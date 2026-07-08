import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.scraper.queen_search_scraper import QueenSearchScraper


class _LocatorStub:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class _PageStub:
    def __init__(self, body_text='', html='', rows=None):
        self.body_text = body_text
        self.html = html
        self.rows = list(rows or [])
        self.visited_urls = []

    def goto(self, url, **kwargs):
        self.visited_urls.append((url, kwargs))

    def locator(self, selector):
        if selector != 'body':
            raise AssertionError(f'unexpected selector: {selector}')
        return _LocatorStub(self.body_text)

    def content(self):
        return self.html

    def evaluate(self, _script):
        return list(self.rows)


class _SearchHarness(QueenSearchScraper):
    def __init__(self, page):
        super().__init__(headless=True)
        self._page_stub = page

    @contextmanager
    def session(self):
        yield self._page_stub


class QueenSearchScraperTest(unittest.TestCase):
    def test_extract_candidate_titles_from_rows_dedupes_and_preserves_full_title(self):
        rows = [
            '套路直播_王子殿下_看病时间治早泄三次测_试一次治疗一次复诊_护士姐姐的早泄治疗 冲冲冲~榨精护士黑丝打飞机 节奏寸止龟头责足交.mp4',
            '  套路直播_王子殿下_看病时间治早泄三次测_试一次治疗一次复诊_护士姐姐的早泄治疗 冲冲冲~榨精护士黑丝打飞机 节奏寸止龟头责足交.mp4  ',
            '各种直播+韩舞+扣币',
            '套路直播_【艾琳175】面试 家奴 测试 踩踏 舔靴 耳光.mp4',
        ]

        records = QueenSearchScraper.extract_candidate_titles_from_rows(rows)

        self.assertEqual(
            records,
            [
                '套路直播_王子殿下_看病时间治早泄三次测_试一次治疗一次复诊_护士姐姐的早泄治疗 冲冲冲~榨精护士黑丝打飞机 节奏寸止龟头责足交.mp4',
                '套路直播_【艾琳175】面试 家奴 测试 踩踏 舔靴 耳光.mp4',
            ],
        )

    def test_search_prefers_structured_rows_over_page_title_noise(self):
        page = _PageStub(
            body_text='套路直播_测试一下\n套路直播_王子殿下_看病时间治早泄三次测',
            html='<title>套路直播_测试一下 - 14个相关资源</title>',
            rows=[
                '套路直播_王子殿下_看病时间治早泄三次测_试一次治疗一次复诊_护士姐姐的早泄治疗 冲冲冲~榨精护士黑丝打飞机 节奏寸止龟头责足交.mp4',
                '套路直播_【艾琳175】面试 家奴 测试 踩踏 舔靴 耳光.mp4',
                '各种直播+韩舞+扣币',
            ],
        )
        scraper = _SearchHarness(page)

        with patch('app.scraper.queen_search_scraper.wait_for_page_ready', lambda _page: None):
            result = scraper.search('套路直播_测试一下', show_browser=False)

        self.assertEqual(
            result['records'],
            [
                '套路直播_王子殿下_看病时间治早泄三次测_试一次治疗一次复诊_护士姐姐的早泄治疗 冲冲冲~榨精护士黑丝打飞机 节奏寸止龟头责足交.mp4',
                '套路直播_【艾琳175】面试 家奴 测试 踩踏 舔靴 耳光.mp4',
            ],
        )


if __name__ == '__main__':
    unittest.main()
