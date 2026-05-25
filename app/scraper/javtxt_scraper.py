import re
from contextlib import contextmanager

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.runtime_config import (
    get_javtxt_base_url,
    get_javtxt_search_url,
    get_scraper_browser_channel,
    get_scraper_locale,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.scraper.avfan_scraper import import_sync_playwright, wait_for_page_ready
from app.scraper.browser_window import minimize_browser_window_if_needed


JAVTXT_DETAIL_RE = re.compile(r'/v/(\d+)')
SECTION_ICON_RE = re.compile(r'^[^\w\s]')
TITLE_SUFFIX_RE = re.compile(r'\s*-\s*JAV.*$', re.I)

TITLE_SECTION_LABELS = {'番号', '演员', '出演女优'}
ACTOR_SECTION_LABELS = ('出演女优', '演员')
RELEASE_DATE_LABELS = ('📆 发行时间', '发行时间', '發行時間')
MAKER_LABELS = ('🎥 片商', '片商')
PUBLISHER_LABELS = ('🔖 厂牌', '厂牌', '廠牌')
TAG_LABELS = ('🏷️ 类别', '类别', '類別')
DESCRIPTION_LABELS = ('📝 剧情介绍', '剧情介绍', '劇情介紹')


class JavtxtScraper:
    def __init__(self, headless=True, locale=None):
        self.headless = headless
        self.locale = str(locale or get_scraper_locale()).strip() or get_scraper_locale()
        self.base_url = get_javtxt_base_url()
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

    def fetch_by_code(self, code):
        normalized_code = normalize_code(code)
        if not normalized_code:
            raise ValueError('视频编号不能为空')

        with self.session() as page:
            search_url = self.build_search_url(normalized_code)
            page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)

            detail_url = self.find_first_detail_url(page)
            if not detail_url:
                return {
                    'code': normalized_code,
                    'found': False,
                    'error': '未搜索到匹配影片',
                    'source': JAVTXT_VIDEO_SOURCE,
                }

            page.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_page_ready(page)
            info = self.parse_movie_info(page, normalized_code)
            info['found'] = bool(info.get('javtxt_movie_id'))
            info['source'] = JAVTXT_VIDEO_SOURCE
            return info

    def build_search_url(self, normalized_code):
        search_code = re.sub(r'[^A-Z0-9]', '', str(normalized_code or '').upper())
        return get_javtxt_search_url(search_code)

    def find_first_detail_url(self, page):
        links = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]'))
                .map((node) => {
                    try {
                        return new URL(node.getAttribute('href'), location.href).href;
                    } catch (error) {
                        return '';
                    }
                })
                .filter((href) => /\\/v\\/\\d+/.test(href));
            """
        )
        return links[0] if links else ''

    def parse_movie_info(self, page, requested_code):
        lines = visible_lines(page)
        final_url = page.url or ''
        movie_id = extract_javtxt_movie_id(final_url)
        title = extract_title(page, lines, requested_code)
        actors_text = normalize_second_source_actor_text(extract_section_text(lines, ACTOR_SECTION_LABELS))
        release_date = extract_detail_value(lines, RELEASE_DATE_LABELS)
        maker = extract_detail_value(lines, MAKER_LABELS)
        publisher = extract_detail_value(lines, PUBLISHER_LABELS)
        tags_text = extract_section_text(lines, TAG_LABELS)
        description = extract_section_text(lines, DESCRIPTION_LABELS)
        return {
            'code': requested_code,
            'title': title,
            'author': actors_text,
            'release_date': release_date,
            'maker': maker,
            'publisher': publisher,
            'description': description,
            'javtxt_title': title,
            'javtxt_actors': actors_text,
            'javtxt_tags': tags_text,
            'javtxt_description': description,
            'javtxt_movie_id': movie_id,
            'javtxt_url': final_url,
        }


def visible_lines(page):
    try:
        text = page.locator('body').inner_text(timeout=30000)
    except Exception:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_javtxt_movie_id(url):
    match = JAVTXT_DETAIL_RE.search(url or '')
    return match.group(1) if match else ''


def extract_title(page, lines, requested_code):
    for selector in ('main h1', 'article h1', 'h1', 'main h2', 'article h2', 'h2'):
        try:
            text = page.locator(selector).first.inner_text(timeout=3000).strip()
        except Exception:
            continue
        cleaned = clean_title(text, requested_code)
        if cleaned:
            return cleaned

    for actor_label in ACTOR_SECTION_LABELS:
        if actor_label not in lines:
            continue
        label_index = lines.index(actor_label)
        for index in range(label_index - 1, -1, -1):
            cleaned = clean_title(lines[index], requested_code)
            if cleaned and cleaned not in TITLE_SECTION_LABELS:
                return cleaned

    page_title = ''
    try:
        page_title = page.title().strip()
    except Exception:
        page_title = ''
    return clean_title(page_title, requested_code)


def clean_title(text, requested_code):
    value = str(text or '').strip()
    if not value:
        return ''
    value = TITLE_SUFFIX_RE.sub('', value).strip()
    normalized_code = normalize_code(requested_code)
    if normalized_code:
        prefix_pattern = re.compile(rf'^\s*{re.escape(normalized_code)}[-_\s:：]*', re.I)
        value = prefix_pattern.sub('', value).strip()
        hyphenated_code = re.sub(r'([A-Z]+)(\d+)$', r'\1-\2', normalized_code)
        value = re.sub(rf'^\s*{re.escape(hyphenated_code)}[-_\s:：]*', '', value, flags=re.I).strip()
    return value


def extract_detail_value(lines, labels):
    section_lines = extract_section_lines(lines, labels)
    return section_lines[0] if section_lines else ''


def extract_section_text(lines, labels):
    return ' '.join(extract_section_lines(lines, labels)).strip()


def extract_section_lines(lines, labels):
    normalized_labels = {str(label or '').strip() for label in labels}
    for index, line in enumerate(lines):
        if str(line or '').strip() not in normalized_labels:
            continue
        values = []
        for next_index in range(index + 1, len(lines)):
            value = str(lines[next_index] or '').strip()
            if not value:
                continue
            if value in normalized_labels:
                continue
            if is_next_section_label(value):
                break
            values.append(value)
        return values
    return []


def is_next_section_label(text):
    value = str(text or '').strip()
    if not value:
        return False
    if value in {'剧情介绍', '劇情介紹', '出演女优', '演员', '番号', '类别', '類別'}:
        return True
    return bool(SECTION_ICON_RE.match(value)) and len(value) <= 12


def normalize_code(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
