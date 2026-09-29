import tempfile
import unittest
from pathlib import Path

from app.queen_library.standard_reference_library import (
    StandardReferenceLibraryService,
    parse_forum_thread_title,
)


class StandardReferenceLibraryTest(unittest.TestCase):
    def test_parses_second_bracket_as_author_and_removes_price_suffix(self):
        record = parse_forum_thread_title(
            '【调教视频】【双子】私影170女仕首调 bf64049 - [售价 3 彩币]'
        )

        self.assertEqual(record['author_name'], '双子')
        self.assertEqual(record['video_title'], '私影170女仕首调 bf64049')

    def test_service_deduplicates_thread_urls_and_groups_by_author(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = StandardReferenceLibraryService(Path(temp_dir) / 'standard-reference.db')
            service.save_page_records([
                {
                    'author_name': '双子',
                    'video_title': '视频一',
                    'raw_title': '【调教视频】【双子】视频一',
                    'thread_url': 'http://www.aicaiaicai.com/thread-1-1-1.html',
                    'page_number': 1,
                },
                {
                    'author_name': '双子',
                    'video_title': '视频一',
                    'raw_title': '【调教视频】【双子】视频一',
                    'thread_url': 'http://www.aicaiaicai.com/thread-1-1-1.html',
                    'page_number': 2,
                },
                {
                    'author_name': '双子',
                    'video_title': '视频二',
                    'raw_title': '【调教视频】【双子】视频二',
                    'thread_url': 'http://www.aicaiaicai.com/thread-2-1-1.html',
                    'page_number': 1,
                },
            ])

            authors = service.list_authors()
            detail = service.get_author_detail('双子')

        self.assertEqual(len(authors), 1)
        self.assertEqual(authors[0]['author_name'], '双子')
        self.assertEqual(authors[0]['video_count'], 2)
        self.assertEqual([row['video_title'] for row in detail['videos']], ['视频二', '视频一'])

    def test_page_count_validation_rejects_zero_and_non_integer_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = StandardReferenceLibraryService(Path(temp_dir) / 'standard-reference.db')

            for page_count in (0, -1, 'abc'):
                with self.subTest(page_count=page_count), self.assertRaises(ValueError):
                    service.validate_page_count(page_count)


if __name__ == '__main__':
    unittest.main()
