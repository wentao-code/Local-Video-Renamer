import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.queen_library.scraper import QueenSearchScraper, QueenSearchTransientError


QUEEN_PREFIX = '\u5957\u8def\u76f4\u64ad_'


class _LocatorStub:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class _SequencedPageStub:
    def __init__(self, states=None, goto_failures=None):
        self.states = list(states or [{'body_text': '', 'html': '', 'rows': []}])
        self.current_index = 0
        self.visited_urls = []
        self.reload_calls = []
        self.wait_calls = []
        self.goto_failures = list(goto_failures or [])

    @property
    def current_state(self):
        return self.states[min(self.current_index, len(self.states) - 1)]

    def goto(self, url, **kwargs):
        self.visited_urls.append((url, kwargs))
        if self.goto_failures:
            error = self.goto_failures.pop(0)
            if error is not None:
                raise error
        self.current_index = 0

    def reload(self, **kwargs):
        self.reload_calls.append(kwargs)
        if self.current_index < len(self.states) - 1:
            self.current_index += 1

    def wait_for_timeout(self, timeout_ms):
        self.wait_calls.append(timeout_ms)

    def locator(self, selector):
        if selector != 'body':
            raise AssertionError(f'unexpected selector: {selector}')
        return _LocatorStub(self.current_state.get('body_text', ''))

    def content(self):
        return self.current_state.get('html', '')

    def evaluate(self, _script):
        if 'href' in str(_script or ''):
            return list(self.current_state.get('records', []))
        return list(self.current_state.get('rows', []))


class _SearchHarness(QueenSearchScraper):
    def __init__(self, page):
        super().__init__(headless=True)
        self._page_stub = page
        self.session_enter_count = 0
        self.session_show_browser_values = []

    @contextmanager
    def session(self, show_browser=None):
        self.session_show_browser_values.append(show_browser)
        if show_browser is not None:
            self.configure_browser_visibility(show_browser)
        self.session_enter_count += 1
        yield self._page_stub


class QueenSearchScraperTest(unittest.TestCase):
    def test_extract_result_row_records_includes_absolute_detail_urls(self):
        page = _SequencedPageStub(
            [
                {
                    'records': [
                        {
                            'title': f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
                            'href': '/hash/abc123',
                        },
                        {
                            'title': f'{QUEEN_PREFIX}QueenB_Title.mp4',
                            'href': 'https://a.1cili.click/hash/def456',
                        },
                    ],
                }
            ]
        )

        records = QueenSearchScraper.extract_result_row_records(page)

        self.assertEqual(
            records,
            [
                {
                    'raw_title': f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
                    'detail_url': 'https://a.1cili.click/hash/abc123',
                },
                {
                    'raw_title': f'{QUEEN_PREFIX}QueenB_Title.mp4',
                    'detail_url': 'https://a.1cili.click/hash/def456',
                },
            ],
        )

    def test_extract_candidate_titles_from_rows_dedupes_and_preserves_full_title(self):
        rows = [
            f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
            f'  {QUEEN_PREFIX}QueenA_Title_01.mp4  ',
            'plain unrelated title',
            f'{QUEEN_PREFIX}QueenB_Title.mp4',
        ]

        records = QueenSearchScraper.extract_candidate_titles_from_rows(rows)

        self.assertEqual(
            records,
            [
                f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
                f'{QUEEN_PREFIX}QueenB_Title.mp4',
            ],
        )

    def test_search_prefers_structured_rows_over_page_title_noise(self):
        page = _SequencedPageStub(
            [
                {
                    'body_text': f'{QUEEN_PREFIX}query\n{QUEEN_PREFIX}QueenA_Title_01.mp4',
                    'html': f'<title>{QUEEN_PREFIX}query - 14 results</title>',
                    'rows': [
                        f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
                        f'{QUEEN_PREFIX}QueenB_Title.mp4',
                        'plain unrelated title',
                    ],
                }
            ]
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search(f'{QUEEN_PREFIX}query', show_browser=False)

        self.assertEqual(
            result['records'],
            [
                f'{QUEEN_PREFIX}QueenA_Title_01.mp4',
                f'{QUEEN_PREFIX}QueenB_Title.mp4',
            ],
        )

    def test_search_reuses_supplied_page_without_opening_nested_session(self):
        page = _SequencedPageStub([{'rows': [f'{QUEEN_PREFIX}QueenTest_Title.mp4']}])
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search(f'{QUEEN_PREFIX}query', show_browser=False, page=page)

        self.assertEqual(scraper.session_enter_count, 0)
        self.assertEqual(result['records'], [f'{QUEEN_PREFIX}QueenTest_Title.mp4'])

    def test_search_configures_visible_browser_before_opening_session(self):
        page = _SequencedPageStub([{'rows': [f'{QUEEN_PREFIX}QueenVisible_Title.mp4']}])
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search(f'{QUEEN_PREFIX}visible-query', show_browser=True)

        self.assertEqual(result['records'], [f'{QUEEN_PREFIX}QueenVisible_Title.mp4'])
        self.assertFalse(scraper.headless)
        self.assertEqual(scraper.session_show_browser_values, [True])

    def test_search_waits_and_reloads_until_real_results_page_is_ready(self):
        page = _SequencedPageStub(
            [
                {
                    'body_text': 'loading...',
                    'html': '<title>loading</title>',
                    'rows': [],
                },
                {
                    'body_text': 'still loading...',
                    'html': '<title>loading</title>',
                    'rows': [],
                },
                {
                    'body_text': f'{QUEEN_PREFIX}QueenReady_Title.mp4',
                    'html': '<title>results</title>',
                    'rows': [f'{QUEEN_PREFIX}QueenReady_Title.mp4'],
                },
            ]
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search(f'{QUEEN_PREFIX}slow-query', show_browser=False, page=page)

        self.assertEqual(result['records'], [f'{QUEEN_PREFIX}QueenReady_Title.mp4'])
        self.assertEqual(page.wait_calls, [20000, 20000])
        self.assertEqual(len(page.reload_calls), 2)
        self.assertEqual(page.visited_urls[0][1]['timeout'], 120000)

    def test_search_retries_same_target_after_initial_navigation_failure(self):
        page = _SequencedPageStub(
            [{'rows': [f'{QUEEN_PREFIX}QueenRecovered_Title.mp4']}],
            goto_failures=[RuntimeError('navigation failed'), None],
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search(f'{QUEEN_PREFIX}recover-query', show_browser=False, page=page)

        self.assertEqual(result['records'], [f'{QUEEN_PREFIX}QueenRecovered_Title.mp4'])
        self.assertEqual(page.wait_calls, [20000])
        self.assertEqual(len(page.visited_urls), 2)
        self.assertEqual(page.reload_calls, [])

    def test_search_raises_transient_error_for_cloudflare_522_page(self):
        page = _SequencedPageStub(
            [
                {
                    'body_text': 'Connection timed out Error code 522 Browser Working Cloudflare Working Host Error',
                    'html': '<title>522: Connection timed out</title>',
                    'rows': [],
                },
            ]
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            with self.assertRaises(QueenSearchTransientError):
                scraper.search(f'{QUEEN_PREFIX}cloudflare-down', show_browser=False, page=page)


if __name__ == '__main__':
    unittest.main()
