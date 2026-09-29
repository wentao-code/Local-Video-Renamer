from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app.core.runtime_config import get_scraper_locale
from app.queen_library.standard_reference_browser import (
    STANDARD_REFERENCE_PROFILE_DIR,
    STANDARD_REFERENCE_URL,
)
from app.scraper.avfan_scraper import import_sync_playwright
from app.queen_library.standard_reference_library import parse_forum_thread_title


def build_forum_page_url(page_number):
    parsed = urlsplit(STANDARD_REFERENCE_URL)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != 'page']
    query.append(('page', str(int(page_number))))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def parse_forum_rows(rows, page_number, base_url=STANDARD_REFERENCE_URL):
    parsed_records = []
    for row in rows or []:
        raw_title = str((row or {}).get('title') or '').strip()
        parsed_title = parse_forum_thread_title(raw_title)
        href = str((row or {}).get('href') or '').strip()
        if not parsed_title or not href:
            continue
        parsed_records.append({
            **parsed_title,
            'thread_url': urljoin(base_url, href),
            'page_number': int(page_number),
        })
    return parsed_records


class StandardReferenceScraper:
    def __init__(self, profile_dir=None, playwright_factory=None, headless=False):
        self.profile_dir = profile_dir or STANDARD_REFERENCE_PROFILE_DIR
        self.playwright_factory = playwright_factory or (lambda: import_sync_playwright()())
        self.headless = bool(headless)
        self._manager = None
        self._playwright = None
        self._context = None

    def session(self):
        return _StandardReferenceBrowserSession(self)

    def _open_session(self):
        self._manager = self.playwright_factory()
        self._playwright = self._manager.start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel='chrome',
            headless=self.headless,
            locale=get_scraper_locale(),
            viewport={'width': 1440, 'height': 1000},
        )
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return page

    def _close_session(self):
        manager = self._manager
        context = self._context
        self._manager = None
        self._context = None
        self._playwright = None
        if manager is not None:
            manager.__exit__(None, None, None)
        elif context is not None:
            context.close()

    @staticmethod
    def _extract_rows(page):
        return page.evaluate(
            '''() => {
                const rows = Array.from(document.querySelectorAll('tr[id^="normalthread_"]'));
                const result = rows.map((row) => {
                    const link = row.querySelector('a.xst, a[href*="viewthread.php?tid="]');
                    if (!link) return null;
                    return {
                        title: (link.innerText || link.textContent || '').replace(/\\s+/g, ' ').trim(),
                        href: link.getAttribute('href') || '',
                    };
                }).filter(Boolean);
                if (result.length) return result;
                return Array.from(document.querySelectorAll('a.xst, a[href*="viewthread.php?tid="]'))
                    .map((link) => ({
                        title: (link.innerText || link.textContent || '').replace(/\\s+/g, ' ').trim(),
                        href: link.getAttribute('href') || '',
                    }));
            }'''
        )

    def fetch_page(self, page, page_number, should_stop=None):
        if callable(should_stop) and should_stop():
            return []
        target_url = build_forum_page_url(page_number)
        page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(500)
        return parse_forum_rows(self._extract_rows(page), page_number, target_url)


class _StandardReferenceBrowserSession:
    def __init__(self, scraper):
        self.scraper = scraper

    def __enter__(self):
        return self.scraper._open_session()

    def __exit__(self, exc_type, exc_value, traceback):
        self.scraper._close_session()
        return False
