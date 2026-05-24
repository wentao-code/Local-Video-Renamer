from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.scraper.avfan_actor_scraper import AvfanActorScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.services.actor_search_entry_parser import parse_actor_search_card


class ActorEnrichmentService:
    def __init__(self, database, scraper=None, show_browser=False, should_stop=None, progress_tracker=None):
        self.database = database
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.scraper = scraper or AvfanActorScraper(headless=not show_browser)

    def enrich_next_actors(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self._candidate_actors(limit)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(AVFAN_VIDEO_SOURCE)

        if self.progress_tracker is not None:
            self.progress_tracker.start('演员库', len(candidates), source_label=source_label)

        for actor_name in candidates:
            if self.should_stop():
                stopped = True
                break

            try:
                with self.scraper.session() as page:
                    result = self._enrich_single_actor(page, actor_name)
                results.append(result)
                if result.get('stopped'):
                    stopped = True
                    self._update_progress(len(results), success_count, failed_count + 1, actor_name)
                    break
                if result.get('status') == ENRICHED_STATUS:
                    success_count += 1
                else:
                    failed_count += 1
            except HumanVerificationRequiredError as exc:
                error_message = str(exc)
                self.database.save_actor_enrichment(
                    actor_name=actor_name,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                    actor_id='',
                    source_key=AVFAN_VIDEO_SOURCE,
                )
                results.append({
                    'actor_name': actor_name,
                    'status': FAILED_STATUS,
                    'error': error_message,
                })
                failed_count += 1
                self._update_progress(len(results), success_count, failed_count, actor_name)
                result = {
                    'requested': limit,
                    'processed_count': len(results),
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'remaining_count': self._remaining_actor_count(),
                    'results': results,
                    'stopped': True,
                    'requires_manual_verification': True,
                    'message': error_message,
                    'entity_label': '演员',
                    'source_key': AVFAN_VIDEO_SOURCE,
                    'source_label': source_label,
                    'remaining_label': '剩余未补全演员',
                }
                self._finish_progress(error_message, stopped=True)
                return result
            except Exception as exc:
                error_message = str(exc)
                self.database.save_actor_enrichment(
                    actor_name=actor_name,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                    actor_id='',
                    source_key=AVFAN_VIDEO_SOURCE,
                )
                results.append({
                    'actor_name': actor_name,
                    'status': FAILED_STATUS,
                    'error': error_message,
                })
                failed_count += 1

            self._update_progress(len(results), success_count, failed_count, actor_name)

        result = {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self._remaining_actor_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '演员',
            'source_key': AVFAN_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余未补全演员',
        }
        self._finish_progress('演员库补全已完成。' if not stopped else '演员库补全已停止。', stopped=stopped)
        return result

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

    def _candidate_actors(self, limit):
        records = self.database.list_actor_enrichment_records()
        actors = []
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            status = records.get(actor_name, {}).get('avfan_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
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
            status = records.get(actor_name, {}).get('avfan_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
                remaining += 1
        return remaining

    def _enrich_single_actor(self, page, actor_name):
        parsed_entries = []
        actor_page_url = self.scraper.open_listing_page(page, actor_name, 1)
        actor_id = self.scraper.extract_actor_id(actor_page_url)
        total_pages = self.scraper.detect_total_pages(page)
        stopped_early = False

        for page_number in range(1, total_pages + 1):
            if self.should_stop():
                stopped_early = True
                break
            if page_number > 1:
                self.scraper.open_listing_page(page, actor_name, page_number)
            parsed_entries.extend(
                self._parse_entries(actor_name, self.scraper.collect_page_entries(page), page_number)
            )

        if stopped_early:
            return {
                'actor_name': actor_name,
                'status': FAILED_STATUS,
                'error': '用户已停止补全',
                'stopped': True,
            }

        unique_entries = self._dedupe_entries(parsed_entries)
        if unique_entries:
            self.database.replace_actor_movies(actor_name, unique_entries)
            self.database.save_actor_enrichment(
                actor_name=actor_name,
                status=ENRICHED_STATUS,
                total_pages=total_pages,
                total_videos=len(unique_entries),
                error='',
                actor_id=actor_id,
                source_key=AVFAN_VIDEO_SOURCE,
            )
            return {
                'actor_name': actor_name,
                'status': ENRICHED_STATUS,
                'total_pages': total_pages,
                'video_count': len(unique_entries),
            }

        self.database.replace_actor_movies(actor_name, [])
        self.database.save_actor_enrichment(
            actor_name=actor_name,
            status=NO_SEARCH_RESULTS_STATUS,
            total_pages=total_pages,
            total_videos=0,
            error='未搜索到演员作品页面内容',
            actor_id=actor_id,
            source_key=AVFAN_VIDEO_SOURCE,
        )
        return {
            'actor_name': actor_name,
            'status': NO_SEARCH_RESULTS_STATUS,
            'total_pages': total_pages,
            'video_count': 0,
            'error': '未搜索到演员作品页面内容',
        }

    def _parse_entries(self, actor_name, rows, page_number):
        parsed = []
        for row in rows:
            card = parse_actor_search_card(
                text=row.get('text', ''),
                href=row.get('href', ''),
                actor_name=actor_name,
                page_number=page_number,
            )
            if not card.get('code'):
                continue
            parsed.append(card)
        return parsed

    @staticmethod
    def _dedupe_entries(entries):
        deduped = {}
        for entry in entries:
            code = entry.get('code', '')
            if not code:
                continue
            deduped[code] = entry
        return [deduped[key] for key in sorted(deduped)]
