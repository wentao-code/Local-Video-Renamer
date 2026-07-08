import json
import tempfile
import unittest
from pathlib import Path

from app.services.queen_library_service import QueenLibraryService


class _ScraperStub:
    def __init__(self, records=None, records_by_keyword=None):
        self.records = list(records or [])
        self.records_by_keyword = dict(records_by_keyword or {})
        self.calls = []

    def search(self, keyword, show_browser=True):
        self.calls.append((keyword, bool(show_browser)))
        records = self.records_by_keyword.get(keyword, self.records)
        return {
            'source_url': f'https://a.1cili.click/search?q={keyword}',
            'records': list(records),
        }


class QueenLibraryServiceTest(unittest.TestCase):
    def test_search_keyword_imports_unique_records_and_blocks_duplicate_keyword(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                [
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_\u8214\u978b\u8214\u811a\u8e22\u88c6_2.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_\u8214\u978b\u8214\u811a\u8e22\u88c6_2.mp4',
                    '\u65e0\u6548\u6807\u9898',
                    '\u5957\u8def\u76f4\u64ad_\u767d\u4e00\u6657_\u5973\u738b\u69a8\u6c41.mp4',
                ]
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)

            result = service.search_keyword('\u5c0f7s')

            self.assertEqual(scraper.calls, [('\u5c0f7s', True)])
            self.assertEqual(result['imported_count'], 2)
            self.assertEqual(result['skipped_count'], 2)
            self.assertEqual(
                [row['queen_name'] for row in result['queens']],
                ['\u5c0f7s', '\u767d\u4e00\u6657'],
            )
            self.assertEqual(len(service.list_keywords()), 1)

            with self.assertRaisesRegex(ValueError, '\u5173\u952e\u8bcd\u5df2\u5b58\u5728'):
                service.search_keyword('\u5c0f7s')

    def test_parse_record_extracts_queen_and_video_title_with_index(self):
        parsed = QueenLibraryService.parse_record_title(
            '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_\u8214\u978b\u8214\u811a\u8e22\u88c6_\u5168\u4f53\u8e29\u8e0f_\u9694\u5185\u88e4\u8e29\u9e21_\u8db3\u4ea4\u5012\u8ba1\u65f6_2.mp4'
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['queen_name'], '\u5c0f7s')
        self.assertEqual(
            parsed['video_title'],
            '\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_\u8214\u978b\u8214\u811a\u8e22\u88c6_\u5168\u4f53\u8e29\u8e0f_\u9694\u5185\u88e4\u8e29\u9e21_\u8db3\u4ea4\u5012\u8ba1\u65f6_2',
        )

    def test_parse_record_strips_plain_mp4_suffix_from_title(self):
        parsed = QueenLibraryService.parse_record_title(
            '\u5957\u8def\u76f4\u64ad_\u4e00\u8336_\u5973\u8001\u5e08\u7684\u65e9\u4e9b\u6d4b\u8bd5.mp4'
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['queen_name'], '\u4e00\u8336')
        self.assertEqual(parsed['video_title'], '\u5973\u8001\u5e08\u7684\u65e9\u4e9b\u6d4b\u8bd5')

    def test_search_keyword_keeps_numbered_variants_as_distinct_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                [
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_2.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_3.mp4',
                ]
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)

            result = service.search_keyword('\u5a31\u6d4b\u8bd5\u8bcd')

            self.assertEqual(result['imported_count'], 2)
            self.assertEqual(result['skipped_count'], 0)
            detail = service.get_queen_detail('\u5c0f7s')
            self.assertEqual(
                [row['video_title'] for row in detail['videos']],
                ['\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_3', '\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_2'],
            )

    def test_refresh_all_searches_keywords_and_queen_terms_and_writes_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            log_path = Path(temp_dir) / 'queen_crawl.log'
            scraper = _ScraperStub(
                records_by_keyword={
                    '\u521d\u59cb\u8bcd': [
                        '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u65e7\u6807\u9898.mp4',
                    ],
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s': [
                        '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u65e7\u6807\u9898.mp4',
                        '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u65b0\u6807\u9898_2.mp4',
                    ],
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper, crawl_log_path=log_path)
            service.search_keyword('\u521d\u59cb\u8bcd', show_browser=False)

            result = service.refresh_all(show_browser=True)

            self.assertEqual(scraper.calls[-2:], [('\u521d\u59cb\u8bcd', True), ('\u5957\u8def\u76f4\u64ad_\u5c0f7s', True)])
            self.assertEqual(result['query_count'], 2)
            self.assertEqual(result['scanned_count'], 3)
            self.assertEqual(result['imported_count'], 1)
            self.assertEqual(result['skipped_count'], 2)
            self.assertEqual(len(service.get_queen_detail('\u5c0f7s')['videos']), 2)
            self.assertTrue(log_path.exists())

            log_payload = json.loads(log_path.read_text(encoding='utf-8').strip().splitlines()[-1])
            self.assertEqual(log_payload['query_count'], 2)
            self.assertEqual(log_payload['imported_count'], 1)
            self.assertEqual(log_payload['skipped_count'], 2)
            self.assertTrue(log_payload['show_browser'])
            self.assertEqual([row['keyword'] for row in log_payload['queries']], ['\u521d\u59cb\u8bcd', '\u5957\u8def\u76f4\u64ad_\u5c0f7s'])

    def test_delete_video_and_delete_queen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                [
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_2.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u9ad8\u8ddf\u8e29\u8e0f_3.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u767d\u4e00\u6657_\u5973\u738b\u69a8\u6c41.mp4',
                ]
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u6d4b\u8bd5\u8bcd')

            detail = service.get_queen_detail('\u5c0f7s')
            self.assertEqual(len(detail['videos']), 2)

            deleted_count = service.delete_queen_video(detail['videos'][0]['id'])
            self.assertEqual(deleted_count, 1)
            self.assertEqual(len(service.get_queen_detail('\u5c0f7s')['videos']), 1)

            removed_count = service.delete_queen('\u5c0f7s')
            self.assertEqual(removed_count, 1)
            self.assertEqual([row['queen_name'] for row in service.list_queens()], ['\u767d\u4e00\u6657'])


if __name__ == '__main__':
    unittest.main()
