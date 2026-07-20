from urllib.parse import quote

from app.core.enrichment_sources import SUPPLEMENT_TASK_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, CODE_PREFIX_LIBRARY_TARGET, VIDEO_LIBRARY_TARGET
from app.core.runtime_config import get_avfan_base_url
from app.core.supplement_task_state import SUPPLEMENT_MODE_ACTORS_ONLY, build_supplement_candidate
from app.scraper.avfan_scraper import AvfanScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.services.enrichment import start_progress_tracker
from app.services.library import CodePrefixLibrary


def _normalize_actor_payload(info):
    actors = info.get('actors') or []
    if not actors:
        actors = [info.get('author', '')]
    cleaned = [str(item or '').strip() for item in actors if str(item or '').strip()]
    actor_text = ' '.join(cleaned).strip()
    return actor_text, actor_text


def _merge_video_supplement_row(current_row, info):
    merged = dict(current_row or {})
    actor_text, actor_raw = _normalize_actor_payload(info)
    if current_row.get('supplement_mode') == SUPPLEMENT_MODE_ACTORS_ONLY:
        merged['author'] = actor_text
        merged['author_raw'] = actor_raw
        return merged
    merged['title'] = str(info.get('title', '') or '').strip() or merged.get('title', '')
    merged['author'] = actor_text
    merged['author_raw'] = actor_raw
    merged['release_date'] = str(info.get('release_date', '') or '').strip() or merged.get('release_date', '')
    merged['maker'] = ' '.join(str(item or '').strip() for item in info.get('maker', []) if str(item or '').strip())
    merged['publisher'] = ' '.join(
        str(item or '').strip() for item in info.get('publisher', []) if str(item or '').strip()
    )
    merged['avfan_movie_id'] = str(info.get('avfan_movie_id', '') or '').strip()
    return merged


def _merge_web_movie_supplement_row(current_row, info):
    merged = dict(current_row or {})
    actor_text, actor_raw = _normalize_actor_payload(info)
    if build_supplement_candidate(current_row).get('supplement_mode') == SUPPLEMENT_MODE_ACTORS_ONLY:
        merged['author'] = actor_text
        merged['author_raw'] = actor_raw
        return merged
    merged['title'] = str(info.get('title', '') or '').strip() or merged.get('title', '')
    merged['author'] = actor_text
    merged['author_raw'] = actor_raw
    merged['release_date'] = str(info.get('release_date', '') or '').strip() or merged.get('release_date', '')
    merged['avfan_url'] = str(info.get('avfan_url', '') or '').strip() or merged.get('avfan_url', '')
    return merged


