import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from app.queen_library.scraper import QueenSearchTransientError
from app.queen_library.service import QueenLibraryService


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


class _SessionReuseScraperStub:
    def __init__(self, records_by_keyword=None):
        self.records_by_keyword = dict(records_by_keyword or {})
        self.calls = []
        self.pages = []
        self.visibility_calls = []
        self.session_enter_count = 0
        self.page = object()

    def configure_browser_visibility(self, show_browser):
        self.visibility_calls.append(bool(show_browser))

    @contextmanager
    def session(self):
        self.session_enter_count += 1
        yield self.page

    def search(self, keyword, show_browser=True, page=None):
        if page is None:
            with self.session() as active_page:
                return self.search(keyword, show_browser=show_browser, page=active_page)
        self.calls.append((keyword, bool(show_browser)))
        self.pages.append(page)
        return {
            'source_url': f'https://a.1cili.click/search?q={keyword}',
            'records': list(self.records_by_keyword.get(keyword, [])),
        }


class _TransientFailureScraperStub(_SessionReuseScraperStub):
    def __init__(self, records_by_keyword=None, transient_keywords=None):
        super().__init__(records_by_keyword=records_by_keyword)
        self.transient_keywords = set(transient_keywords or [])

    def search(self, keyword, show_browser=True, page=None):
        self.calls.append((keyword, bool(show_browser)))
        self.pages.append(page)
        if keyword in self.transient_keywords:
            raise QueenSearchTransientError('Cloudflare 522 Connection timed out')
        return {
            'source_url': f'https://a.1cili.click/search?q={keyword}',
            'records': list(self.records_by_keyword.get(keyword, [])),
        }


