from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.services.movie_author_resolver import MovieAuthorResolver


class ActorJavtxtEnrichmentService:
    def __init__(self, database, show_browser=False, should_stop=None, progress_tracker=None):
        self.database = database
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
        )

    def enrich_next_actors(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self._candidate_actors(limit)
        blocked_count = self._blocked_actor_count()
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(JAVTXT_VIDEO_SOURCE)

        if self.progress_tracker is not None:
            self.progress_tracker.start('演员库', len(candidates), source_label=source_label)

        for actor_name in candidates:
            if self.should_stop():
                stopped = True
                break

            try:
                result = self._enrich_single_actor(actor_name)
                results.append(result)
                if result.get('status') == ENRICHED_STATUS:
                    success_count += 1
                else:
                    failed_count += 1
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
                results.append({
                    'actor_name': actor_name,
                    'status': FAILED_STATUS,
                    'error': error_message,
                })
                failed_count += 1

            self._update_progress(len(results), success_count, failed_count, actor_name)

        message = ''
        if not candidates and blocked_count > 0:
            message = f'有 {blocked_count} 个演员尚未完成天阙阁补全，暂不能使用辛聚谷继续补全。'

        result = {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self._remaining_actor_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '演员',
            'source_key': JAVTXT_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余未用辛聚谷补全演员',
            'message': message,
            'blocked_count': blocked_count,
        }
        finish_message = message or ('演员库主演补全已完成。' if not stopped else '演员库主演补全已停止。')
        self._finish_progress(finish_message, stopped=stopped)
        return result

    def _candidate_actors(self, limit):
        records = self.database.list_actor_enrichment_records()
        actors = []
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and self._is_ready_for_javtxt(record):
                actors.append(actor_name)
            if len(actors) >= limit:
                break
        return actors

    def _remaining_actor_count(self):
        records = self.database.list_actor_enrichment_records()
        remaining = 0
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and self._is_ready_for_javtxt(record):
                remaining += 1
        return remaining

    def _blocked_actor_count(self):
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

    def _enrich_single_actor(self, actor_name):
        movies = self.database.list_actor_movies(actor_name)
        if not movies:
            raise RuntimeError('请先使用天阙阁补全演员库作品列表。')

        with self.author_resolver.session():
            enriched_movies = self.author_resolver.enrich_entries(movies)

        self.database.replace_actor_movies(actor_name, enriched_movies)
        self.database.save_actor_enrichment(
            actor_name=actor_name,
            status=ENRICHED_STATUS,
            total_pages=0,
            total_videos=len(enriched_movies),
            error='',
            actor_id='',
            source_key=JAVTXT_VIDEO_SOURCE,
        )
        return {
            'actor_name': actor_name,
            'status': ENRICHED_STATUS,
            'video_count': len(enriched_movies),
        }

    def _update_progress(self, processed_count, success_count, failed_count, current_item):
        if self.progress_tracker is not None:
            self.progress_tracker.update(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                current_item=current_item,
            )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)
