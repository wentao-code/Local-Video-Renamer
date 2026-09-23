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
    def __init__(self, states=None, goto_failures=None, fail_on_wait=False):
        self.states = list(states or [{'body_text': '', 'html': '', 'rows': []}])
        self.current_index = 0
        self.visited_urls = []
        self.reload_calls = []
        self.wait_calls = []
        self.goto_failures = list(goto_failures or [])
        self.fail_on_wait = bool(fail_on_wait)

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
        if self.fail_on_wait:
            raise AssertionError(f'unexpected wait: {timeout_ms}')
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
    def test_open_results_page_stops_after_bounded_navigation_failures(self):
        page = _SequencedPageStub(
            states=[{'body_text': '', 'html': '', 'rows': []}],
            goto_failures=[RuntimeError('connection reset')] * 5,
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.get_operation_timeout_milliseconds', return_value=1), \
                patch('app.queen_library.scraper.QUEEN_SEARCH_RELOAD_WAIT_MS', 0):
            with self.assertRaises(QueenSearchTransientError):
                scraper._open_results_page(page, 'https://y.9cili.click/search?q=test')

        self.assertLessEqual(len(page.visited_urls), 3)

    def test_open_results_page_honors_stop_request_during_navigation_retry(self):
        page = _SequencedPageStub(
            states=[{'body_text': '', 'html': '', 'rows': []}],
            goto_failures=[RuntimeError('connection reset')],
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.get_operation_timeout_milliseconds', return_value=1), \
                patch('app.queen_library.scraper.QUEEN_SEARCH_RELOAD_WAIT_MS', 0):
            with self.assertRaisesRegex(QueenSearchTransientError, '停止'):
                scraper._open_results_page(
                    page,
                    'https://y.9cili.click/search?q=test',
                    should_stop=lambda: True,
                )

        self.assertEqual(len(page.visited_urls), 0)

    def test_build_search_url_supports_sort_and_page(self):
        self.assertEqual(
            QueenSearchScraper.build_search_url('\u5957\u8def\u76f4\u64ad'),
            'https://y.9cili.click/search?q=%E5%A5%97%E8%B7%AF%E7%9B%B4%E6%92%AD',
        )
        self.assertEqual(
            QueenSearchScraper.build_search_url('\u5957\u8def\u76f4\u64ad', page=5),
            'https://y.9cili.click/search?q=%E5%A5%97%E8%B7%AF%E7%9B%B4%E6%92%AD&page=5',
        )
        self.assertEqual(
            QueenSearchScraper.build_search_url('\u5957\u8def\u76f4\u64ad', sort='relevance', page=2),
            'https://y.9cili.click/search?q=%E5%A5%97%E8%B7%AF%E7%9B%B4%E6%92%AD&sort=relevance&page=2',
        )

    def test_search_visits_ten_pages_in_order_and_deduplicates_combined_records(self):
        page = _SequencedPageStub(
            [
                {
                    'records': [
                        {'title': f'{QUEEN_PREFIX}QueenA_Title.mp4', 'href': '/hash/a'},
                        {'title': f'{QUEEN_PREFIX}QueenB_Title.mp4', 'href': '/hash/b'},
                    ],
                    'rows': [
                        f'{QUEEN_PREFIX}QueenA_Title.mp4',
                        f'{QUEEN_PREFIX}QueenB_Title.mp4',
                    ],
                }
            ]
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None), \
                patch('app.queen_library.scraper.get_operation_timeout_milliseconds', return_value=120000):
            result = scraper.search('\u5957\u8def\u76f4\u64ad', show_browser=False, page=page)

        base_url = QueenSearchScraper.build_search_url('\u5957\u8def\u76f4\u64ad')
        relevance_url = QueenSearchScraper.build_search_url('\u5957\u8def\u76f4\u64ad', sort='relevance')
        expected_urls = [
            base_url,
            *[f'{base_url}&page={page_number}' for page_number in range(2, 6)],
            relevance_url,
            *[f'{relevance_url}&page={page_number}' for page_number in range(2, 6)],
        ]
        visited = [url for url, _kwargs in page.visited_urls]
        self.assertEqual(visited, expected_urls)
        self.assertEqual(
            result['records'],
            [
                {'raw_title': f'{QUEEN_PREFIX}QueenA_Title.mp4', 'detail_url': 'https://y.9cili.click/hash/a'},
                {'raw_title': f'{QUEEN_PREFIX}QueenB_Title.mp4', 'detail_url': 'https://y.9cili.click/hash/b'},
            ],
        )
        self.assertEqual(result['source_urls'], visited)

    def test_search_uses_backup_domain_for_all_pages_when_primary_first_page_fails(self):
        page = _SequencedPageStub(
            [
                {
                    'records': [f'{QUEEN_PREFIX}QueenFallback_Title.mp4'],
                    'rows': [f'{QUEEN_PREFIX}QueenFallback_Title.mp4'],
                }
            ],
            goto_failures=[RuntimeError('primary domain unavailable')],
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None), \
                patch('app.queen_library.scraper.get_operation_timeout_milliseconds', return_value=120000):
            result = scraper.search('\u5957\u8def\u76f4\u64ad', show_browser=False, page=page)

        visited = [url for url, _kwargs in page.visited_urls]
        self.assertEqual(len(visited), 11)
        self.assertTrue(visited[0].startswith('https://y.9cili.click/search?'))
        self.assertTrue(all(url.startswith('https://a.1cili.click/search?') for url in visited[1:]))
        self.assertEqual(result['source_url'], visited[1])

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
                    'detail_url': 'https://y.9cili.click/hash/abc123',
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
        self.assertEqual(page.wait_calls[:2], [200, 200])
        self.assertEqual(len(page.reload_calls), 20)
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
        self.assertEqual(page.wait_calls, [])
        self.assertEqual(len(page.visited_urls), 11)
        self.assertEqual(page.reload_calls, [])

    def test_search_treats_zero_results_page_as_ready(self):
        page = _SequencedPageStub(
            [
                {
                    'body_text': "0 results\n我们未能找到关于 '03loveyo' 的资源\n请尝试更短或更宽泛的关键词",
                    'html': '<title>03loveyo - 0个相关资源 - ØMagnet</title>',
                    'rows': [],
                },
            ],
            fail_on_wait=True,
        )
        scraper = _SearchHarness(page)

        with patch('app.queen_library.scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search('03loveyo', show_browser=False, page=page)

        self.assertEqual(result['records'], [])
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
