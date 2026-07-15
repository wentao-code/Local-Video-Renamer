from contextlib import nullcontext

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET
from app.services.enrichment import start_progress_tracker
from app.services.enrichment.library_refresh_tracker import (
    LibraryExpiredRefreshTracker,
    sync_actor_refresh_update_statuses,
)
from app.services.resolvers import MovieAuthorResolver


class ActorJavtxtEnrichmentService:
    def __init__(
        self,
        database,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
        planned_actor_names=None,
        planned_items=None,
    ):
        self.database = database
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.planned_actor_names = self._normalize_planned_actor_names(planned_actor_names)
        self.planned_codes_by_actor = self._planned_codes_by_parent(planned_items, 'actor_name')
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
            logger=self.logger,
        )
        self.refresh_tracker = None

    @staticmethod
    def _normalize_planned_actor_names(planned_actor_names):
        actor_names = []
        seen = set()
        for actor_name in planned_actor_names or []:
            normalized = str(actor_name or '').strip()
            if not normalized or normalized in seen:
                continue
            actor_names.append(normalized)
            seen.add(normalized)
        return actor_names

    @staticmethod
    def _planned_codes_by_parent(planned_items, parent_key):
        grouped = {}
        for item in planned_items or []:
            parent = str((item or {}).get(parent_key, '') or '').strip()
            code = MovieAuthorResolver._normalize_code((item or {}).get('code', ''))
            if not parent or not code:
                continue
            grouped.setdefault(parent, [])
            if code not in grouped[parent]:
                grouped[parent].append(code)
        return grouped

    def enrich_next_actors(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        sync_actor_refresh_update_statuses(self.database)
        self.refresh_tracker = LibraryExpiredRefreshTracker(
            self.database,
            'actor',
            JAVTXT_VIDEO_SOURCE,
        )
        ready_actor_infos = self._ready_actor_infos()
        ready_actor_names = [info['actor_name'] for info in ready_actor_infos]
        blocked_count = self._blocked_actor_count()
        remaining_video_count_before = sum(int(info.get('pending_video_count', 0) or 0) for info in ready_actor_infos)
        remaining_video_count_after = remaining_video_count_before
        target_video_count = min(limit, remaining_video_count_before)
        results = []
        progress_state = {
            'processed_video_count': 0,
            'success_video_count': 0,
            'failed_video_count': 0,
        }
        stopped = False
        source_label = get_video_enrichment_source_label(JAVTXT_VIDEO_SOURCE)
        self._log(
            'INFO',
            '演员库 JAVTXT 补全任务启动',
            requested_limit=limit,
            ready_actor_count=len(ready_actor_names),
            blocked_count=blocked_count,
            target_video_count=target_video_count,
            ready_actor_names=' | '.join(ready_actor_names[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '演员库',
                target_video_count,
                source_label=source_label,
                count_unit='视频',
                target_type=ACTOR_LIBRARY_TARGET,
                source_key=JAVTXT_VIDEO_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        session_context = self.author_resolver.session() if self._should_use_task_level_session(ready_actor_infos) else nullcontext()
        with session_context:
            for actor_info in ready_actor_infos:
                actor_name = actor_info['actor_name']
                pending_before = int(actor_info.get('pending_video_count', 0) or 0)
                if self.should_stop():
                    stopped = True
                    self._log('WARNING', '演员库 JAVTXT 补全收到停止请求', processed_count=progress_state['processed_video_count'])
                    break

                remaining_slots = limit - int(progress_state.get('processed_video_count', 0) or 0)
                if remaining_slots <= 0:
                    break

                try:
                    self.refresh_tracker.start(actor_name)
                    result = self._enrich_single_actor(actor_name, remaining_slots, progress_state)
                    result.update(self.refresh_tracker.complete(actor_name, result.get('status')))
                    results.append(result)
                    remaining_video_count_after = remaining_video_count_after - pending_before + int(
                        result.get('remaining_video_count', pending_before) or 0
                    )
                except Exception as exc:
                    error_message = str(exc)
                    self.database.save_actor_enrichment(
                        actor_name=actor_name,
                        status=FAILED_STATUS,
                        total_pages=0,
                        total_videos=0,
                        error=error_message,
                        actor_id='',
                        source_key=JAVTXT_VIDEO_SOURCE,
                    )
                    results.append(
                        {
                            'actor_name': actor_name,
                            'status': FAILED_STATUS,
                            'error': error_message,
                            'processed_video_count': 0,
                            'success_video_count': 0,
                            'failed_video_count': 1,
                            'remaining_video_count': self._pending_actor_video_count(actor_name),
                            'count_unit': '视频',
                        }
                    )
                    remaining_video_count_after = remaining_video_count_after - pending_before + int(
                        results[-1].get('remaining_video_count', pending_before) or 0
                    )
                    progress_state['failed_video_count'] = int(progress_state.get('failed_video_count', 0) or 0) + 1
                    self._log(
                        'ERROR',
                        '演员库 JAVTXT 补全异常，已写入失败状态',
                        actor_name=actor_name,
                        error=error_message,
                    )
                    self._update_progress(
                        int(progress_state.get('processed_video_count', 0) or 0),
                        int(progress_state.get('success_video_count', 0) or 0),
                        int(progress_state.get('failed_video_count', 0) or 0),
                        actor_name,
                    )

        message = ''
        if not ready_actor_names and blocked_count > 0:
            message = f'当前有 {blocked_count} 个演员尚未完成 AVFan 补全，暂时不能使用 JAVTXT 继续补全。'

        result = {
            'requested': limit,
            'processed_count': int(progress_state.get('processed_video_count', 0) or 0),
            'success_count': int(progress_state.get('success_video_count', 0) or 0),
            'failed_count': int(progress_state.get('failed_video_count', 0) or 0),
            'remaining_count': max(0, int(remaining_video_count_after or 0)),
            'results': results,
            'processed_items': [
                dict(item or {})
                for actor_result in results
                for item in (actor_result or {}).get('processed_items', []) or []
            ],
            'stopped': stopped,
            'entity_label': '演员库 / JAVTXT',
            'source_key': JAVTXT_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余待补全视频',
            'message': message,
            'blocked_count': blocked_count,
            'count_unit': '视频',
        }
        finish_message = message or ('演员库 JAVTXT 补全已完成。' if not stopped else '演员库 JAVTXT 补全已停止。')
        self._finish_progress(finish_message, stopped=stopped)
        self._log(
            'INFO',
            '演员库 JAVTXT 补全任务结束',
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            blocked_count=blocked_count,
            stopped=stopped,
        )
        return result

    def list_plan_candidate_names(self, limit):
        names = []
        seen = set()
        for item in self.list_plan_candidate_items(limit):
            actor_name = str(item.get('actor_name', '') or '').strip()
            if actor_name and actor_name not in seen:
                names.append(actor_name)
                seen.add(actor_name)
        return names

    def list_plan_candidate_items(self, limit):
        """Build concrete video-code candidates with three bulk reads, never per actor."""
        limit = max(0, int(limit or 0))
        if limit <= 0:
            return []
        sync_actor_refresh_update_statuses(self.database)
        records = self.database.list_actor_enrichment_records()
        planned_names = set(self.planned_actor_names)
        movies = [
            dict(row or {})
            for row in self.database.list_all_actor_movies()
            if str((row or {}).get('actor_name', '') or '').strip()
        ]
        cached_rows = self.database.get_javtxt_actor_cache_by_codes(
            [row.get('code', '') for row in movies]
        )
        candidates = []
        seen = set()
        for movie in movies:
            actor_name = str(movie.get('actor_name', '') or '').strip()
            if planned_names and actor_name not in planned_names:
                continue
            if not self._is_ready_for_javtxt(records.get(actor_name, {})):
                continue
            should_attempt, _reason = self.author_resolver._should_attempt_lookup(movie, cached_rows)
            code = self.author_resolver._normalize_code(movie.get('code', ''))
            identity = (actor_name, code)
            if not should_attempt or not code or identity in seen:
                continue
            candidates.append({'actor_name': actor_name, 'code': code})
            seen.add(identity)
            if len(candidates) >= limit:
                break
        return candidates

    def _should_use_task_level_session(self, ready_actor_infos):
        return bool(ready_actor_infos) and type(self)._enrich_single_actor is ActorJavtxtEnrichmentService._enrich_single_actor

    def _ready_actor_infos(self):
        if self.planned_codes_by_actor:
            return [
                {'actor_name': actor_name, 'pending_video_count': len(codes)}
                for actor_name, codes in self.planned_codes_by_actor.items()
                if codes
            ]
        records = self.database.list_actor_enrichment_records()
        refresh_tracker = self.refresh_tracker or LibraryExpiredRefreshTracker(
            self.database,
            'actor',
            JAVTXT_VIDEO_SOURCE,
        )
        actor_infos = []
        source_names = self.planned_actor_names or [
            str((row or {}).get('name', '') or '').strip()
            for row in self.database.list_actors()
        ]
        for actor_name in source_names:
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            if not self._is_ready_for_javtxt(record):
                continue

            movies = self.database.list_actor_movies(actor_name)
            pending_count = self.author_resolver.count_pending_entries(movies)
            if pending_count <= 0 and not refresh_tracker.is_expired(actor_name):
                continue

            actor_infos.append(
                {
                    'actor_name': actor_name,
                    'pending_video_count': pending_count,
                }
            )
            self._log(
                'INFO',
                '演员已进入 JAVTXT 待补全队列',
                actor_name=actor_name,
                pending_video_count=pending_count,
                avfan_total_videos=record.get('avfan_total_videos', 0),
            )
        return actor_infos

    def _ready_actor_names(self):
        return [info['actor_name'] for info in self._ready_actor_infos()]

    def _remaining_actor_video_count(self, ready_actor_names=None):
        actor_names = ready_actor_names if ready_actor_names is not None else self._ready_actor_names()
        return sum(self._pending_actor_video_count(actor_name) for actor_name in actor_names)

    def _pending_actor_video_count(self, actor_name):
        movies = self.database.list_actor_movies(actor_name)
        return self.author_resolver.count_pending_entries(movies)

    def _blocked_actor_count(self):
        if self.planned_codes_by_actor:
            return 0
        records = self.database.list_actor_enrichment_records()
        blocked = 0
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and not self._is_ready_for_javtxt(record):
                blocked += 1
        return blocked

    @staticmethod
    def _is_ready_for_javtxt(record):
        avfan_status = str((record or {}).get('avfan_enrichment_status', '') or '').strip()
        avfan_total_videos = int((record or {}).get('avfan_total_videos', 0) or 0)
        return avfan_status == ENRICHED_STATUS and avfan_total_videos > 0

    def _enrich_single_actor(self, actor_name, max_video_count, progress_state):
        all_movies = self.database.list_actor_movies(actor_name)
        if not all_movies:
            raise RuntimeError('请先使用 AVFan 补全演员库作品列表。')
        planned_codes = set(self.planned_codes_by_actor.get(actor_name, []))
        movies = [
            movie for movie in all_movies
            if not planned_codes or self.author_resolver._normalize_code(movie.get('code', '')) in planned_codes
        ]
        if not movies:
            raise RuntimeError('待补全表中的具体番号已不在演员作品列表中。')

        progress_state['_processed_offset'] = int(progress_state.get('processed_video_count', 0) or 0)
        progress_state['_success_offset'] = int(progress_state.get('success_video_count', 0) or 0)
        progress_state['_failed_offset'] = int(progress_state.get('failed_video_count', 0) or 0)
        pending_before = self.author_resolver.count_pending_entries(movies)
        self._log(
            'INFO',
            '开始处理演员的 JAVTXT 补全',
            actor_name=actor_name,
            movie_count=len(movies),
            pending_video_count=pending_before,
            max_video_count=max_video_count,
        )

        resolution = self.author_resolver.enrich_entries_with_details(
            movies,
            max_lookup_count=max_video_count,
            progress_callback=lambda update: self._on_video_progress(update, progress_state, actor_name),
        )
        processed_items = self._resolved_planned_items(resolution, planned_codes)

        enriched_movies = resolution.get('entries', [])
        merged_movies = enriched_movies
        if planned_codes:
            enriched_by_code = {
                self.author_resolver._normalize_code(movie.get('code', '')): movie
                for movie in enriched_movies
            }
            merged_movies = [
                enriched_by_code.get(self.author_resolver._normalize_code(movie.get('code', '')), movie)
                for movie in all_movies
            ]
        completed = self.author_resolver.count_pending_entries(merged_movies) <= 0
        status = ENRICHED_STATUS if completed else UNENRICHED_STATUS
        self.database.replace_actor_movies(actor_name, merged_movies)
        self.database.save_actor_enrichment(
            actor_name=actor_name,
            status=status,
            total_pages=0,
            total_videos=len(merged_movies),
            error='',
            actor_id='',
            source_key=JAVTXT_VIDEO_SOURCE,
        )
        self._log(
            'INFO',
            '演员 JAVTXT 补全完成并写库',
            actor_name=actor_name,
            status=status,
            movie_count=len(merged_movies),
            processed_video_count=int(resolution.get('processed_video_count', 0) or 0),
            success_video_count=int(resolution.get('success_video_count', 0) or 0),
            failed_video_count=int(resolution.get('failed_video_count', 0) or 0),
            remaining_video_count=int(resolution.get('pending_video_count', 0) or 0),
        )
        return {
            'actor_name': actor_name,
            'status': status,
            'video_count': len(merged_movies),
            'processed_video_count': int(resolution.get('processed_video_count', 0) or 0),
            'success_video_count': int(resolution.get('success_video_count', 0) or 0),
            'failed_video_count': int(resolution.get('failed_video_count', 0) or 0),
            'remaining_video_count': int(resolution.get('pending_video_count', 0) or 0),
            'processed_items': [
                {**dict(item or {}), 'actor_name': actor_name}
                for item in processed_items
            ],
            'count_unit': '视频',
        }

    def _resolved_planned_items(self, resolution, planned_codes):
        processed_items = [dict(item or {}) for item in resolution.get('processed_items', []) or []]
        seen_codes = {
            self.author_resolver._normalize_code(item.get('code', ''))
            for item in processed_items
        }
        for movie in resolution.get('entries', []) or []:
            code = self.author_resolver._normalize_code((movie or {}).get('code', ''))
            if not code or code in seen_codes or (planned_codes and code not in planned_codes):
                continue
            should_attempt, _reason = self.author_resolver._should_attempt_lookup(movie, {})
            if should_attempt:
                continue
            processed_items.append(
                {'code': code, 'status': str((movie or {}).get('javtxt_enrichment_status', '') or '').strip()}
            )
            seen_codes.add(code)
        return processed_items

    def _update_progress(self, processed_count, success_count, failed_count, current_item):
        if self.progress_tracker is not None:
            self.progress_tracker.update(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                current_item=current_item,
            )
        self._log(
            'INFO',
            '演员库 JAVTXT 补全进度更新',
            processed_count=processed_count,
            success_count=success_count,
            failed_count=failed_count,
            current_item=current_item,
        )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)

    def _on_video_progress(self, update, progress_state, actor_name):
        offset_processed = int(progress_state.get('_processed_offset', 0) or 0)
        offset_success = int(progress_state.get('_success_offset', 0) or 0)
        offset_failed = int(progress_state.get('_failed_offset', 0) or 0)

        progress_state['processed_video_count'] = offset_processed + int(update.get('processed_video_count', 0) or 0)
        progress_state['success_video_count'] = offset_success + int(update.get('success_video_count', 0) or 0)
        progress_state['failed_video_count'] = offset_failed + int(update.get('failed_video_count', 0) or 0)

        self._log(
            'INFO',
            '演员下视频作者补全进度更新',
            actor_name=actor_name,
            code=str(update.get('code', '') or ''),
            status=str(update.get('status', '') or ''),
            processed_video_count=progress_state['processed_video_count'],
            success_video_count=progress_state['success_video_count'],
            failed_video_count=progress_state['failed_video_count'],
        )
        self._update_progress(
            progress_state['processed_video_count'],
            progress_state['success_video_count'],
            progress_state['failed_video_count'],
            str(update.get('code', '') or ''),
        )

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='actor_javtxt_enrichment', **fields)