class QueenLibraryServiceTest(unittest.TestCase):
    @staticmethod
    def _queue_rows(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                '''
                SELECT keyword, status
                FROM queen_crawl_queue_log
                ORDER BY id ASC
                '''
            ).fetchall()
        finally:
            conn.close()

    @staticmethod
    def _queue_row_dicts(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                '''
                SELECT keyword, status, hand_mark
                FROM queen_crawl_queue_log
                ORDER BY id ASC
                '''
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def test_search_keyword_imports_unique_records_and_blocks_duplicate_keyword(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                [
                    {
                        'raw_title': '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_\u8214\u978b\u8214\u811a\u8e22\u88c6_2.mp4',
                        'detail_url': 'https://a.1cili.click/hash/x7s-001',
                    },
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
            detail = service.get_queen_detail('\u5c0f7s')
            self.assertEqual(detail['videos'][0]['detail_url'], 'https://a.1cili.click/hash/x7s-001')

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

            self.assertEqual(
                scraper.calls[-3:],
                [('\u521d\u59cb\u8bcd', True), ('\u5c0f7s', True), ('\u5957\u8def\u76f4\u64ad_\u5c0f7s', True)],
            )
            self.assertEqual(result['query_count'], 3)
            self.assertEqual(result['scanned_count'], 3)
            self.assertEqual(result['imported_count'], 1)
            self.assertEqual(result['skipped_count'], 2)
            self.assertEqual(len(service.get_queen_detail('\u5c0f7s')['videos']), 2)
            self.assertTrue(log_path.exists())

            log_payload = json.loads(log_path.read_text(encoding='utf-8').strip().splitlines()[-1])
            self.assertEqual(log_payload['query_count'], 3)
            self.assertEqual(log_payload['imported_count'], 1)
            self.assertEqual(log_payload['skipped_count'], 2)
            self.assertTrue(log_payload['show_browser'])
            self.assertEqual(
                [row['keyword'] for row in log_payload['queries']],
                ['\u521d\u59cb\u8bcd', '\u5c0f7s', '\u5957\u8def\u76f4\u64ad_\u5c0f7s'],
            )

    def test_refresh_all_reuses_one_browser_session_across_keywords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _SessionReuseScraperStub(
                records_by_keyword={
                    '\u521d\u59cb\u8bcd': ['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u65e7\u6807\u9898.mp4'],
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s': ['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u65b0\u6807\u9898_2.mp4'],
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            service.search_keyword('\u521d\u59cb\u8bcd', show_browser=False)
            baseline_session_count = scraper.session_enter_count
            baseline_page_count = len(scraper.pages)

            result = service.refresh_all(show_browser=True)

            self.assertEqual(result['query_count'], 3)
            self.assertEqual(scraper.visibility_calls, [True])
            self.assertEqual(scraper.session_enter_count, baseline_session_count + 1)
            self.assertEqual(scraper.pages[baseline_page_count:], [scraper.page, scraper.page, scraper.page])

    def test_refresh_all_skips_transient_cloudflare_failure_and_continues_next_keyword(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _TransientFailureScraperStub(
                records_by_keyword={
                    'good': ['\u5957\u8def\u76f4\u64ad_Good_Title.mp4'],
                },
                transient_keywords={'bad'},
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            conn = sqlite3.connect(db_path)
            try:
                conn.executemany(
                    'INSERT INTO queen_keywords(keyword) VALUES (?)',
                    [('good',), ('bad',)],
                )
                conn.commit()
            finally:
                conn.close()

            result = service.refresh_all(show_browser=False, batch_size=10)

            self.assertFalse(result['stopped'])
            self.assertEqual(result['query_count'], 2)
            self.assertEqual(result['processed_count'], 2)
            self.assertEqual(result['imported_count'], 1)
            self.assertEqual(result['skipped_count'], 1)
            self.assertEqual([keyword for keyword, _show_browser in scraper.calls], ['bad', 'good'])
            bad_query = next(row for row in result['queries'] if row['keyword'] == 'bad')
            self.assertEqual(bad_query['skipped_count'], 1)
            self.assertIn('Cloudflare 522', bad_query['error'])

    def test_refresh_all_reports_progress_after_each_fixed_size_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _ScraperStub(
                records_by_keyword={
                    f'\u5173\u952e\u8bcd{index}': [
                        f'\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898{index}.mp4'
                    ]
                    for index in range(1, 24)
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            conn = sqlite3.connect(db_path)
            try:
                conn.executemany(
                    'INSERT INTO queen_keywords(keyword) VALUES (?)',
                    [(f'\u5173\u952e\u8bcd{index}',) for index in range(1, 24)],
                )
                conn.commit()
            finally:
                conn.close()

            progress_updates = []
            result = service.refresh_all(
                show_browser=False,
                batch_size=10,
                progress_callback=lambda payload: progress_updates.append(dict(payload or {})),
            )

            self.assertEqual(result['query_count'], 23)
            self.assertEqual([row['processed_count'] for row in progress_updates], [10, 20, 23])
            self.assertTrue(progress_updates[-1]['completed'])

    def test_refresh_all_stops_after_current_batch_and_resumes_from_pending_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _ScraperStub(
                records_by_keyword={
                    f'关键词{index}': [f'套路直播_女王_{index}.mp4']
                    for index in range(1, 24)
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            conn = sqlite3.connect(db_path)
            try:
                conn.executemany(
                    'INSERT INTO queen_keywords(keyword) VALUES (?)',
                    [(f'关键词{index}',) for index in range(1, 24)],
                )
                conn.commit()
            finally:
                conn.close()

            progress_updates = []
            stopped = service.refresh_all(
                show_browser=False,
                batch_size=10,
                progress_callback=lambda payload: progress_updates.append(dict(payload or {})),
                should_stop=lambda: len(progress_updates) >= 1,
            )

            self.assertTrue(stopped['stopped'])
            self.assertEqual(stopped['processed_count'], 10)
            self.assertEqual(stopped['remaining_count'], 13)
            self.assertEqual([row['processed_count'] for row in progress_updates], [10])
            self.assertEqual(len(scraper.calls), 10)

            queue_rows = self._queue_rows(db_path)
            self.assertEqual(len(queue_rows), 23)
            self.assertEqual([status for _keyword, status in queue_rows[:10]], ['ok'] * 10)
            self.assertEqual([status for _keyword, status in queue_rows[10:]], [''] * 13)
            expected_resume_keywords = [keyword for keyword, status in queue_rows[10:]]

            resumed = service.refresh_all(show_browser=False, batch_size=10)

            self.assertFalse(resumed['stopped'])
            self.assertEqual(resumed['processed_count'], 13)
            self.assertEqual(resumed['remaining_count'], 0)
            self.assertEqual([keyword for keyword, _flag in scraper.calls[10:]], expected_resume_keywords)
            self.assertEqual(self._queue_rows(db_path), [])

    def test_refresh_all_clears_queue_when_every_row_reaches_ok_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _ScraperStub(
                records_by_keyword={
                    f'关键词{index}': [f'套路直播_女王_{index}.mp4']
                    for index in range(1, 4)
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            conn = sqlite3.connect(db_path)
            try:
                conn.executemany(
                    'INSERT INTO queen_keywords(keyword) VALUES (?)',
                    [(f'关键词{index}',) for index in range(1, 4)],
                )
                conn.commit()
            finally:
                conn.close()

            result = service.refresh_all(show_browser=False, batch_size=10)

            self.assertFalse(result['stopped'])
            self.assertEqual(result['processed_count'], 3)
            self.assertEqual(result['remaining_count'], 0)
            self.assertEqual(self._queue_rows(db_path), [])

    def test_refresh_all_searches_queen_name_and_prefixed_name_without_saving_them_as_keywords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _ScraperStub(
                records_by_keyword={
                    '\u521d\u59cb\u8bcd': ['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898A.mp4'],
                    '\u5c0f7s': ['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898B.mp4'],
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s': ['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898C.mp4'],
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            service.search_keyword('\u521d\u59cb\u8bcd', show_browser=False)
            scraper.calls.clear()

            result = service.refresh_all(show_browser=False, batch_size=10)

            self.assertEqual(result['query_count'], 3)
            self.assertEqual(
                [keyword for keyword, _flag in scraper.calls],
                ['\u521d\u59cb\u8bcd', '\u5c0f7s', '\u5957\u8def\u76f4\u64ad_\u5c0f7s'],
            )
            self.assertEqual(
                [row['keyword'] for row in service.list_keywords()],
                ['\u521d\u59cb\u8bcd'],
            )

    def test_refresh_all_skips_hand_marked_keywords_and_preserves_marks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'queen_library.db'
            scraper = _ScraperStub(
                records_by_keyword={
                    'alpha': ['\u5957\u8def\u76f4\u64ad_Alpha_\u6807\u9898A.mp4'],
                    'beta': ['\u5957\u8def\u76f4\u64ad_Beta_\u6807\u9898B.mp4'],
                    'gamma': ['\u5957\u8def\u76f4\u64ad_Gamma_\u6807\u9898C.mp4'],
                }
            )
            service = QueenLibraryService(db_path, scraper=scraper)
            conn = sqlite3.connect(db_path)
            try:
                conn.executemany(
                    'INSERT INTO queen_keywords(keyword) VALUES (?)',
                    [('alpha',), ('beta',), ('gamma',)],
                )
                conn.execute(
                    '''
                    INSERT INTO queen_crawl_queue_log(keyword, source, status, scanned_count, imported_count, skipped_count, hand_mark)
                    VALUES (?, ?, ?, 0, 0, 0, 1)
                    ''',
                    ('beta', '\u5173\u952e\u8bcd\u5e93', ''),
                )
                conn.commit()
            finally:
                conn.close()

            result = service.refresh_all(show_browser=False, batch_size=10)

            self.assertFalse(result['stopped'])
            self.assertEqual(result['query_count'], 2)
            self.assertEqual([keyword for keyword, _flag in scraper.calls], ['gamma', 'alpha'])
            self.assertEqual(
                self._queue_row_dicts(db_path),
                [{'keyword': 'beta', 'status': '', 'hand_mark': 1}],
            )

    def test_save_queen_profile_marks_queen_as_confirmed_and_returns_detail_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u4e1d\u8db3\u9ad8\u8ddf\u8c03\u6559_2.mp4'])
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u5c0f7s')

            profile = service.save_queen_profile(
                '\u5c0f7s',
                {
                    'body_type': '\u82d7\u6761',
                    'style': '\u7c97\u66b4',
                    'face': '\u662f',
                    'age_group': '\u5c11\u5987',
                    'like_level': 'A',
                },
            )

            self.assertTrue(profile['profile_confirmed'])
            self.assertEqual(profile['body_type'], 'slim')
            self.assertEqual(service.get_queen_detail('\u5c0f7s')['profile']['like_level'], 'A')
            queen_rows = service.list_queens()
            self.assertEqual(queen_rows[0]['queen_name'], '\u5c0f7s')
            self.assertTrue(queen_rows[0]['profile_confirmed'])

    def test_get_library_stats_returns_counts_and_level_distributions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                [
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898A.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u6807\u9898B.mp4',
                    '\u5957\u8def\u76f4\u64ad_\u767d\u4e00\u6657_\u6807\u9898C.mp4',
                ]
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u7edf\u8ba1\u8bcd', show_browser=False)
            service.save_queen_profile(
                '\u5c0f7s',
                {
                    'body_type': '\u82d7\u6761',
                    'style': '\u7c97\u66b4',
                    'face': '\u662f',
                    'age_group': '\u5c11\u5987',
                    'like_level': 'A',
                },
            )
            detail = service.get_queen_detail('\u5c0f7s')
            service.update_queen_video_metadata(detail['videos'][0]['id'], '\u8c03\u6559', 'S')

            stats = service.get_library_stats()

            self.assertEqual(stats['queen_count'], 2)
            self.assertEqual(stats['video_count'], 3)
            self.assertEqual(
                {row['level']: row['count'] for row in stats['like_level_distribution']},
                {'A': 1, 'B': 0, 'C': 0, 'D': 0, '': 1},
            )
            self.assertEqual(
                {row['level']: row['count'] for row in stats['video_level_distribution']},
                {'S': 1, 'A': 0, 'B': 0, 'C': 0, '': 2},
            )

    def test_save_queen_profile_rejects_incomplete_or_unknown_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=_ScraperStub())

            with self.assertRaisesRegex(ValueError, 'body_type'):
                service.save_queen_profile(
                    '\u5c0f7s',
                    {
                        'body_type': '',
                        'style': '\u6e29\u548c',
                        'face': '\u5426',
                        'age_group': '\u719f\u5973',
                        'like_level': 'B',
                    },
                )

            with self.assertRaisesRegex(ValueError, 'like_level'):
                service.save_queen_profile(
                    '\u5c0f7s',
                    {
                        'body_type': '\u80a5\u80d6',
                        'style': '\u6e29\u548c',
                        'face': '\u5426',
                        'age_group': '\u719f\u5973',
                        'like_level': 'S',
                    },
                )

    def test_update_queen_video_metadata_saves_content_type_and_level(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(['\u5957\u8def\u76f4\u64ad_\u5c0f7s_\u8c03\u6559_2.mp4'])
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u5c0f7s')
            record_id = service.get_queen_detail('\u5c0f7s')['videos'][0]['id']

            saved = service.update_queen_video_metadata(record_id, '\u8c03\u6559', 'S')

            self.assertEqual(saved['content_type'], 'discipline')
            self.assertEqual(saved['content_level'], 'S')
            detail = service.get_queen_detail('\u5c0f7s')
            self.assertEqual(detail['videos'][0]['content_type'], 'discipline')
            self.assertEqual(detail['videos'][0]['content_level'], 'S')

            with self.assertRaisesRegex(ValueError, '\u5185\u5bb9'):
                service.update_queen_video_metadata(record_id, '\u672a\u77e5', 'S')
            with self.assertRaisesRegex(ValueError, '\u7b49\u7ea7'):
                service.update_queen_video_metadata(record_id, '\u8c03\u6559', 'SS')

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

    def test_rename_queen_merges_into_existing_name_and_prefers_current_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                records_by_keyword={
                    '\u65e7\u540d\u8bcd': [
                        '\u5957\u8def\u76f4\u64ad_\u65e7\u540d_\u91cd\u590d\u6807\u9898.mp4',
                        '\u5957\u8def\u76f4\u64ad_\u65e7\u540d_\u65e7\u540d\u72ec\u6709.mp4',
                    ],
                    '\u65b0\u540d\u8bcd': [
                        {
                            'raw_title': '\u5957\u8def\u76f4\u64ad_\u65b0\u540d_\u91cd\u590d\u6807\u9898.mp4',
                            'detail_url': 'https://a.1cili.click/hash/dup-detail',
                        },
                        '\u5957\u8def\u76f4\u64ad_\u65b0\u540d_\u65b0\u540d\u72ec\u6709.mp4',
                    ],
                }
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u65e7\u540d\u8bcd', show_browser=False)
            service.search_keyword('\u65b0\u540d\u8bcd', show_browser=False)

            service.save_queen_profile(
                '\u65e7\u540d',
                {
                    'body_type': '\u82d7\u6761',
                    'style': '\u7c97\u66b4',
                    'face': '\u662f',
                    'age_group': '\u5c11\u5987',
                    'like_level': 'A',
                },
            )
            service.save_queen_profile(
                '\u65b0\u540d',
                {
                    'body_type': '\u80a5\u80d6',
                    'style': '\u6e29\u548c',
                    'face': '\u5426',
                    'age_group': '\u719f\u5973',
                    'like_level': 'D',
                },
            )
            duplicate_source_id = next(
                row['id']
                for row in service.get_queen_detail('\u65e7\u540d')['videos']
                if row['video_title'] == '\u91cd\u590d\u6807\u9898'
            )
            service.update_queen_video_metadata(duplicate_source_id, '\u8c03\u6559', 'S')

            merged = service.rename_queen(
                '\u65e7\u540d',
                '\u65b0\u540d',
                profile={
                    'body_type': '\u82d7\u6761',
                    'style': '\u7c97\u66b4',
                    'face': '\u662f',
                    'age_group': '\u5c11\u5987',
                    'like_level': 'A',
                },
            )

            self.assertEqual(merged['queen_name'], '\u65b0\u540d')
            self.assertEqual([row['queen_name'] for row in service.list_queens()], ['\u65b0\u540d'])
            self.assertEqual(merged['profile']['like_level'], 'A')
            self.assertEqual(merged['profile']['body_type'], 'slim')
            self.assertEqual(len(merged['videos']), 3)

            duplicate_rows = [row for row in merged['videos'] if row['video_title'] == '\u91cd\u590d\u6807\u9898']
            self.assertEqual(len(duplicate_rows), 1)
            self.assertEqual(duplicate_rows[0]['detail_url'], 'https://a.1cili.click/hash/dup-detail')
            self.assertEqual(duplicate_rows[0]['content_type'], 'discipline')
            self.assertEqual(duplicate_rows[0]['content_level'], 'S')

    def test_rename_queen_moves_records_when_target_name_does_not_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(['\u5957\u8def\u76f4\u64ad_\u65e7\u540d_\u6807\u9898A.mp4'])
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u6d4b\u8bd5\u8bcd', show_browser=False)

            renamed = service.rename_queen('\u65e7\u540d', '\u65b0\u540d')

            self.assertEqual(renamed['queen_name'], '\u65b0\u540d')
            self.assertEqual([row['queen_name'] for row in service.list_queens()], ['\u65b0\u540d'])
            self.assertEqual(len(renamed['videos']), 1)
            self.assertEqual(renamed['videos'][0]['queen_name'], '\u65b0\u540d')

    def test_renamed_queen_alias_normalizes_future_imports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper = _ScraperStub(
                records_by_keyword={
                    '\u521d\u59cb\u8bcd': [
                        '\u5957\u8def\u76f4\u64ad_\u9519\u8bef\u540d_\u6807\u9898A.mp4',
                    ],
                    '\u518d\u6b21\u6293\u53d6': [
                        '\u5957\u8def\u76f4\u64ad_\u9519\u8bef\u540d_\u6807\u9898A.mp4',
                        '\u5957\u8def\u76f4\u64ad_\u9519\u8bef\u540d_\u6807\u9898B.mp4',
                    ],
                }
            )
            service = QueenLibraryService(Path(temp_dir) / 'queen_library.db', scraper=scraper)
            service.search_keyword('\u521d\u59cb\u8bcd', show_browser=False)

            service.rename_queen('\u9519\u8bef\u540d', '\u6807\u51c6\u540d')
            result = service.search_keyword('\u518d\u6b21\u6293\u53d6', show_browser=False)

            self.assertEqual(result['imported_count'], 1)
            self.assertEqual(result['skipped_count'], 1)
            self.assertEqual([row['queen_name'] for row in service.list_queens()], ['\u6807\u51c6\u540d'])
            detail = service.get_queen_detail('\u6807\u51c6\u540d')
            self.assertEqual(
                sorted(row['video_title'] for row in detail['videos']),
                ['\u6807\u9898A', '\u6807\u9898B'],
            )
            self.assertEqual({row['queen_name'] for row in detail['videos']}, {'\u6807\u51c6\u540d'})


if __name__ == '__main__':
    unittest.main()
