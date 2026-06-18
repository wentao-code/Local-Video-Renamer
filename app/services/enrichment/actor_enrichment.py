from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET
from app.scraper.avfan_actor_scraper import AvfanActorScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.services.enrichment import start_progress_tracker
from app.services.parsers import parse_actor_search_card


class ActorEnrichmentService:
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
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
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
        self._log(
            'INFO',
            '演员库补全任务启动',
            source_key=AVFAN_VIDEO_SOURCE,
            requested_limit=limit,
            candidate_count=len(candidates),
            candidate_names=' | '.join(candidates[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '演员库',
                len(candidates),
                source_label=source_label,
                count_unit='演员',
                target_type=ACTOR_LIBRARY_TARGET,
                source_key=AVFAN_VIDEO_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        for actor_name in candidates:
            if self.should_stop():
                stopped = True
                self._log('WARNING', '演员库补全收到停止请求', processed_count=len(results))
                break

            self._log('INFO', '开始处理演员', actor_name=actor_name)
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
                results.append({'actor_name': actor_name, 'status': FAILED_STATUS, 'error': error_message})
                failed_count += 1
                self._log(
                    'ERROR',
                    '演员库补全被人机验证中断',
                    actor_name=actor_name,
                    error=error_message,
                )
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
                results.append({'actor_name': actor_name, 'status': FAILED_STATUS, 'error': error_message})
                failed_count += 1
                self._log(
                    'ERROR',
                    '演员库补全异常，已写入失败状态',
                    actor_name=actor_name,
                    error=error_message,
                )

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
        self._log(
            'INFO',
            '演员库补全任务结束',
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
            '演员库补全进度更新',
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
        self._log(
            'INFO',
            '已筛选演员库候选演员',
            candidate_count=len(actors),
            candidate_names=' | '.join(actors[:20]),
        )
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
        self._log('INFO', '演员详情页已打开', actor_name=actor_name, actor_id=actor_id, total_pages=total_pages)

        for page_number in range(1, total_pages + 1):
            if self.should_stop():
                stopped_early = True
                self._log('WARNING', '演员分页抓取提前停止', actor_name=actor_name, page_number=page_number)
                break
            if page_number > 1:
                self.scraper.open_listing_page(page, actor_name, page_number)
            page_rows = self.scraper.collect_page_entries(page)
            page_entries = self._parse_entries(actor_name, page_rows, page_number)
            parsed_entries.extend(page_entries)
            self._log(
                'INFO',
                '演员分页抓取完成',
                actor_name=actor_name,
                page_number=page_number,
                raw_row_count=len(page_rows),
                parsed_entry_count=len(page_entries),
                accumulated_entry_count=len(parsed_entries),
            )

        if stopped_early:
            return {
                'actor_name': actor_name,
                'status': FAILED_STATUS,
                'error': '用户已停止补全',
                'stopped': True,
            }

        unique_entries = self._dedupe_entries(parsed_entries)
        self._log(
            'INFO',
            '演员作品结果去重完成',
            actor_name=actor_name,
            parsed_entry_count=len(parsed_entries),
            unique_entry_count=len(unique_entries),
        )
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
            self._log(
                'INFO',
                '演员补全成功并写库',
                actor_name=actor_name,
                actor_id=actor_id,
                total_pages=total_pages,
                video_count=len(unique_entries),
                status=ENRICHED_STATUS,
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
        self._log(
            'WARNING',
            '演员未抓到页面内容，已写入无搜索结果状态',
            actor_name=actor_name,
            actor_id=actor_id,
            total_pages=total_pages,
            status=NO_SEARCH_RESULTS_STATUS,
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

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='actor_enrichment', **fields)