class _SupplementBaseService:
    entity_label = ''
    target_type = ''
    count_unit = ''
    stop_message = ''
    finish_message = ''

    def __init__(
        self,
        database,
        scraper=None,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
        filter_settings=None,
        planned_items=None,
    ):
        self.database = database
        self.scraper = scraper or AvfanScraper(headless=not show_browser)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.filter_settings = filter_settings
        self.planned_items = [dict(item or {}) for item in (planned_items or [])]
        planned_plan_ids = {
            str((item or {}).get('plan_id', '') or '').strip()
            for item in self.planned_items
            if str((item or {}).get('plan_id', '') or '').strip()
        }
        self.running_plan_id = next(iter(planned_plan_ids), '') if len(planned_plan_ids) == 1 else ''

    @staticmethod
    def _unique_planned_values(planned_items, key_name):
        values = []
        seen = set()
        for item in planned_items or []:
            value = str((item or {}).get(key_name, '') or '').strip()
            if not value or value in seen:
                continue
            values.append(value)
            seen.add(value)
        return values

    def _planned_codes(self):
        return self._unique_planned_values(self.planned_items, 'code')

    def _planned_prefixes(self):
        return self._unique_planned_values(self.planned_items, 'prefix')

    def _planned_actor_names(self):
        return self._unique_planned_values(self.planned_items, 'actor_name')

    def _select_planned_rows(self, rows, key_name, limit):
        planned_values = self._unique_planned_values(self.planned_items, key_name)
        if not planned_values:
            return list(rows or [])[: max(0, int(limit or 0))]
        by_value = {}
        for row in rows or []:
            value = str((row or {}).get(key_name, '') or '').strip()
            if value and value not in by_value:
                by_value[value] = dict(row or {})
        selected = []
        for value in planned_values:
            if value in by_value:
                selected.append(by_value[value])
            if len(selected) >= int(limit or 0):
                break
        return selected

    def _start_progress(self, total_count):
        if self.progress_tracker is None:
            return
        start_progress_tracker(
            self.progress_tracker,
            self.entity_label,
            total_count,
            source_label=get_video_enrichment_source_label(SUPPLEMENT_TASK_SOURCE),
            count_unit=self.count_unit,
            target_type=self.target_type,
            source_key=SUPPLEMENT_TASK_SOURCE,
            log_path=str(getattr(self.logger, 'log_path', '') or ''),
            task_kind='single',
        )

    def _update_progress(self, processed_count, success_count, failed_count, current_item):
        if self.progress_tracker is None:
            return
        self.progress_tracker.update(
            processed_count=processed_count,
            success_count=success_count,
            failed_count=failed_count,
            current_item=current_item,
        )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is None:
            return
        self.progress_tracker.finish(message=message, stopped=stopped)

    def _resolve_remaining_state(self, estimate_remaining, exact_count_loader, has_more_loader):
        if estimate_remaining:
            has_more_pending = bool(has_more_loader())
            return (1 if has_more_pending else 0), has_more_pending
        remaining_count = max(0, int(exact_count_loader() or 0))
        return remaining_count, remaining_count > 0

    def _fetch_movie_info(self, row):
        current_row = dict(row or {})
        avfan_url = str(current_row.get('avfan_url', '') or '').strip()
        if avfan_url and hasattr(self.scraper, 'fetch_by_url'):
            return self.scraper.fetch_by_url(avfan_url)

        avfan_movie_id = str(current_row.get('avfan_movie_id', '') or '').strip()
        if avfan_movie_id and hasattr(self.scraper, 'fetch_by_url'):
            movie_url = f"{get_avfan_base_url()}/movies/{quote(avfan_movie_id)}"
            return self.scraper.fetch_by_url(movie_url)

        return self.scraper.fetch_by_code(current_row.get('code', ''))

    def _resolve_incomplete_error(self, row):
        mode = build_supplement_candidate(row).get('supplement_mode')
        if mode == SUPPLEMENT_MODE_ACTORS_ONLY:
            return 'AVFan 未返回可补全的演员信息'
        return 'AVFan 未返回完整补全信息'

    def _save_terminal_status(self, row, status, error=''):
        current_row = dict(row or {})
        if current_row.get('actor_name'):
            return self.database.save_actor_movie_supplement_status(
                current_row.get('actor_name', ''),
                current_row.get('code', ''),
                status,
                error=error,
            )
        if current_row.get('prefix'):
            return self.database.save_code_prefix_movie_supplement_status(
                current_row.get('prefix', ''),
                current_row.get('code', ''),
                status,
                error=error,
            )
        return self.database.save_video_supplement_status(
            current_row.get('code', ''),
            status,
            error=error,
        )

    def _result(
        self,
        limit,
        results,
        success_count,
        failed_count,
        remaining_count,
        *,
        processed_count=None,
        stopped=False,
        message='',
        requires_manual_verification=False,
    ):
        processed_count = len(results) if processed_count is None else max(0, int(processed_count or 0))
        return {
            'requested': limit,
            'processed_count': processed_count,
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': remaining_count,
            'has_more_pending': max(0, int(remaining_count or 0)) > 0,
            'results': results,
            'stopped': stopped,
            'requires_manual_verification': requires_manual_verification,
            'message': message,
            'entity_label': self.entity_label,
            'count_unit': self.count_unit,
            'source_key': SUPPLEMENT_TASK_SOURCE,
            'source_label': get_video_enrichment_source_label(SUPPLEMENT_TASK_SOURCE),
            'remaining_label': f'剩余待补全{self.count_unit}',
        }

    @staticmethod
    def _build_group_status(status_key, *, ok_when_clean):
        if ok_when_clean:
            return {status_key: 'ok'}
        return {status_key: 'failed'}

    def _persist_batch_updates(self, updated_rows, successful_rows, terminal_rows, bulk_updater):
        successful_keys = {self._supplement_row_identity(row) for row in successful_rows or []}
        terminal_by_key = {
            self._supplement_row_identity(row): (status, error_message)
            for row, status, error_message in terminal_rows or []
        }
        persisted_rows = []
        persisted_keys = set()
        for row in updated_rows or []:
            current = dict(row or {})
            key = self._supplement_row_identity(current)
            status, error_message = terminal_by_key.get(key, (ENRICHED_STATUS if key in successful_keys else UNENRICHED_STATUS, ''))
            current['_supplement_status'] = status
            current['_supplement_error'] = error_message
            persisted_rows.append(current)
            persisted_keys.add(key)
        status_only_rows = [
            (row, status, error_message)
            for row, status, error_message in terminal_rows or []
            if self._supplement_row_identity(row) not in persisted_keys
        ]
        if persisted_rows or status_only_rows:
            bulk_updater(persisted_rows, status_updates=status_only_rows)

    @staticmethod
    def _supplement_row_identity(row):
        current = dict(row or {})
        return (
            str(current.get('actor_name', '') or '').strip(),
            str(current.get('prefix', '') or '').strip().upper(),
            str(current.get('code', '') or '').strip().upper(),
        )


