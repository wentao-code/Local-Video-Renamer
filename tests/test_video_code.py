import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import contextmanager
from pathlib import Path

from app.core.filename_rules import extract_code_from_filename
from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.video_code import compact_video_code, has_supported_video_code, standardize_video_code
from app.data.database_handler import VideoDatabase
from app.scraper.javtxt_scraper import extract_page_code
from app.services.code_prefix_entry_parser import extract_code
from app.services.movie_author_resolver import MovieAuthorResolver


class VideoCodeStandardizationTest(unittest.TestCase):
    def test_strips_leading_numeric_vendor_prefix(self):
        samples = {
            '168BOU001': 'BOU-001',
            '168BOU-001': 'BOU-001',
            '360MBMH058': 'MBMH-058',
            '360MBMH-058': 'MBMH-058',
            '013ONEZ075': 'ONEZ-075',
            '013ONEZ-075': 'ONEZ-075',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_keeps_real_numeric_or_alphanumeric_prefixes_when_standardizing(self):
        samples = {
            '010216-061': '010216-061',
            'T28-123': 'T28-123',
            'S2MBD-123': 'S2MBD-123',
        }
        for raw_code, expected in samples.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(standardize_video_code(raw_code), expected)

    def test_pure_numeric_prefix_codes_are_not_supported_for_web_lookup(self):
        self.assertFalse(has_supported_video_code('010216-061'))
        self.assertFalse(
            is_javtxt_eligible_movie(
                {
                    'code': '010216-061',
                    'title': 'sample',
                    'release_date': '2025-01-01',
                }
            )
        )
        self.assertEqual(extract_code('010216-061 sample'), '')
        self.assertIsNone(extract_code_from_filename('010216-061 sample'))

    def test_compact_code_uses_standardized_form_for_lookup(self):
        self.assertEqual(compact_video_code('168BOU-001'), 'BOU001')
        self.assertEqual(compact_video_code('BOU-001'), 'BOU001')

    def test_filename_and_card_parsers_return_standard_code(self):
        self.assertEqual(extract_code_from_filename('168BOU001 title'), 'BOU-001')
        self.assertEqual(extract_code('360MBMH-058 熟年同窓会'), 'MBMH-058')

    def test_javtxt_page_code_extraction_matches_standard_lookup_code(self):
        self.assertEqual(extract_page_code(['番号', 'bou-001 (h_113bou00001)']), 'BOU001')


class VideoCodeDatabaseMigrationTest(unittest.TestCase):
    def test_database_init_normalizes_existing_actor_movie_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('actor', '168BOUZ-004', 'title', '', '2025-04-29', 'done', '506760', 'https://javtxt.top/v/506760', '2025-04-29'),
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code, javtxt_movie_id, javtxt_url
                    FROM actor_movies
                    WHERE actor_name = ?
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('BOUZ-004', '506760', 'https://javtxt.top/v/506760')])

    def test_database_init_removes_duplicate_numeric_prefixed_actor_movie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('actor', '168BOU-001', 'title 1', '', '2025-04-28', 'done', '503611', 'https://javtxt.top/v/503611'),
                        ('actor', 'BOU-001', 'title 2', '', '2025-04-10', 'done', '503611', 'https://javtxt.top/v/503611'),
                    ],
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code
                    FROM actor_movies
                    WHERE actor_name = ?
                    ORDER BY code
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('BOU-001',)])

    def test_database_init_clears_numeric_only_web_lookup_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('actor', '010216-061', 'numeric only', '', '2025-01-01', 'done', '999', 'https://javtxt.top/v/999', 'tag'),
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT code, javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM actor_movies
                    WHERE actor_name = ?
                    ''',
                    ('actor',),
                ).fetchall()

        self.assertEqual(rows, [('010216-061', UNENRICHED_STATUS, '', '', '')])

    def test_database_init_clears_ineligible_processed_video_javtxt_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO processed_videos (
                        code, title, author, release_date,
                        javtxt_title, javtxt_actors, javtxt_actors_raw,
                        javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_enrichment_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'SQTE-241',
                        'old title',
                        '',
                        '2019-01-27',
                        'javtxt title',
                        'actor',
                        'actor',
                        '286795',
                        'https://javtxt.top/v/286795',
                        'tag',
                        '已补全',
                    ),
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('SQTE-241',),
                ).fetchall()

        self.assertEqual(rows, [(UNENRICHED_STATUS, '', '', '')])

    def test_database_init_clears_legacy_web_movie_javtxt_state_without_trusted_release_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        'NSPS',
                        'NSPS-702',
                        'legacy movie',
                        '',
                        '2020-12-22',
                        ENRICHED_STATUS,
                        '272298',
                        'https://javtxt.top/v/272298',
                        'tag',
                    ),
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags
                    FROM code_prefix_movies
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('NSPS', 'NSPS-702'),
                ).fetchall()

        self.assertEqual(rows, [(UNENRICHED_STATUS, '', '', '')])

    def test_javtxt_video_library_candidates_skip_ineligible_old_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {'code': 'SQTE-241', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'ABP-123', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "UPDATE processed_videos SET release_date = ? WHERE code = ?",
                    ('2019-01-27', 'SQTE-241'),
                )
                conn.execute(
                    "UPDATE processed_videos SET release_date = ? WHERE code = ?",
                    ('2025-02-01', 'ABP-123'),
                )
                conn.commit()

            rows = db.list_videos_for_enrichment(10, JAVTXT_VIDEO_SOURCE)

        self.assertEqual([row['code'] for row in rows], ['ABP-123'])

    def test_manual_category_candidates_skip_ineligible_old_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, release_date, javtxt_title, javtxt_url,
                        javtxt_tags, javtxt_enrichment_status, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('SQTE-241', 'old processed', '2019-01-27', 'old processed', 'https://javtxt.top/v/286795', 'tag', ENRICHED_STATUS, '', ''),
                        ('ABP-123', 'new processed', '2025-02-01', 'new processed', 'https://javtxt.top/v/123', 'tag', ENRICHED_STATUS, '', '2025-02-01'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, author, release_date, javtxt_url,
                        javtxt_tags, author_raw, video_category, javtxt_release_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('NSPS', 'NSPS-648', 'old web movie', '演员旧', '2017-11-19', 'https://javtxt.top/v/260682', '人妻', '演员旧', '', ''),
                        ('MIDV', 'MIDV-001', 'new web movie', '演员新', '2025-01-01', 'https://javtxt.top/v/456', '人妻', '演员新', '', '2025-01-01'),
                    ],
                )
                conn.commit()

            rows = db.list_videos_requiring_manual_category()['videos']
            with closing(sqlite3.connect(db_path)) as conn:
                processed_row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_url
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    ('SQTE-241',),
                ).fetchone()
                prefix_row = conn.execute(
                    '''
                    SELECT javtxt_enrichment_status, javtxt_url
                    FROM code_prefix_movies
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('NSPS', 'NSPS-648'),
                ).fetchone()

        self.assertEqual([row['code'] for row in rows], ['ABP-123', 'MIDV-001'])
        self.assertEqual(processed_row, (UNENRICHED_STATUS, ''))
        self.assertEqual(prefix_row, (UNENRICHED_STATUS, ''))


