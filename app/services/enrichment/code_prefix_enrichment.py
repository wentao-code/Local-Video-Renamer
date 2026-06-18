from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import CODE_PREFIX_LIBRARY_TARGET
from app.scraper.avfan_code_prefix_scraper import AvfanCodePrefixScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.services.enrichment import start_progress_tracker
from app.services.library import CodePrefixLibrary, extract_code_prefix
from app.services.parsers import parse_code_prefix_card


class CodePrefixEnrichmentService:
    def __init__(
        self,
        database,
        scraper=None,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
    ):
        self.database = database
        self.prefix_library = CodePrefixLibrary(database)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.scraper = scraper or AvfanCodePrefixScraper(headless=not show_browser)

    def enrich_next_prefixes(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self._candidate_prefixes(limit)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(AVFAN_VIDEO_SOURCE)
        self._log(
            'INFO',
            '番号库补全任务启动',
            source_key=AVFAN_VIDEO_SOURCE,
            requested_limit=limit,
            candidate_count=len(candidates),
            candidate_prefixes=','.join(candidates[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '番号库',
                len(candidates),
                source_label=source_label,
                count_unit='番号',
                target_type=CODE_PREFIX_LIBRARY_TARGET,
                source_key=AVFAN_VIDEO_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        # Reuse one browser session across the whole batch so a new prefix
        # does not relaunch the browser window.
        with self.scraper.session() as page:
            for prefix in candidates:
                if self.should_stop():
                    stopped = True
                    self._log('WARNING', '番号库补全收到停止请求', processed_count=len(results))
                    break

                self._log('INFO', '开始处理番号前缀', prefix=prefix)
                try:
                    result = self._enrich_single_prefix(page, prefix)
                    results.append(result)
                    if result.get('stopped'):
                        stopped = True
                        self._update_progress(len(results), success_count, failed_count + 1, prefix)
                        break
                    if result.get('status') == ENRICHED_STATUS:
                        success_count += 1
                    else:
                        failed_count += 1
                except HumanVerificationRequiredError as exc:
                    error_message = str(exc)
                    self.database.save_code_prefix_enrichment(
                        prefix=prefix,
                        status=FAILED_STATUS,
                        total_pages=0,
                        total_videos=0,
                        error=error_message,
                        source_key=AVFAN_VIDEO_SOURCE,
                    )
                    results.append({'prefix': prefix, 'status': FAILED_STATUS, 'error': error_message})
                    failed_count += 1
                    self._log(
                        'ERROR',
                        '番号库补全被人机验证中断',
                        prefix=prefix,
                        error=error_message,
                    )
                    self._update_progress(len(results), success_count, failed_count, prefix)
                    result = {
                        'requested': limit,
                        'processed_count': len(results),
                        'success_count': success_count,
                        'failed_count': failed_count,
                        'remaining_count': self._remaining_prefix_count(),
                        'results': results,
                        'stopped': True,
                        'requires_manual_verification': True,
                        'message': error_message,
                        'entity_label': '番号',
                        'source_key': AVFAN_VIDEO_SOURCE,
                        'source_label': source_label,
                        'remaining_label': '剩余未补全番号',
                    }
                    self._finish_progress(error_message, stopped=True)
                    return result
                except Exception as exc:
                    error_message = str(exc)
                    self.database.save_code_prefix_enrichment(
                        prefix=prefix,
                        status=FAILED_STATUS,
                        total_pages=0,
                        total_videos=0,
                        error=error_message,
                        source_key=AVFAN_VIDEO_SOURCE,
                    )
                    results.append({'prefix': prefix, 'status': FAILED_STATUS, 'error': error_message})
                    failed_count += 1
                    self._log(
                        'ERROR',
                        '番号库补全异常，已写入失败状态',
                        prefix=prefix,
                        error=error_message,
                    )

                self._update_progress(len(results), success_count, failed_count, prefix)

        result = {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self._remaining_prefix_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '番号',
            'source_key': AVFAN_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余未补全番号',
        }
        self._finish_progress('番号补全已完成。' if not stopped else '番号补全已停止。', stopped=stopped)
        self._log(
            'INFO',
            '番号库补全任务结束',
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            stopped=stopped,
        )
        return result

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
            '番号库补全进度更新',
            processed_count=processed_count,
            success_count=success_count,
            failed_count=failed_count,
            current_item=current_item,
        )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)

    def _candidate_prefixes(self, limit):
        records = self.database.list_code_prefix_enrichment_records()
        prefixes = []
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            status = records.get(prefix, {}).get('avfan_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
                prefixes.append(prefix)
            if len(prefixes) >= limit:
                break
        self._log(
            'INFO',
            '已筛选番号库候选前缀',
            candidate_count=len(prefixes),
            candidate_prefixes=','.join(prefixes[:20]),
        )
        return prefixes

    def _remaining_prefix_count(self):
        records = self.database.list_code_prefix_enrichment_records()
        remaining = 0
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            status = records.get(prefix, {}).get('avfan_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
                remaining += 1
        return remaining

    def _enrich_single_prefix(self, page, prefix):
        parsed_entries = []
        self.scraper.open_listing_page(page, prefix, 1)
        total_pages = self.scraper.detect_total_pages(page)
        stopped_early = False
        self._log('INFO', '番号前缀详情页已打开', prefix=prefix, total_pages=total_pages)

        for page_number in range(1, total_pages + 1):
            if self.should_stop():
                stopped_early = True
                self._log('WARNING', '番号前缀分页抓取提前停止', prefix=prefix, page_number=page_number)
                break
            if page_number > 1:
                self.scraper.open_listing_page(page, prefix, page_number)
            page_rows = self.scraper.collect_page_entries(page)
            page_entries = self._parse_entries(prefix, page_rows, page_number)
            parsed_entries.extend(page_entries)
            self._log(
                'INFO',
                '番号前缀分页抓取完成',
                prefix=prefix,
                page_number=page_number,
                raw_row_count=len(page_rows),
                parsed_entry_count=len(page_entries),
                accumulated_entry_count=len(parsed_entries),
            )

        if stopped_early:
            return {
                'prefix': prefix,
                'status': FAILED_STATUS,
                'error': '用户已停止补全',
                'stopped': True,
            }

        unique_entries = self._dedupe_entries(parsed_entries)
        self._log(
            'INFO',
            '番号前缀结果去重完成',
            prefix=prefix,
            parsed_entry_count=len(parsed_entries),
            unique_entry_count=len(unique_entries),
        )
        if unique_entries:
            self.database.replace_code_prefix_movies(prefix, unique_entries)
            self.database.save_code_prefix_enrichment(
                prefix=prefix,
                status=ENRICHED_STATUS,
                total_pages=total_pages,
                total_videos=len(unique_entries),
                error='',
                source_key=AVFAN_VIDEO_SOURCE,
            )
            self._log(
                'INFO',
                '番号前缀补全成功并写库',
                prefix=prefix,
                total_pages=total_pages,
                video_count=len(unique_entries),
                status=ENRICHED_STATUS,
            )
            return {
                'prefix': prefix,
                'status': ENRICHED_STATUS,
                'total_pages': total_pages,
                'video_count': len(unique_entries),
            }

        self.database.replace_code_prefix_movies(prefix, [])
        self.database.save_code_prefix_enrichment(
            prefix=prefix,
            status=NO_SEARCH_RESULTS_STATUS,
            total_pages=total_pages,
            total_videos=0,
            error='未搜索到番号页面内容',
            source_key=AVFAN_VIDEO_SOURCE,
        )
        self._log(
            'WARNING',
            '番号前缀未抓到页面内容，已写入无搜索结果状态',
            prefix=prefix,
            total_pages=total_pages,
            status=NO_SEARCH_RESULTS_STATUS,
        )
        return {
            'prefix': prefix,
            'status': NO_SEARCH_RESULTS_STATUS,
            'total_pages': total_pages,
            'video_count': 0,
            'error': '未搜索到番号页面内容',
        }

    def _parse_entries(self, prefix, rows, page_number):
        prefix_upper = str(prefix or '').strip().upper()
        parsed = []
        for row in rows:
            card = parse_code_prefix_card(
                text=row.get('text', ''),
                href=row.get('href', ''),
                prefix=prefix_upper,
                page_number=page_number,
            )
            code = card.get('code', '')
            if not code:
                continue
            if extract_code_prefix(code) != prefix_upper:
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

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='code_prefix_enrichment', **fields)
