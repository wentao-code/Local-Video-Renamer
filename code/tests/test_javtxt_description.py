import unittest

from app.scraper.javtxt_scraper import JavtxtScraper


class _Locator:
    def __init__(self, text=''):
        self._text = text
        self.first = self

    def inner_text(self, timeout=3000):
        return self._text


class _Page:
    url = 'https://javtxt.example/v/511'

    def locator(self, selector):
        if selector == 'h1':
            return _Locator('ROE-511 Sample Title')
        return _Locator('')

    def title(self):
        return 'ROE-511 Sample Title'


class JavtxtDescriptionTest(unittest.TestCase):
    def test_parse_movie_info_extracts_plot_description(self):
        lines = [
            '剧情介绍',
            '毕业后毫无风发决定在东京打拼的优。她用温柔包容我的一切。',
            '类别',
            '熟女 单体作品',
            '出演女优',
            '木户薰',
            '番号',
            'ROE-511',
        ]

        info = JavtxtScraper().parse_movie_info(_Page(), 'ROE-511', lines=lines)

        self.assertEqual(info['javtxt_description'], '毕业后毫无风发决定在东京打拼的优。她用温柔包容我的一切。')
        self.assertEqual(info['javtxt_tags'], '熟女 单体作品')


if __name__ == '__main__':
    unittest.main()
