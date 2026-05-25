from app.core.enrichment_sources import (
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    build_video_remaining_label,
    get_video_enrichment_source_label,
    normalize_video_enrichment_source,
)
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import VIDEO_LIBRARY_TARGET
from app.scraper.avfan_scraper import AvfanScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.scraper.javtxt_scraper import JavtxtScraper


class VideoSourceEnrichmentService:
    def __init__(
        self,
        database,
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        scraper=None,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
        progress_tracker=None,
    ):
        self.database = database
        self.source_key = normalize_video_enrichment_source(source_key)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.scraper = scraper or self._build_scraper(show_browser, cooldown_before_search)

    def _build_scraper(self, show_browser, cooldown_before_search):
        if self.source_key == JAVTXT_VIDEO_SOURCE:
            return JavtxtScraper(headless=not show_browser)
        return AvfanScraper(
            headless=not show_browser,
            cooldown_before_search=cooldown_before_search,
        )

    def enrich_next_videos(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self.database.list_videos_for_enrichment(limit, self.source_key)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(self.source_key)

        if self.progress_tracker is not None:
            self.progress_tracker.start(
                '视频库',
                len(candidates),
                source_label=source_label,
                count_unit='视频',
                target_type=VIDEO_LIBRARY_TARGET,
                source_key=self.source_key,
            )

        with self.scraper.session():
            for video in candidates:
                if self.should_stop():
                    stopped = True
                    break

                code = video.get('code', '')
                try:
                    info = self.scraper.fetch_by_code(code)
                    if info.get('found'):
                        self.database.update_video_enrichment(
                            code,
                            info,
                            ENRICHED_STATUS,
                            source_key=self.source_key,
                        )
                        success_count += 1
                        results.append(
                            {
                                'code': code,
                                'status': ENRICHED_STATUS,
                                'info': info,
                            }
                        )
                    else:
                        error_message = info.get('error', '未搜索到匹配影片')
                        self.database.mark_video_no_search_results(
                            code,
                            error_message,
                            source_key=self.source_key,
                        )
                        failed_count += 1
                        results.append(
                            {
                                'code': code,
                                'status': NO_SEARCH_RESULTS_STATUS,
                                'error': error_message,
                            }
                        )
                except HumanVerificationRequiredError as exc:
                    error_message = str(exc)
                    self.database.mark_video_enrichment_failed(
                        code,
                        error_message,
                        source_key=self.source_key,
                    )
                    failed_count += 1
                    results.append(
                        {
                            'code': code,
                            'status': FAILED_STATUS,
                            'error': error_message,
                        }
                    )
                    self._update_progress(len(results), success_count, failed_count, code)
                    result = self._build_result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        True,
                        source_label,
                        requires_manual_verification=True,
                        message=error_message,
                    )
                    self._finish_progress(error_message, stopped=True)
                    return result
                except Exception as exc:
                    error_message = str(exc)
                    self.database.mark_video_enrichment_failed(
                        code,
                        error_message,
                        source_key=self.source_key,
                    )
                    failed_count += 1
                    results.append(
                        {
                            'code': code,
                            'status': FAILED_STATUS,
                            'error': error_message,
                        }
                    )

                self._update_progress(len(results), success_count, failed_count, code)

        result = self._build_result(limit, results, success_count, failed_count, stopped, source_label)
        self._finish_progress('视频补全已完成。' if not stopped else '视频补全已停止。', stopped=stopped)
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

    def _build_result(
        self,
        limit,
        results,
        success_count,
        failed_count,
        stopped,
        source_label,
        requires_manual_verification=False,
        message='',
    ):
        return {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self.database.count_videos_by_enrichment_status(
                UNENRICHED_STATUS,
                source_key=self.source_key,
            )
            + self.database.count_videos_by_enrichment_status(
                FAILED_STATUS,
                source_key=self.source_key,
            ),
            'results': results,
            'stopped': stopped,
            'requires_manual_verification': requires_manual_verification,
            'message': message,
            'entity_label': '视频',
            'source_key': self.source_key,
            'source_label': source_label,
            'remaining_label': build_video_remaining_label(self.source_key),
        }
