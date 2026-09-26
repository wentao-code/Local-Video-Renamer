import re
from contextlib import contextmanager
from urllib.parse import quote, urljoin, urlparse

from app.core.app_logging import get_logger
from app.core.operation_timeout_settings import get_operation_timeout_milliseconds
from app.core.runtime_config import get_scraper_browser_channel, get_scraper_locale
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


LOGGER = get_logger(__name__)
QUEEN_SEARCH_BASE_URL = 'https://y.9cili.click'
QUEEN_SEARCH_BACKUP_URL = 'https://a.1cili.click'
QUEEN_RECORD_PREFIX = '\u5957\u8def\u76f4\u64ad_'
TITLE_PATTERN = re.compile(r'\u5957\u8def\u76f4\u64ad_[^<>"\'\r\n\t ]+')
QUEEN_SEARCH_LOAD_TIMEOUT_MS = 120000
QUEEN_SEARCH_RELOAD_WAIT_MS = 200
QUEEN_SEARCH_MAX_ATTEMPTS = 3
QUEEN_SEARCH_MAX_PAGES_PER_SORT = 5
QUEEN_SEARCH_RESULTS_PER_PAGE = 50
QUEEN_SEARCH_RELEVANCE_THRESHOLD = 250


class QueenSearchTransientError(RuntimeError):
    pass


