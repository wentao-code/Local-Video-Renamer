from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import CODE_PREFIX_LIBRARY_TARGET
from app.services.enrichment import start_progress_tracker
from app.services.enrichment.library_refresh_tracker import (
    LibraryExpiredRefreshTracker,
    sync_code_prefix_refresh_update_statuses,
)
from app.services.library import CodePrefixLibrary
from app.services.resolvers import MovieAuthorResolver


class CodePrefixJavtxtEnrichmentService:
    def __init__(
        self,
        database,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
        planned_prefixes=None,
        planned_items=None,
    ):
        self.database = database
        self.prefix_library = CodePrefixLibrary(database)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.planned_prefixes = self._normalize_planned_prefixes(planned_prefixes)
        self.planned_codes_by_prefix = self._planned_codes_by_parent(planned_items, 'prefix')
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
            logger=self.logger,
        )
        self.refresh_tracker = None

    @staticmethod
    def _normalize_planned_prefixes(planned_prefixes):
        prefixes = []
        seen = set()
        for prefix in planned_prefixes or []:
            normalized = str(prefix or '').strip().upper()
            if not normalized or normalized in seen:
                continue
            prefixes.append(normalized)
            seen.add(normalized)
        return prefixes

    @staticmethod
    def _planned_codes_by_parent(planned_items, parent_key):
        grouped = {}
        for item in planned_items or []:
            parent = str((item or {}).get(parent_key, '') or '').strip().upper()
            code = MovieAuthorResolver._normalize_code((item or {}).get('code', ''))
            if not parent or not code:
                continue
            grouped.setdefault(parent, [])
            if code not in grouped[parent]:
                grouped[parent].append(code)
        return grouped

    def enrich_next_prefixes(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        sync_code_prefix_refresh_update_statuses(self.database, self.prefix_library)
        self.refresh_tracker = LibraryExpiredRefreshTracker(
            self.database,
            'code_prefix',
            JAVTXT_VIDEO_SOURCE,
        )
        ready_prefix_infos = self._ready_prefix_infos()
        ready_prefixes = [info['prefix'] for info in ready_prefix_infos]
        blocked_count = self._blocked_prefix_count()
        remaining_video_count_before = sum(int(info.get('pending_video_count', 0) or 0) for info in ready_prefix_infos)
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
            '番号库辛聚谷补全任务启动',
            requested_limit=limit,
            ready_prefix_count=len(ready_prefixes),
            blocked_count=blocked_count,
            target_video_count=target_video_count,
            ready_prefixes=','.join(ready_prefixes[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '番号库',
                target_video_count,
                source_label=source_label,
                count_unit='视频',
                target_type=CODE_PREFIX_LIBRARY_TARGET,
                source_key=JAVTXT_VIDEO_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        # Reuse one JAVTXT browser session across the whole batch so moving
        # to the next prefix does not reopen the browser window.
        with self.author_resolver.session():
            for prefix_info in ready_prefix_infos:
                prefix = prefix_info['prefix']
                pending_before = int(prefix_info.get('pending_video_count', 0) or 0)
                if self.should_stop():
                    stopped = True
                    self._log('WARNING', '番号库辛聚谷补全收到停止请求', processed_count=progress_state['processed_video_count'])
                    break

                remaining_slots = limit - int(progress_state.get('processed_video_count', 0) or 0)
                if remaining_slots <= 0:
                    break

                try:
                    self.refresh_tracker.start(prefix)
                    result = self._enrich_single_prefix(prefix, remaining_slots, progress_state)
                    result.update(self.refresh_tracker.complete(prefix, result.get('status')))
                    results.append(result)
                    remaining_video_count_after = remaining_video_count_after - pending_before + int(
                        result.get('remaining_video_count', pending_before) or 0
                    )
                except Exception as exc:
                    error_message = str(exc)
                    self.database.save_code_prefix_enrichment(
                        prefix=prefix,
                        status=FAILED_STATUS,
                        total_pages=0,
                        total_videos=0,
                        error=error_message,
                        source_key=JAVTXT_VIDEO_SOURCE,
                    )
                    results.append(
                        {
                            'prefix': prefix,
                            'status': FAILED_STATUS,
                            'error': error_message,
                            'processed_video_count': 0,
                            'success_video_count': 0,
                            'failed_video_count': 1,
                            'remaining_video_count': self._pending_prefix_video_count(prefix),
                            'count_unit': '视频',
                        }
                    )
                    remaining_video_count_after = remaining_video_count_after - pending_before + int(
                        results[-1].get('remaining_video_count', pending_before) or 0
                    )
                    progress_state['failed_video_count'] = int(progress_state.get('failed_video_count', 0) or 0) + 1
                    self._log(
                        'ERROR',
                        '番号库辛聚谷补全异常，已写入失败状态',
                        prefix=prefix,
                        error=error_message,
                    )
                    self._update_progress(
                        int(progress_state.get('processed_video_count', 0) or 0),
                        int(progress_state.get('success_video_count', 0) or 0),
                        int(progress_state.get('failed_video_count', 0) or 0),
                        prefix,
                    )

        message = ''
        if not ready_prefixes and blocked_count > 0:
            message = f'当前有 {blocked_count} 个番号尚未完成天陨阁补全，暂时不能使用辛聚谷继续补全。'

        result = {
            'requested': limit,
            'processed_count': int(progress_state.get('processed_video_count', 0) or 0),
            'success_count': int(progress_state.get('success_video_count', 0) or 0),
            'failed_count': int(progress_state.get('failed_video_count', 0) or 0),
            'remaining_count': max(0, int(remaining_video_count_after or 0)),
            'results': results,
            'processed_items': [
                dict(item or {})
                for prefix_result in results
                for item in (prefix_result or {}).get('processed_items', []) or []
            ],
            'stopped': stopped,
            'entity_label': '番号库 / 辛聚谷',
            'source_key': JAVTXT_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余待补全视频',
            'message': message,
            'blocked_count': blocked_count,
            'count_unit': '视频',
        }
        finish_message = message or ('番号库辛聚谷补全已完成。' if not stopped else '番号库辛聚谷补全已停止。')
        self._finish_progress(finish_message, stopped=stopped)
        self._log(
            'INFO',
            '番号库辛聚谷补全任务结束',
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            blocked_count=blocked_count,
            stopped=stopped,
        )
        return result

    def list_plan_candidate_prefixes(self, limit):
        prefixes = []
        seen = set()
        for item in self.list_plan_candidate_items(limit):
            prefix = str(item.get('prefix', '') or '').strip().upper()
            if prefix and prefix not in seen:
                prefixes.append(prefix)
                seen.add(prefix)
        return prefixes

    def list_plan_candidate_items(self, limit):
        """Build concrete video-code candidates with bulk reads, never per prefix."""
        limit = max(0, int(limit or 0))
        if limit <= 0:
            return []
        sql_candidate_getter = getattr(self.database, 'list_sql_javtxt_candidate_items', None)
        if callable(sql_candidate_getter):
            sql_rows = list(sql_candidate_getter('code_prefix', max(limit * 20, limit)) or [])
            records = {}
            movies = []
            cached_rows = {}
            for row in sql_rows:
                current = dict(row or {})
                code = self.author_resolver._normalize_code(current.get('code', ''))
                cached_rows[code] = {
                    'code': code,
                    'javtxt_actors': current.pop('cached_javtxt_actors', ''),
                    'javtxt_actors_raw': current.pop('cached_javtxt_actors_raw', ''),
                    'javtxt_movie_id': current.pop('cached_javtxt_movie_id', ''),
                    'javtxt_url': current.pop('cached_javtxt_url', ''),
                    'javtxt_tags': current.pop('cached_javtxt_tags', ''),
                    'javtxt_enrichment_status': current.pop('cached_javtxt_enrichment_status', UNENRICHED_STATUS),
                    'javtxt_release_date': current.pop('cached_javtxt_release_date', ''),
                    'release_date': current.pop('cached_release_date', ''),
                }
                movies.append(current)
        else:
            sync_code_prefix_refresh_update_statuses(self.database, self.prefix_library)
            records = self.database.list_code_prefix_enrichment_records()
            movies = [dict(row or {}) for row in self.database.list_all_code_prefix_movies()]
            cached_rows = self.database.get_javtxt_actor_cache_by_codes(
                [row.get('code', '') for row in movies]
            )
        planned_prefixes = set(self.planned_prefixes)
        candidates = []
        seen = set()
        for movie in movies:
            prefix = str(movie.get('prefix', '') or '').strip().upper()
            if not prefix or (planned_prefixes and prefix not in planned_prefixes):
                continue
            if not callable(sql_candidate_getter) and not self._is_ready_for_javtxt(records.get(prefix, {})):
                continue
            should_attempt, _reason = self.author_resolver._should_attempt_lookup(movie, cached_rows)
            code = self.author_resolver._normalize_code(movie.get('code', ''))
            identity = (prefix, code)
            if not should_attempt or not code or identity in seen:
                continue
            candidates.append({'prefix': prefix, 'code': code})
            seen.add(identity)
            if len(candidates) >= limit:
                break
        return candidates

    def _ready_prefix_infos(self):
        if self.planned_codes_by_prefix:
            return [
                {'prefix': prefix, 'pending_video_count': len(codes)}
                for prefix, codes in self.planned_codes_by_prefix.items()
                if codes
            ]
        records = self.database.list_code_prefix_enrichment_records()
        refresh_tracker = self.refresh_tracker or LibraryExpiredRefreshTracker(
            self.database,
            'code_prefix',
            JAVTXT_VIDEO_SOURCE,
        )
        prefix_infos = []
        source_prefixes = self.planned_prefixes or [
            str((row or {}).get('prefix', '') or '').strip().upper()
            for row in self.prefix_library.list_prefixes()
        ]
        for prefix in source_prefixes:
            record = records.get(prefix, {})
            if not self._is_ready_for_javtxt(record):
                continue

            movies = self.database.list_code_prefix_movies(prefix)
            pending_count = self.author_resolver.count_pending_entries(movies)
            if pending_count <= 0 and not refresh_tracker.is_expired(prefix):
                continue

            prefix_infos.append(
                {
                    'prefix': prefix,
                    'pending_video_count': pending_count,
                }
            )
            self._log(
                'INFO',
                '番号前缀已进入辛聚谷待补全队列',
                prefix=prefix,
                pending_video_count=pending_count,
                avfan_total_videos=record.get('avfan_total_videos', 0),
            )
        return prefix_infos

    def _ready_prefixes(self):
        return [info['prefix'] for info in self._ready_prefix_infos()]

    def _remaining_prefix_video_count(self, prefixes=None):
        target_prefixes = prefixes if prefixes is not None else self._ready_prefixes()
        return sum(self._pending_prefix_video_count(prefix) for prefix in target_prefixes)

    def _pending_prefix_video_count(self, prefix):
        movies = self.database.list_code_prefix_movies(prefix)
        return self.author_resolver.count_pending_entries(movies)

    def _blocked_prefix_count(self):
        if self.planned_codes_by_prefix:
            return 0
        records = self.database.list_code_prefix_enrichment_records()
        blocked = 0
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            record = records.get(prefix, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and not self._is_ready_for_javtxt(record):
                blocked += 1
        return blocked

    @staticmethod
    def _is_ready_for_javtxt(record):
        avfan_status = str((record or {}).get('avfan_enrichment_status', '') or '').strip()
        avfan_total_videos = int((record or {}).get('avfan_total_videos', 0) or 0)
        return avfan_status == ENRICHED_STATUS and avfan_total_videos > 0

    def _enrich_single_prefix(self, prefix, max_video_count, progress_state):
        all_movies = self.database.list_code_prefix_movies(prefix)
        if not all_movies:
            raise RuntimeError('请先使用天陨阁补全番号库作品列表。')
        planned_codes = set(self.planned_codes_by_prefix.get(prefix, []))
        movies = [
            movie for movie in all_movies
            if not planned_codes or self.author_resolver._normalize_code(movie.get('code', '')) in planned_codes
        ]
        if not movies:
            raise RuntimeError('待补全表中的具体番号已不在番号作品列表中。')

        progress_state['_processed_offset'] = int(progress_state.get('processed_video_count', 0) or 0)
        progress_state['_success_offset'] = int(progress_state.get('success_video_count', 0) or 0)
        progress_state['_failed_offset'] = int(progress_state.get('failed_video_count', 0) or 0)
        pending_before = self.author_resolver.count_pending_entries(movies)
        self._log(
            'INFO',
            '开始处理番号前缀的辛聚谷演员补全',
            prefix=prefix,
            movie_count=len(movies),
            pending_video_count=pending_before,
            max_video_count=max_video_count,
        )

        resolution = self.author_resolver.enrich_entries_with_details(
            movies,
            max_lookup_count=max_video_count,
            progress_callback=lambda update: self._on_video_progress(update, progress_state, prefix),
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
        self.database.replace_code_prefix_movies(prefix, merged_movies)
        self.database.save_code_prefix_enrichment(
            prefix=prefix,
            status=status,
            total_pages=0,
            total_videos=len(merged_movies),
            error='',
            source_key=JAVTXT_VIDEO_SOURCE,
        )
        self._log(
            'INFO',
            '番号前缀辛聚谷补全完成并写库',
            prefix=prefix,
            status=status,
            movie_count=len(merged_movies),
            processed_video_count=int(resolution.get('processed_video_count', 0) or 0),
            success_video_count=int(resolution.get('success_video_count', 0) or 0),
            failed_video_count=int(resolution.get('failed_video_count', 0) or 0),
            remaining_video_count=int(resolution.get('pending_video_count', 0) or 0),
        )
        return {
            'prefix': prefix,
            'status': status,
            'video_count': len(merged_movies),
            'processed_video_count': int(resolution.get('processed_video_count', 0) or 0),
            'success_video_count': int(resolution.get('success_video_count', 0) or 0),
            'failed_video_count': int(resolution.get('failed_video_count', 0) or 0),
            'remaining_video_count': int(resolution.get('pending_video_count', 0) or 0),
            'processed_items': [
                {**dict(item or {}), 'prefix': prefix}
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
            '番号库辛聚谷补全进度更新',
            processed_count=processed_count,
            success_count=success_count,
            failed_count=failed_count,
            current_item=current_item,
        )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)

    def _on_video_progress(self, update, progress_state, prefix):
        offset_processed = int(progress_state.get('_processed_offset', 0) or 0)
        offset_success = int(progress_state.get('_success_offset', 0) or 0)
        offset_failed = int(progress_state.get('_failed_offset', 0) or 0)

        progress_state['processed_video_count'] = offset_processed + int(update.get('processed_video_count', 0) or 0)
        progress_state['success_video_count'] = offset_success + int(update.get('success_video_count', 0) or 0)
        progress_state['failed_video_count'] = offset_failed + int(update.get('failed_video_count', 0) or 0)

        self._log(
            'INFO',
            '番号前缀下视频作者补全进度更新',
            prefix=prefix,
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
            self.logger.log(level, message, service='code_prefix_javtxt_enrichment', **fields)