class VideoSupplementEnrichmentService(_SupplementBaseService):
    entity_label = '视频'
    target_type = VIDEO_LIBRARY_TARGET
    count_unit = '视频'
    stop_message = '视频补充任务已停止'
    finish_message = '视频补充任务已完成'

    def enrich_next_videos(self, limit, estimate_remaining=False):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')
        if self.planned_items:
            candidates = [dict(item) for item in self.planned_items if str(item.get('code', '') or '').strip()][:limit]
        else:
            candidates = self.database.list_video_supplement_candidates(limit)
        results = []
        success_count = 0
        failed_count = 0
        batch_updated_rows = []
        batch_successful_rows = []
        batch_terminal_rows = []
        if self.planned_items:
            remaining_loader = lambda: max(0, len(self.planned_items) - len(results))
            has_more_loader = lambda: bool(max(0, len(self.planned_items) - len(results)))
        else:
            remaining_loader = lambda: self.database.count_pending_video_supplements()
            has_more_loader = lambda: bool(self.database.list_video_supplement_candidates(1))
        self._start_progress(len(candidates))
        with self.scraper.session():
            for row in candidates:
                if self.should_stop():
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_processed_videos_for_supplement,
                    )
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        remaining_loader,
                        has_more_loader,
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        stopped=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(self.stop_message, stopped=True)
                    return result
                code = row.get('code', '')
                try:
                    info = self._fetch_movie_info(row)
                    if not info.get('found'):
                        batch_terminal_rows.append((row, NO_SEARCH_RESULTS_STATUS, info.get('error', '')))
                        failed_count += 1
                        results.append({'code': code, 'status': 'failed', 'error': info.get('error', '')})
                    else:
                        merged_row = _merge_video_supplement_row(row, info)
                        batch_updated_rows.append(merged_row)
                        if build_supplement_candidate(merged_row):
                            error_message = self._resolve_incomplete_error(merged_row)
                            batch_terminal_rows.append((merged_row, NO_SEARCH_RESULTS_STATUS, error_message))
                            failed_count += 1
                            results.append({'code': code, 'status': 'failed', 'error': error_message})
                        else:
                            batch_successful_rows.append(merged_row)
                            success_count += 1
                            results.append({'code': code, 'status': 'ok'})
                except HumanVerificationRequiredError as exc:
                    batch_terminal_rows.append((row, FAILED_STATUS, str(exc)))
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_processed_videos_for_supplement,
                    )
                    failed_count += 1
                    results.append({'code': code, 'status': 'failed', 'error': str(exc)})
                    self._update_progress(len(results), success_count, failed_count, code)
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        remaining_loader,
                        has_more_loader,
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        stopped=True,
                        message=str(exc),
                        requires_manual_verification=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(str(exc), stopped=True)
                    return result
                except Exception as exc:
                    batch_terminal_rows.append((row, FAILED_STATUS, str(exc)))
                    failed_count += 1
                    results.append({'code': code, 'status': 'failed', 'error': str(exc)})
                self._update_progress(len(results), success_count, failed_count, code)
        self._persist_batch_updates(
            batch_updated_rows,
            batch_successful_rows,
            batch_terminal_rows,
            self.database.bulk_update_processed_videos_for_supplement,
        )
        remaining_count, has_more_pending = self._resolve_remaining_state(
            estimate_remaining,
            remaining_loader,
            has_more_loader,
        )
        result = self._result(
            limit,
            results,
            success_count,
            failed_count,
            remaining_count,
        )
        result['has_more_pending'] = has_more_pending
        self._finish_progress(self.finish_message)
        return result


