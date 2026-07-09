import re
from contextlib import contextmanager
from urllib.parse import quote

from app.core.runtime_config import get_scraper_browser_channel, get_scraper_locale
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


QUEEN_SEARCH_BASE_URL = 'https://a.1cili.click'
QUEEN_RECORD_PREFIX = '\u5957\u8def\u76f4\u64ad_'
TITLE_PATTERN = re.compile(r'\u5957\u8def\u76f4\u64ad_[^<>"\'\r\n\t ]+')
QUEEN_SEARCH_LOAD_TIMEOUT_MS = 120000
QUEEN_SEARCH_RELOAD_WAIT_MS = 20000


class QueenSearchScraper:
    def __init__(self, headless=False, locale=None):
        self.headless = bool(headless)
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self._playwright_manager = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @contextmanager
    def session(self):
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
        minimize_browser_window_if_needed(self._page, self.headless)
        return self._page

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

    def search(self, keyword, show_browser=True, page=None):
        normalized_keyword = str(keyword or '').strip()
        if not normalized_keyword:
            raise ValueError('\u7f3a\u5c11\u5173\u952e\u8bcd')
        target_url = self.build_search_url(normalized_keyword)
        if page is None:
            with self.session() as active_page:
                return self.search(normalized_keyword, show_browser=show_browser, page=active_page)
        if bool(show_browser) != (not self.headless):
            # Keep runtime behavior predictable for tests and callers.
            self.headless = not bool(show_browser)
        self._open_results_page(page, target_url)
        records = self.extract_candidate_titles_from_page(page)
        return {
            'source_url': target_url,
            'records': records,
        }

    def _open_results_page(self, page, target_url):
        has_loaded_target_once = False
        while True:
            try:
                if has_loaded_target_once:
                    page.reload(wait_until='domcontentloaded', timeout=QUEEN_SEARCH_LOAD_TIMEOUT_MS)
                else:
                    page.goto(target_url, wait_until='domcontentloaded', timeout=QUEEN_SEARCH_LOAD_TIMEOUT_MS)
                    has_loaded_target_once = True
                wait_for_page_ready(page)
            except Exception:
                page.wait_for_timeout(QUEEN_SEARCH_RELOAD_WAIT_MS)
                continue
            if self._is_results_page_ready(page):
                return
            page.wait_for_timeout(QUEEN_SEARCH_RELOAD_WAIT_MS)
            has_loaded_target_once = True

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
        return bool(cls.extract_candidate_titles(body_text=body_text, html=html))

    @staticmethod
    def build_search_url(keyword):
        return f'{QUEEN_SEARCH_BASE_URL}/search?q={quote(str(keyword or "").strip())}'

    @classmethod
    def extract_candidate_titles_from_page(cls, page):
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
