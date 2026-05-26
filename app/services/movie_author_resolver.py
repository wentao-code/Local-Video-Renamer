import re
from datetime import date, datetime

from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.scraper.javtxt_scraper import JavtxtScraper


JAVTXT_AUTHOR_MIN_RELEASE_DATE = date(2020, 1, 1)
TERMINAL_JAVTXT_VIDEO_STATUSES = {
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
}


class MovieAuthorResolver:
    def __init__(self, database, scraper=None, headless=True, should_stop=None, logger=None):
        self.database = database
        self.logger = logger
        self.scraper = scraper or JavtxtScraper(headless=headless, logger=logger)
        self.should_stop = should_stop or (lambda: False)
        self._author_cache = {}
        self._status_cache = {}

    def session(self):
        return self.scraper.session()

    def enrich_entries(self, entries, progress_callback=None):
        return self.enrich_entries_with_details(entries, progress_callback=progress_callback).get('entries', [])

    def enrich_entries_with_details(self, entries, max_lookup_count=None, progress_callback=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = self._load_cached_rows(normalized_entries)
        pending_video_count_before = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        requested_lookup_count = pending_video_count_before
        if max_lookup_count is not None:
            requested_lookup_count = min(
                pending_video_count_before,
                max(0, int(max_lookup_count or 0)),
            )
        self._log(
            'INFO',
            '作者解析任务准备完成',
            entry_count=len(normalized_entries),
            pending_video_count_before=pending_video_count_before,
            requested_lookup_count=requested_lookup_count,
            max_lookup_count=max_lookup_count if max_lookup_count is not None else '',
        )

        processed_video_count = 0
        success_video_count = 0
        failed_video_count = 0

        for entry in normalized_entries:
            if processed_video_count >= requested_lookup_count:
                self._log('INFO', '作者解析达到本轮上限', processed_video_count=processed_video_count)
                break
            if self.should_stop():
                self._log('WARNING', '作者解析收到停止请求', processed_video_count=processed_video_count)
                break

            code = self._normalize_code(entry.get('code', ''))
            if not code:
                self._log('WARNING', '条目缺少有效番号，跳过作者解析', raw_code=entry.get('code', ''))
                continue

            should_attempt, skip_reason = self._should_attempt_lookup(entry, cached_rows)
            if not should_attempt:
                self._log('INFO', '跳过作者解析', code=code, reason=skip_reason)
                continue

            resolution = self._resolve_author_result(code, cached_rows.get(code, {}))
            processed_video_count += 1

            author = normalize_second_source_actor_text(resolution.get('author', ''))
            status = resolution.get('status', UNENRICHED_STATUS)
            if author:
                entry['author'] = author
            if status == ENRICHED_STATUS:
                success_video_count += 1
            elif status == FAILED_STATUS:
                failed_video_count += 1

            self._log(
                'INFO',
                '作者解析完成',
                code=code,
                status=status,
                author=author,
                processed_video_count=processed_video_count,
                success_video_count=success_video_count,
                failed_video_count=failed_video_count,
            )

            if progress_callback is not None:
                progress_callback(
                    {
                        'code': code,
                        'author': author,
                        'status': status,
                        'processed_video_count': processed_video_count,
                        'success_video_count': success_video_count,
                        'failed_video_count': failed_video_count,
                    }
                )

            cached_rows[code] = {
                'code': code,
                'javtxt_actors': author,
                'javtxt_enrichment_status': status,
            }

        pending_video_count_after = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        self._log(
            'INFO',
            '作者解析任务结束',
            processed_video_count=processed_video_count,
            success_video_count=success_video_count,
            failed_video_count=failed_video_count,
            pending_video_count_after=pending_video_count_after,
        )
        return {
            'entries': normalized_entries,
            'processed_video_count': processed_video_count,
            'success_video_count': success_video_count,
            'failed_video_count': failed_video_count,
            'pending_video_count': pending_video_count_after,
            'requested_video_count': requested_lookup_count,
            'completed': pending_video_count_after <= 0,
        }

    def count_pending_entries(self, entries, cached_rows=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = cached_rows if cached_rows is not None else self._load_cached_rows(normalized_entries)
        pending_count = 0
        for entry in normalized_entries:
            should_attempt, _ = self._should_attempt_lookup(entry, cached_rows)
            if should_attempt:
                pending_count += 1
        return pending_count

    def _normalize_entry(self, entry):
        updated = dict(entry or {})
        updated['author'] = normalize_second_source_actor_text(updated.get('author', ''))
        return updated

    def _prepare_entries(self, entries):
        normalized_entries = [self._normalize_entry(entry) for entry in (entries or [])]
        normalized_entries.sort(key=self._lookup_order_key)
        return normalized_entries

    def _load_cached_rows(self, entries):
        eligible_codes = [
            self._normalize_code(entry.get('code', ''))
            for entry in entries
            if self._should_lookup_author(entry)
        ]
        cached_rows = self.database.get_javtxt_actor_cache_by_codes(eligible_codes)
        self._log(
            'INFO',
            '已加载作者缓存',
            eligible_code_count=len(eligible_codes),
            cached_row_count=len(cached_rows),
        )
        return cached_rows

    def _should_attempt_lookup(self, entry, cached_rows):
        if not self._should_lookup_author(entry):
            return False, 'not_eligible_for_javtxt_lookup'
        if self._has_author(entry):
            return False, 'author_already_present'

        code = self._normalize_code(entry.get('code', ''))
        if not code:
            return False, 'invalid_code'

        cached_row = cached_rows.get(code, {})
        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        if cached_author:
            entry['author'] = cached_author
            return False, 'cached_author_applied'

        cached_status = self._normalize_video_status((cached_row or {}).get('javtxt_enrichment_status', ''))
        if cached_status == UNENRICHED_STATUS:
            return True, 'unenriched'
        if self._is_retryable_empty_author_result(cached_row, cached_status):
            return True, 'retryable_empty_author_result'
        return False, f'cached_terminal_status:{cached_status}'

    @staticmethod
    def _has_author(entry):
        return bool(normalize_second_source_actor_text((entry or {}).get('author', '')))

    def _resolve_author_result(self, code, cached_row):
        if code in self._author_cache or code in self._status_cache:
            self._log(
                'INFO',
                '命中进程内作者缓存',
                code=code,
                status=self._status_cache.get(code, UNENRICHED_STATUS),
                author=self._author_cache.get(code, ''),
            )
            return {
                'author': self._author_cache.get(code, ''),
                'status': self._status_cache.get(code, UNENRICHED_STATUS),
            }

        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        cached_status = self._normalize_video_status((cached_row or {}).get('javtxt_enrichment_status', ''))
        if cached_author:
            self._author_cache[code] = cached_author
            self._status_cache[code] = ENRICHED_STATUS
            self._log('INFO', '命中数据库作者缓存', code=code, status=ENRICHED_STATUS, author=cached_author)
            return {
                'author': cached_author,
                'status': ENRICHED_STATUS,
            }
        if (
            cached_status in TERMINAL_JAVTXT_VIDEO_STATUSES
            and cached_status != UNENRICHED_STATUS
            and not self._is_retryable_empty_author_result(cached_row, cached_status)
        ):
            self._author_cache[code] = ''
            self._status_cache[code] = cached_status
            self._log('INFO', '命中数据库终态缓存，不再请求详情页', code=code, status=cached_status)
            return {
                'author': '',
                'status': cached_status,
            }

        author = ''
        status = UNENRICHED_STATUS
        error_message = ''
        info = {}
        try:
            self._log('INFO', '开始请求 JAVTXT 详情页', code=code)
            info = self.scraper.fetch_by_code(code)
            if info.get('found'):
                author = normalize_second_source_actor_text(info.get('author', ''))
                status = ENRICHED_STATUS if author else FAILED_STATUS
                if not author:
                    error_message = 'JAVTXT 未返回演员信息'
            else:
                status = NO_SEARCH_RESULTS_STATUS
                error_message = str(info.get('error', '') or 'JAVTXT 未找到匹配结果')
        except Exception as exc:
            status = FAILED_STATUS
            error_message = str(exc)

        self._author_cache[code] = author
        self._status_cache[code] = status
        self._save_video_cache(code, info, status=status, error=error_message)
        self._log(
            'INFO',
            'JAVTXT 请求结果已写入缓存',
            code=code,
            status=status,
            author=author,
            error=error_message,
        )
        return {
            'author': author,
            'status': status,
        }

    def _save_video_cache(self, code, info, status=ENRICHED_STATUS, error=''):
        if self.database is None or not hasattr(self.database, 'save_javtxt_cache_for_video'):
            self._log('WARNING', '数据库未提供 JAVTXT 缓存写入接口，跳过缓存落库', code=code)
            return
        try:
            self.database.save_javtxt_cache_for_video(
                code,
                info,
                status=status,
                error=error,
            )
        except Exception as exc:
            self._log('ERROR', '写入 JAVTXT 视频缓存失败', code=code, status=status, error=str(exc))
            return
        self._log('INFO', 'JAVTXT 视频缓存写入完成', code=code, status=status, error=error)

    @staticmethod
    def _is_retryable_empty_author_result(cached_row, cached_status):
        if cached_status not in (NO_SEARCH_RESULTS_STATUS, FAILED_STATUS):
            return False
        return bool(
            str((cached_row or {}).get('javtxt_movie_id', '') or '').strip()
            or str((cached_row or {}).get('javtxt_url', '') or '').strip()
        )

    def _should_lookup_author(self, entry):
        code = self._normalize_code((entry or {}).get('code', ''))
        if not code:
            return False
        release_date = self._parse_release_date((entry or {}).get('release_date', ''))
        if release_date is None:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE

    @staticmethod
    def _parse_release_date(value):
        text = str(value or '').strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, '%Y-%m-%d').date()
        except ValueError:
            return None

    @staticmethod
    def _normalize_code(value):
        return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

    @staticmethod
    def _normalize_video_status(value):
        text = str(value or '').strip()
        return text or UNENRICHED_STATUS

    def _lookup_order_key(self, entry):
        normalized_code = self._normalize_code((entry or {}).get('code', ''))
        prefix_part = re.match(r'[A-Z]+', normalized_code or '')
        number_match = re.search(r'(\d+)', normalized_code or '')
        prefix_text = prefix_part.group(0) if prefix_part else normalized_code
        number_value = int(number_match.group(1)) if number_match else 10 ** 12
        return (prefix_text, number_value, normalized_code)

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='movie_author_resolver', **fields)