class CodePrefixSupplementEnrichmentService(_SupplementBaseService):
    entity_label = '番号'
    target_type = CODE_PREFIX_LIBRARY_TARGET
    count_unit = '视频'
    stop_message = '番号补充任务已停止'
    finish_message = '番号补充任务已完成'

    def __init__(
        self,
        database,
        scraper=None,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
        filter_settings=None,
        planned_items=None,
    ):
        super().__init__(
            database,
            scraper=scraper,
            show_browser=show_browser,
            should_stop=should_stop,
            progress_tracker=progress_tracker,
            logger=logger,
            filter_settings=filter_settings,
            planned_items=planned_items,
        )
        self.prefix_library = CodePrefixLibrary(database)

    def enrich_next_prefixes(self, limit, estimate_remaining=False):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')
        candidates = self._candidate_prefix_batches(limit)
        results = []
        processed_count = 0
        success_count = 0
        failed_count = 0
        batch_updated_rows = []
        batch_successful_rows = []
        batch_terminal_rows = []
        self._start_progress(sum(len(rows) for _, rows in candidates))
        with self.scraper.session():
            for prefix, rows in candidates:
                updated_rows = []
                successful_rows = []
                terminal_rows = []
                stop_requested = False
                try:
                    for row in rows:
                        if self.should_stop():
                            stop_requested = True
                            break
                        code = row.get('code', '')
                        info = self._fetch_movie_info(row)
                        processed_count += 1
                        if info.get('found'):
                            merged_row = _merge_web_movie_supplement_row(row, info)
                            updated_rows.append(merged_row)
                            if build_supplement_candidate(merged_row):
                                error_message = self._resolve_incomplete_error(merged_row)
                                terminal_rows.append((merged_row, NO_SEARCH_RESULTS_STATUS, error_message))
                                failed_count += 1
                            else:
                                successful_rows.append(merged_row)
                                success_count += 1
                        else:
                            terminal_rows.append((row, NO_SEARCH_RESULTS_STATUS, info.get('error', '')))
                            failed_count += 1
                        self._update_progress(processed_count, success_count, failed_count, code)
                except HumanVerificationRequiredError as exc:
                    batch_updated_rows.extend(updated_rows)
                    batch_successful_rows.extend(successful_rows)
                    batch_terminal_rows.extend(terminal_rows)
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_code_prefix_movies_for_supplement,
                    )
                    failed_count += 1
                    results.append({'prefix': prefix, 'status': 'failed', 'error': str(exc)})
                    self._update_progress(processed_count, success_count, failed_count, prefix)
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        self._remaining_video_count,
                        lambda: self._candidate_prefix_batches(1),
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        processed_count=processed_count,
                        stopped=True,
                        message=str(exc),
                        requires_manual_verification=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(str(exc), stopped=True)
                    return result
                except Exception as exc:
                    batch_updated_rows.extend(updated_rows)
                    batch_successful_rows.extend(successful_rows)
                    batch_terminal_rows.extend(terminal_rows)
                    if 'row' in locals():
                        batch_terminal_rows.append((row, FAILED_STATUS, str(exc)))
                    failed_count += 1
                    results.append({'prefix': prefix, 'status': 'failed', 'error': str(exc)})
                    self._update_progress(processed_count, success_count, failed_count, prefix)
                    continue

                batch_updated_rows.extend(updated_rows)
                batch_successful_rows.extend(successful_rows)
                batch_terminal_rows.extend(terminal_rows)
                if updated_rows and not terminal_rows:
                    results.append({'prefix': prefix, 'status': 'ok'})
                elif updated_rows or terminal_rows:
                    results.append({'prefix': prefix, 'status': 'failed'})

                if stop_requested:
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_code_prefix_movies_for_supplement,
                    )
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        self._remaining_video_count,
                        lambda: self._candidate_prefix_batches(1),
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        processed_count=processed_count,
                        stopped=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(self.stop_message, stopped=True)
                    return result

        self._persist_batch_updates(
            batch_updated_rows,
            batch_successful_rows,
            batch_terminal_rows,
            self.database.bulk_update_code_prefix_movies_for_supplement,
        )
        remaining_count, has_more_pending = self._resolve_remaining_state(
            estimate_remaining,
            self._remaining_video_count,
            lambda: self._candidate_prefix_batches(1),
        )
        result = self._result(
            limit,
            results,
            success_count,
            failed_count,
            remaining_count,
            processed_count=processed_count,
        )
        result['has_more_pending'] = has_more_pending
        self._finish_progress(self.finish_message)
        return result

    def _candidate_rows_for_prefix(self, prefix):
        sql_candidate_getter = getattr(self.database, 'list_sql_supplement_candidates', None)
        if callable(sql_candidate_getter):
            normalized_prefix = str(prefix or '').strip().upper()
            return [
                {
                    **dict(movie or {}),
                    **build_supplement_candidate(movie, filter_settings=self.filter_settings),
                }
                for movie in sql_candidate_getter(
                    'code_prefix',
                    1000000,
                    include_queued=bool(self.planned_items),
                    running_plan_id=self.running_plan_id,
                )
                if str((movie or {}).get('prefix', '') or '').strip().upper() == normalized_prefix
                and build_supplement_candidate(movie, filter_settings=self.filter_settings)
            ]
        return [
            dict(movie or {})
            for movie in self.database.list_code_prefix_movies(prefix)
            if build_supplement_candidate(movie, filter_settings=self.filter_settings)
        ]

    def _candidate_prefix_batches(self, limit):
        if self.planned_items:
            return self._planned_prefix_batches(limit)
        batches = []
        remaining_limit = max(0, int(limit or 0))
        for row in self.prefix_library.list_prefixes():
            if remaining_limit <= 0:
                break
            prefix = str(row.get('prefix', '') or '').strip().upper()
            if not prefix:
                continue
            candidate_rows = self._candidate_rows_for_prefix(prefix)
            if not candidate_rows:
                continue
            selected_rows = candidate_rows[:remaining_limit]
            batches.append((prefix, selected_rows))
            remaining_limit -= len(selected_rows)
        return batches

    def _planned_prefix_batches(self, limit):
        batches = []
        remaining_limit = max(0, int(limit or 0))
        used_codes = set()
        for item in self.planned_items:
            if remaining_limit <= 0:
                break
            prefix = str((item or {}).get('prefix', '') or '').strip().upper()
            code = str((item or {}).get('code', '') or '').strip()
            if not prefix:
                continue
            selected_row = dict(item)
            row_code = str(selected_row.get('code', '') or '').strip()
            if code and row_code != code:
                continue
            if row_code and row_code in used_codes:
                continue
            if not selected_row:
                continue
            selected_code = str((selected_row or {}).get('code', '') or '').strip()
            if selected_code:
                used_codes.add(selected_code)
            if batches and batches[-1][0] == prefix:
                batches[-1][1].append(selected_row)
            else:
                batches.append((prefix, [selected_row]))
            remaining_limit -= 1
        return batches

    def _remaining_video_count(self):
        sql_candidate_getter = getattr(self.database, 'list_sql_supplement_candidates', None)
        if callable(sql_candidate_getter):
            return sum(
                1
                for movie in sql_candidate_getter('code_prefix', 1000000)
                if build_supplement_candidate(movie, filter_settings=self.filter_settings)
            )
        return sum(
            1
            for movie in (self.database.list_all_code_prefix_movies() or [])
            if build_supplement_candidate(movie, filter_settings=self.filter_settings)
        )