class QueenSearchScraper:
    def __init__(self, headless=False, locale=None, minimize_window=False):
        self.headless = bool(headless)
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self.minimize_window = bool(minimize_window)
        self._playwright_manager = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @contextmanager
    def session(self, show_browser=None):
        if show_browser is not None:
            self.configure_browser_visibility(show_browser)
        created_here = False
        if self._context is None or self._page is None:
            self.open_session()
            created_here = True
        try:
            yield self._page
        finally:
            if created_here:
                self.close_session()

    def open_session(self):
        if self._context is not None and self._page is not None:
            return self._page

        sync_playwright = import_sync_playwright()
        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        browser_channel = get_scraper_browser_channel()
        launch_options = {'headless': self.headless}
        if browser_channel:
            launch_options['channel'] = browser_channel
        try:
            self._browser = self._playwright.chromium.launch(**launch_options)
        except Exception:
            launch_options.pop('channel', None)
            self._browser = self._playwright.chromium.launch(**launch_options)
        self._context = self._browser.new_context(locale=self.locale, viewport={'width': 1440, 'height': 1200})
        self._page = self._context.new_page()
        if self.minimize_window:
            minimize_browser_window_if_needed(self._page, self.headless)
        return self._page

    def configure_browser_visibility(self, show_browser):
        desired_headless = not bool(show_browser)
        if self.headless == desired_headless:
            return
        if self._context is not None or self._browser is not None:
            self.close_session()
        self.headless = desired_headless

    def close_session(self):
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            try:
                if self._browser is not None:
                    self._browser.close()
            finally:
                self._browser = None
                try:
                    if self._playwright is not None:
                        self._playwright.stop()
                finally:
                    self._playwright = None
                    self._playwright_manager = None

    def search(self, keyword, show_browser=True, page=None, should_stop=None):
        normalized_keyword = str(keyword or '').strip()
        if not normalized_keyword:
            raise ValueError('\u7f3a\u5c11\u5173\u952e\u8bcd')
        if page is None:
            with self.session(show_browser=show_browser) as active_page:
                return self.search(
                    normalized_keyword,
                    show_browser=show_browser,
                    page=active_page,
                    should_stop=should_stop,
                )

        first_sort = ''
        first_url = self.build_search_url(
            normalized_keyword,
            sort=first_sort,
            page=1,
            base_url=QUEEN_SEARCH_BASE_URL,
        )
        selected_first_url = self._open_results_page(
            page,
            first_url,
            fallback_url=self.build_search_url(
                normalized_keyword,
                sort=first_sort,
                page=1,
                base_url=QUEEN_SEARCH_BACKUP_URL,
            ),
            should_stop=should_stop,
        )
        selected_url_parts = urlparse(selected_first_url)
        selected_base_url = (
            f'{selected_url_parts.scheme}://{selected_url_parts.netloc}'
            if selected_url_parts.scheme and selected_url_parts.netloc
            else QUEEN_SEARCH_BASE_URL
        )
        source_urls = [selected_first_url]
        records = self.extract_candidate_titles_from_page(page, base_url=selected_base_url)

        default_result_count = self._read_reported_result_count(page)
        if default_result_count is None:
            LOGGER.warning(
                '女王库搜索结果总数无法读取，按单页处理 keyword=%s sort=default',
                normalized_keyword,
            )
        default_total_pages = self._page_count_for_result_count(default_result_count)
        for page_number in range(2, default_total_pages + 1):
            target_url = self.build_search_url(
                normalized_keyword,
                sort='',
                page=page_number,
                base_url=selected_base_url,
            )
            self._open_results_page(page, target_url, should_stop=should_stop)
            source_urls.append(target_url)
            records.extend(
                self.extract_candidate_titles_from_page(page, base_url=selected_base_url)
            )

        if default_result_count is not None and default_result_count >= QUEEN_SEARCH_RELEVANCE_THRESHOLD:
            relevance_first_url = self.build_search_url(
                normalized_keyword,
                sort='relevance',
                page=1,
                base_url=selected_base_url,
            )
            relevance_url = self._open_results_page(
                page,
                relevance_first_url,
                should_stop=should_stop,
            )
            source_urls.append(relevance_url)
            records.extend(self.extract_candidate_titles_from_page(page, base_url=selected_base_url))
            relevance_result_count = self._read_reported_result_count(page)
            if relevance_result_count is None:
                LOGGER.warning(
                    '女王库相关度搜索结果总数无法读取，按单页处理 keyword=%s',
                    normalized_keyword,
                )
            relevance_total_pages = self._page_count_for_result_count(relevance_result_count)
            for page_number in range(2, relevance_total_pages + 1):
                target_url = self.build_search_url(
                    normalized_keyword,
                    sort='relevance',
                    page=page_number,
                    base_url=selected_base_url,
                )
                self._open_results_page(page, target_url, should_stop=should_stop)
                source_urls.append(target_url)
                records.extend(
                    self.extract_candidate_titles_from_page(page, base_url=selected_base_url)
                )

        records = self._dedupe_records(records)
        return {
            'source_url': source_urls[0],
            'source_urls': source_urls,
            'records': records,
        }

    @classmethod
    def _read_reported_result_count(cls, page):
        try:
            body_text = page.locator('body').inner_text(timeout=5000)
        except Exception:
            return None
        return cls._extract_reported_result_count(body_text)

    @staticmethod
    def _extract_reported_result_count(body_text):
        chinese_match = re.search(r'(?:\u7ea6\s*)?([\d,]+)\s*\u4e2a\u7ed3\u679c', body_text or '')
        if chinese_match:
            return int(chinese_match.group(1).replace(',', ''))
        english_match = re.search(
            r'(?:about\s+)?([\d,]+)\s+results?\b',
            body_text or '',
            re.IGNORECASE,
        )
        if english_match:
            return int(english_match.group(1).replace(',', ''))
        return None

    @staticmethod
    def _page_count_for_result_count(result_count):
        if result_count is None:
            return 1
        calculated_pages = max(
            1,
            (max(0, int(result_count)) + QUEEN_SEARCH_RESULTS_PER_PAGE - 1)
            // QUEEN_SEARCH_RESULTS_PER_PAGE,
        )
        return min(calculated_pages, QUEEN_SEARCH_MAX_PAGES_PER_SORT)

    def _open_results_page(self, page, target_url, fallback_url='', should_stop=None):
        active_url = str(target_url or '').strip()
        normalized_fallback_url = str(fallback_url or '').strip()
        fallback_attempted = False
        has_loaded_target_once = False
        last_error = None
        for attempt in range(1, QUEEN_SEARCH_MAX_ATTEMPTS + 1):
            self._raise_if_stop_requested(should_stop)
            try:
                load_timeout_ms = get_operation_timeout_milliseconds('queen_page_load')
                if has_loaded_target_once:
                    page.reload(wait_until='domcontentloaded', timeout=load_timeout_ms)
                else:
                    page.goto(active_url, wait_until='domcontentloaded', timeout=load_timeout_ms)
                    has_loaded_target_once = True
                if callable(should_stop):
                    wait_for_page_ready(page, should_stop)
                else:
                    wait_for_page_ready(page)
            except QueenSearchTransientError:
                raise
            except Exception as exc:
                last_error = exc
                self._raise_if_stop_requested(should_stop)
                if normalized_fallback_url and not fallback_attempted and not has_loaded_target_once:
                    active_url = normalized_fallback_url
                    fallback_attempted = True
                    has_loaded_target_once = False
                    continue
                if self._is_cloudflare_522_page(page):
                    raise QueenSearchTransientError('Cloudflare 522 Connection timed out')
                if attempt >= QUEEN_SEARCH_MAX_ATTEMPTS:
                    break
                self._wait_before_retry(page, should_stop)
                continue
            if self._is_cloudflare_522_page(page):
                if normalized_fallback_url and not fallback_attempted:
                    active_url = normalized_fallback_url
                    fallback_attempted = True
                    has_loaded_target_once = False
                    continue
                last_error = QueenSearchTransientError('Cloudflare 522 Connection timed out')
                if attempt >= QUEEN_SEARCH_MAX_ATTEMPTS:
                    break
                self._wait_before_retry(page, should_stop)
                continue
            if self._is_results_page_ready(page):
                return active_url
            if attempt >= QUEEN_SEARCH_MAX_ATTEMPTS:
                break
            self._wait_before_retry(page, should_stop)

        self._raise_if_stop_requested(should_stop)
        if isinstance(last_error, QueenSearchTransientError):
            raise last_error
        detail = f': {last_error}' if last_error else ''
        raise QueenSearchTransientError(
            f'女王库页面在 {QUEEN_SEARCH_MAX_ATTEMPTS} 次尝试后仍未准备完成{detail}'
        ) from last_error

    @staticmethod
    def _raise_if_stop_requested(should_stop):
        if callable(should_stop) and should_stop():
            raise QueenSearchTransientError('女王库抓取已请求停止')

    @classmethod
    def _wait_before_retry(cls, page, should_stop=None):
        cls._raise_if_stop_requested(should_stop)
        wait_ms = max(0, int(QUEEN_SEARCH_RELOAD_WAIT_MS))
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        cls._raise_if_stop_requested(should_stop)

    @staticmethod
    def _is_cloudflare_522_page(page):
        try:
            body_text = page.locator('body').inner_text(timeout=1000)
        except Exception:
            body_text = ''
        try:
            html = page.content()
        except Exception:
            html = ''
        normalized = f'{body_text}\n{html}'.lower()
        return (
            'cloudflare' in normalized
            and (
                'error code 522' in normalized
                or '522: connection timed out' in normalized
                or 'connection timed out' in normalized and 'host error' in normalized
            )
        )

    @classmethod
    def _is_results_page_ready(cls, page):
        rows = cls.extract_result_row_titles(page)
        if rows:
            return True
        body_text = ''
        try:
            body_text = page.locator('body').inner_text(timeout=5000)
        except Exception:
            body_text = ''
        html = ''
        try:
            html = page.content()
        except Exception:
            html = ''
        if cls._is_zero_results_page(body_text=body_text, html=html):
            return True
        return (
            cls._extract_reported_result_count(body_text) is not None
            or bool(cls.extract_candidate_titles(body_text=body_text, html=html))
        )

    @staticmethod
    def _is_zero_results_page(body_text='', html=''):
        normalized = f'{body_text}\n{html}'.lower()
        return bool(
            re.search(r'\b0\s+results?\b', normalized)
            or '0个相关资源' in normalized
            or 'no results' in normalized
        )

    @staticmethod
    def build_search_url(keyword, sort='', page=1, base_url=None):
        normalized_base_url = str(base_url or QUEEN_SEARCH_BASE_URL).rstrip('/')
        query_parts = [f'q={quote(str(keyword or "").strip())}']
        normalized_sort = str(sort or '').strip()
        if normalized_sort:
            query_parts.append(f'sort={quote(normalized_sort)}')
        normalized_page = max(1, int(page or 1))
        if normalized_page > 1:
            query_parts.append(f'page={normalized_page}')
        return f'{normalized_base_url}/search?{"&".join(query_parts)}'

    @classmethod
    def extract_candidate_titles_from_page(cls, page, base_url=None):
        structured_records = cls.extract_result_row_records(page, base_url=base_url)
        if structured_records:
            return structured_records

        records = cls.extract_candidate_titles_from_rows(cls.extract_result_row_titles(page))
        if records:
            return records

        body_text = ''
        try:
            body_text = page.locator('body').inner_text(timeout=5000)
        except Exception:
            body_text = ''
        html = ''
        try:
            html = page.content()
        except Exception:
            html = ''
        return cls.extract_candidate_titles(body_text=body_text, html=html)

    @classmethod
    def extract_result_row_records(cls, page, base_url=None):
        try:
            rows = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('table.file-list tbody tr')).map((row) => {
                    const link = row.querySelector('a');
                    if (!link) return null;
                    const title = Array.from(link.childNodes)
                        .filter((node) => !(node.nodeType === Node.ELEMENT_NODE && node.matches('p.sample')))
                        .map((node) => node.textContent || '')
                        .join('');
                    return {
                        title: title.replace(/\\s+/g, ' ').trim(),
                        href: link.getAttribute('href') || '',
                    };
                }).filter(Boolean)
                """
            )
        except Exception:
            return []

        seen = set()
        records = []
        for row in list(rows or []):
            payload = dict(row or {}) if isinstance(row, dict) else {}
            raw_title = ' '.join(str(payload.get('title', '') or '').split()).strip()
            if not raw_title:
                continue
            prefix_index = raw_title.find(QUEEN_RECORD_PREFIX)
            if prefix_index < 0:
                continue
            raw_title = raw_title[prefix_index:]
            if raw_title in seen:
                continue
            seen.add(raw_title)
            detail_url = str(payload.get('href', '') or '').strip()
            records.append({
                'raw_title': raw_title,
                'detail_url': urljoin(base_url or QUEEN_SEARCH_BASE_URL, detail_url) if detail_url else '',
            })
        return records

    @staticmethod
    def _dedupe_records(records):
        seen = set()
        deduped = []
        for record in list(records or []):
            if isinstance(record, dict):
                identity = record.get('raw_title', record.get('title', ''))
            else:
                identity = record
            normalized_identity = ' '.join(str(identity or '').split()).strip()
            if not normalized_identity or normalized_identity in seen:
                continue
            seen.add(normalized_identity)
            deduped.append(record)
        return deduped

    @classmethod
    def extract_result_row_titles(cls, page):
        try:
            rows = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('table.file-list tbody tr')).map((row) => {
                    const link = row.querySelector('a');
                    if (!link) return '';
                    const title = Array.from(link.childNodes)
                        .filter((node) => !(node.nodeType === Node.ELEMENT_NODE && node.matches('p.sample')))
                        .map((node) => node.textContent || '')
                        .join('');
                    return title.replace(/\\s+/g, ' ').trim();
                })
                """
            )
        except Exception:
            return []
        return [' '.join(str(row or '').split()).strip() for row in list(rows or []) if str(row or '').strip()]

    @classmethod
    def extract_candidate_titles_from_rows(cls, rows):
        seen = set()
        records = []
        for row in list(rows or []):
            normalized = ' '.join(str(row or '').split()).strip()
            if not normalized:
                continue
            prefix_index = normalized.find(QUEEN_RECORD_PREFIX)
            if prefix_index < 0:
                continue
            normalized = normalized[prefix_index:]
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            records.append(normalized)
        return records

    @classmethod
    def extract_candidate_titles(cls, body_text='', html=''):
        seen = set()
        records = []
        for source_text in (str(body_text or ''), str(html or '')):
            for match in TITLE_PATTERN.findall(source_text):
                normalized = str(match or '').strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                records.append(normalized)
        return records