class _StubDatabase:
    def get_javtxt_actor_cache_by_codes(self, codes):
        return {}

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        return 0


class _StubScraper:
    @contextmanager
    def session(self):
        yield None

    def fetch_by_code(self, code):
        return {
            'code': code,
            'found': True,
            'title': 'old movie',
            'javtxt_title': 'old movie',
            'author': '演员A',
            'javtxt_actors': '演员A',
            'javtxt_actors_raw': '演员A',
            'release_date': '2018-05-13',
            'javtxt_tags': '人妻',
            'javtxt_movie_id': '272298',
            'javtxt_url': 'https://javtxt.top/v/272298',
        }


class MovieAuthorResolverEligibilityTest(unittest.TestCase):
    def test_javtxt_result_with_old_release_date_is_downgraded(self):
        resolver = MovieAuthorResolver(_StubDatabase(), scraper=_StubScraper())
        result = resolver.enrich_entries_with_details(
            [
                {
                    'code': 'NSPS-702',
                    'title': 'legacy movie',
                    'author': '',
                    'release_date': '2020-12-22',
                }
            ]
        )

        entry = result['entries'][0]
        self.assertEqual(entry['release_date'], '2018-05-13')
        self.assertEqual(entry['javtxt_enrichment_status'], UNENRICHED_STATUS)
        self.assertEqual(entry['javtxt_movie_id'], '272298')
        self.assertEqual(entry['javtxt_url'], 'https://javtxt.top/v/272298')


if __name__ == '__main__':
    unittest.main()