class ActorSupplementEnrichmentService(_SupplementBaseService):
    entity_label = '演员'
    target_type = ACTOR_LIBRARY_TARGET
    count_unit = '视频'
    stop_message = '演员补充任务已停止'
    finish_message = '演员补充任务已完成'

    def enrich_next_actors(self, limit, estimate_remaining=False):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')
        candidates = self._candidate_actor_batches(limit)
        results = []
        processed_count = 0
        success_count = 0
        failed_count = 0
        batch_updated_rows = []
        batch_successful_rows = []
        batch_terminal_rows = []
        self._start_progress(sum(len(rows) for _, rows in candidates))
        with self.scraper.session():
            for actor_name, rows in candidates:
                updated_rows = []
                successful_rows = []
                terminal_rows = []
                stop_requested = False
                try:
                    for row in rows:
                        if self.should_stop():
                            stop_requested = True
                            break
                        code = row.get('code', '')
                        info = self._fetch_movie_info(row)
                        processed_count += 1
                        if info.get('found'):
                            merged_row = _merge_web_movie_supplement_row(row, info)
                            updated_rows.append(merged_row)
                            if build_supplement_candidate(merged_row):
                                error_message = self._resolve_incomplete_error(merged_row)
                                terminal_rows.append((merged_row, NO_SEARCH_RESULTS_STATUS, error_message))
                                failed_count += 1
                            else:
                                successful_rows.append(merged_row)
                                success_count += 1
                        else:
                            terminal_rows.append((row, NO_SEARCH_RESULTS_STATUS, info.get('error', '')))
                            failed_count += 1
                        self._update_progress(processed_count, success_count, failed_count, code)
                except HumanVerificationRequiredError as exc:
                    batch_updated_rows.extend(updated_rows)
                    batch_successful_rows.extend(successful_rows)
                    batch_terminal_rows.extend(terminal_rows)
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_actor_movies_for_supplement,
                    )
                    failed_count += 1
                    results.append({'actor_name': actor_name, 'status': 'failed', 'error': str(exc)})
                    self._update_progress(processed_count, success_count, failed_count, actor_name)
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        self._remaining_video_count,
                        lambda: self._candidate_actor_batches(1),
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        processed_count=processed_count,
                        stopped=True,
                        message=str(exc),
                        requires_manual_verification=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(str(exc), stopped=True)
                    return result
                except Exception as exc:
                    batch_updated_rows.extend(updated_rows)
                    batch_successful_rows.extend(successful_rows)
                    batch_terminal_rows.extend(terminal_rows)
                    if 'row' in locals():
                        batch_terminal_rows.append((row, FAILED_STATUS, str(exc)))
                    failed_count += 1
                    results.append({'actor_name': actor_name, 'status': 'failed', 'error': str(exc)})
                    self._update_progress(processed_count, success_count, failed_count, actor_name)
                    continue

                batch_updated_rows.extend(updated_rows)
                batch_successful_rows.extend(successful_rows)
                batch_terminal_rows.extend(terminal_rows)
                if updated_rows and not terminal_rows:
                    results.append({'actor_name': actor_name, 'status': 'ok'})
                elif updated_rows or terminal_rows:
                    results.append({'actor_name': actor_name, 'status': 'failed'})

                if stop_requested:
                    self._persist_batch_updates(
                        batch_updated_rows,
                        batch_successful_rows,
                        batch_terminal_rows,
                        self.database.bulk_update_actor_movies_for_supplement,
                    )
                    remaining_count, has_more_pending = self._resolve_remaining_state(
                        estimate_remaining,
                        self._remaining_video_count,
                        lambda: self._candidate_actor_batches(1),
                    )
                    result = self._result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        remaining_count,
                        processed_count=processed_count,
                        stopped=True,
                    )
                    result['has_more_pending'] = has_more_pending
                    self._finish_progress(self.stop_message, stopped=True)
                    return result

        self._persist_batch_updates(
            batch_updated_rows,
            batch_successful_rows,
            batch_terminal_rows,
            self.database.bulk_update_actor_movies_for_supplement,
        )
        remaining_count, has_more_pending = self._resolve_remaining_state(
            estimate_remaining,
            self._remaining_video_count,
            lambda: self._candidate_actor_batches(1),
        )
        result = self._result(
            limit,
            results,
            success_count,
            failed_count,
            remaining_count,
            processed_count=processed_count,
        )
        result['has_more_pending'] = has_more_pending
        self._finish_progress(self.finish_message)
        return result

    def _candidate_rows_for_actor(self, actor_name):
        sql_candidate_getter = getattr(self.database, 'list_sql_supplement_candidates', None)
        if callable(sql_candidate_getter):
            normalized_name = str(actor_name or '').strip()
            return [
                {
                    **dict(movie or {}),
                    **build_supplement_candidate(movie, filter_settings=self.filter_settings),
                }
                for movie in sql_candidate_getter(
                    'actor',
                    1000000,
                    include_queued=bool(self.planned_items),
                    running_plan_id=self.running_plan_id,
                )
                if str((movie or {}).get('actor_name', '') or '').strip() == normalized_name
                and build_supplement_candidate(movie, filter_settings=self.filter_settings)
            ]
        return [
            dict(movie or {})
            for movie in self.database.list_actor_movies(actor_name)
            if build_supplement_candidate(movie, filter_settings=self.filter_settings)
        ]

    def _candidate_actor_batches(self, limit):
        if self.planned_items:
            return self._planned_actor_batches(limit)
        batches = []
        remaining_limit = max(0, int(limit or 0))
        for row in self.database.list_actors():
            if remaining_limit <= 0:
                break
            actor_name = str(row.get('name', '') or '').strip()
            if not actor_name:
                continue
            candidate_rows = self._candidate_rows_for_actor(actor_name)
            if not candidate_rows:
                continue
            selected_rows = candidate_rows[:remaining_limit]
            batches.append((actor_name, selected_rows))
            remaining_limit -= len(selected_rows)
        return batches

    def _planned_actor_batches(self, limit):
        batches = []
        remaining_limit = max(0, int(limit or 0))
        used_codes = set()
        for item in self.planned_items:
            if remaining_limit <= 0:
                break
            actor_name = str((item or {}).get('actor_name', '') or '').strip()
            code = str((item or {}).get('code', '') or '').strip()
            if not actor_name:
                continue
            selected_row = dict(item)
            row_code = str(selected_row.get('code', '') or '').strip()
            if code and row_code != code:
                continue
            if row_code and row_code in used_codes:
                continue
            if not selected_row:
                continue
            selected_code = str((selected_row or {}).get('code', '') or '').strip()
            if selected_code:
                used_codes.add(selected_code)
            if batches and batches[-1][0] == actor_name:
                batches[-1][1].append(selected_row)
            else:
                batches.append((actor_name, [selected_row]))
            remaining_limit -= 1
        return batches

    def _remaining_video_count(self):
        sql_candidate_getter = getattr(self.database, 'list_sql_supplement_candidates', None)
        if callable(sql_candidate_getter):
            return sum(
                1
                for movie in sql_candidate_getter('actor', 1000000)
                if build_supplement_candidate(movie, filter_settings=self.filter_settings)
            )
        return sum(
            1
            for movie in (self.database.list_all_actor_movies() or [])
            if build_supplement_candidate(movie, filter_settings=self.filter_settings)
        )
