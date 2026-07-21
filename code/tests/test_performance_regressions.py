import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS
from app.data.database_handler import VideoDatabase
from app.services.library import DataCenterService
from app.services.library.actor_library_sync_service import ActorLibrarySyncService


class VideoLibraryReadPathRegressionTest(unittest.TestCase):
    def test_list_videos_does_not_refresh_categories_on_plain_library_read(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO video_entities (
                        code, title, author, release_date,
                        avfan_enrichment_status, javtxt_enrichment_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    ('AAA-001', 'Video A', 'Actor A', '2024-01-01', ENRICHED_STATUS, ENRICHED_STATUS),
                )
                conn.execute(
                    "INSERT INTO local_video_records (code, storage_location) VALUES (?, ?)",
                    ('AAA-001', 'Local folder'),
                )
                conn.commit()

            with patch.object(db, 'refresh_video_categories_from_filter_rules', side_effect=AssertionError('unexpected refresh')):
                rows = db.list_videos()

            self.assertEqual([row['code'] for row in rows], ['AAA-001'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class ActorSyncRegressionTest(unittest.TestCase):
    def test_actor_sync_uses_video_summary_rows_not_full_video_listing(self):
        class FakeIdentifier:
            @staticmethod
            def identify_from_author_text(author_text):
                return [{'name': author_text, 'birthday': '', 'age': '', 'matched': True}]

        class FakeDatabase:
            def __init__(self):
                self.inserted = None

            def list_video_summary_rows(self):
                return [
                    {'author': 'Actor A'},
                    {'author': 'Actor B'},
                ]

            def list_videos(self):
                raise AssertionError('unexpected full video listing')

            def insert_missing_actors(self, actors):
                self.inserted = list(actors)
                return len(actors)

        database = FakeDatabase()
        service = ActorLibrarySyncService(database, actor_identifier=FakeIdentifier())

        created_count = service.sync_from_video_library()

        self.assertEqual(created_count, 2)
        self.assertEqual([row['name'] for row in database.inserted], ['Actor A', 'Actor B'])


class DataCenterJavtxtSummaryRegressionTest(unittest.TestCase):
    def test_actor_javtxt_summary_does_not_summarize_each_movie_individually(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [('Actor A',), ('Actor B',)],
                )
                conn.commit()

            shared_movies = [
                {
                    'code': 'AAA-001',
                    'title': 'Movie 1',
                    'author': '',
                    'author_raw': '',
                    'release_date': '2024-01-01',
                    'avfan_url': '',
                    'page_number': 1,
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                    'javtxt_movie_id': 'm1',
                    'javtxt_url': 'https://example.com/1',
                    'javtxt_tags': '',
                    'javtxt_release_date': '2024-01-01',
                    'video_category': '',
                },
                {
                    'code': 'AAA-002',
                    'title': 'Movie 2',
                    'author': '',
                    'author_raw': '',
                    'release_date': '2024-01-02',
                    'avfan_url': '',
                    'page_number': 1,
                    'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                    'javtxt_movie_id': '',
                    'javtxt_url': '',
                    'javtxt_tags': '',
                    'javtxt_release_date': '2024-01-02',
                    'video_category': '',
                },
            ]
            db.replace_actor_movies('Actor A', shared_movies)
            db.replace_actor_movies('Actor B', shared_movies)

            original_summarize = __import__('app.services.library.data_center_service', fromlist=['summarize_javtxt_movies']).summarize_javtxt_movies

            def guarded_summarize(movies, cache_rows=None):
                if len(list(movies or [])) == 1:
                    raise AssertionError('single-movie summarize should not be used in actor JAVTXT summary')
                return original_summarize(movies, cache_rows=cache_rows)

            with patch('app.services.library.data_center_service.summarize_javtxt_movies', side_effect=guarded_summarize):
                summary = DataCenterService(db).get_summary_snapshot()['summary']

            actor_summary = summary['actor_library']['sources']['javtxt']
            self.assertEqual(actor_summary['total_count'], 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class DataCenterJavtxtFilterReuseRegressionTest(unittest.TestCase):
    def test_actor_javtxt_summary_filters_grouped_movies_only_once(self):
        class FakeDatabase:
            @staticmethod
            def list_actors():
                return [{'name': 'Actor A'}]

            @staticmethod
            def list_actor_movies_by_names(actor_names):
                return {
                    'Actor A': [
                        {
                            'code': 'AAA-001',
                            'title': 'Movie 1',
                            'author': 'Actor A',
                            'author_raw': 'Actor A',
                            'release_date': '2024-01-01',
                            'avfan_url': '',
                            'page_number': 1,
                            'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                            'javtxt_movie_id': '',
                            'javtxt_url': '',
                            'javtxt_tags': '',
                            'javtxt_release_date': '2024-01-01',
                            'video_category': '',
                        }
                    ]
                }

            @staticmethod
            def get_javtxt_actor_cache_by_codes(codes):
                return {}

            @staticmethod
            def list_video_summary_rows():
                return []

        class FakeFilterService:
            def __init__(self):
                self.calls = 0

            @staticmethod
            def load_settings():
                return {'rules': {'code': [], 'title': [], 'javtxt_tags': [], 'co_star_code': []}}

            def filter_video_rows(self, rows, settings=None):
                self.calls += 1
                return list(rows or [])

        filter_service = FakeFilterService()
        service = DataCenterService(FakeDatabase(), video_filter_service=filter_service)

        summary = service._build_actor_source_summary('javtxt', filter_settings=filter_service.load_settings())

        self.assertEqual(summary['total_count'], 1)
        self.assertEqual(filter_service.calls, 1)

    def test_actor_javtxt_summary_reuses_merged_movies_for_issue_groups(self):
        class FakeDatabase:
            @staticmethod
            def list_actors():
                return [{'name': 'Actor A'}]

            @staticmethod
            def list_actor_movies_by_names(actor_names):
                return {
                    'Actor A': [
                        {
                            'code': 'AAA-001',
                            'title': 'Movie 1',
                            'author': 'Actor A',
                            'author_raw': 'Actor A',
                            'release_date': '2024-01-01',
                            'avfan_url': '',
                            'page_number': 1,
                            'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
                            'javtxt_movie_id': '',
                            'javtxt_url': '',
                            'javtxt_tags': '',
                            'javtxt_release_date': '2024-01-01',
                            'video_category': '',
                        }
                    ]
                }

            @staticmethod
            def get_javtxt_actor_cache_by_codes(codes):
                return {}

            @staticmethod
            def list_video_summary_rows():
                return []

        service = DataCenterService(FakeDatabase(), video_filter_service=None)
        original_merge = service._merge_movies_by_code

        with patch.object(service, '_merge_movies_by_code', wraps=original_merge) as merge_mock:
            summary = service._build_actor_source_summary('javtxt', filter_settings=None)

        self.assertEqual(summary['total_count'], 1)
        self.assertEqual(merge_mock.call_count, 1)


class DataCenterSummaryBuildCacheRegressionTest(unittest.TestCase):
    def test_summary_build_reuses_large_library_reads_within_one_refresh(self):
        movie = {
            'code': 'AAA-001',
            'title': 'Movie 1',
            'author': 'Actor A',
            'author_raw': 'Actor A',
            'release_date': '2024-01-01',
            'avfan_enrichment_status': ENRICHED_STATUS,
            'javtxt_enrichment_status': NO_SEARCH_RESULTS_STATUS,
            'javtxt_movie_id': '',
            'javtxt_url': '',
            'javtxt_tags': '',
            'javtxt_release_date': '2024-01-01',
            'video_category': '',
        }

        class FakeDatabase:
            def __init__(self):
                self.calls = {
                    'list_video_summary_rows': 0,
                    'list_actors': 0,
                    'list_actor_movies_by_names': 0,
                    'list_code_prefix_movies_by_prefixes': 0,
                }

            def list_video_summary_rows(self):
                self.calls['list_video_summary_rows'] += 1
                return [dict(movie)]

            def list_actors(self):
                self.calls['list_actors'] += 1
                return [{'name': 'Actor A'}]

            def list_actor_movies_by_names(self, actor_names):
                self.calls['list_actor_movies_by_names'] += 1
                return {'Actor A': [dict(movie)]}

            def list_code_prefix_movies_by_prefixes(self, prefixes):
                self.calls['list_code_prefix_movies_by_prefixes'] += 1
                return {'AAA': [dict(movie)]}

            @staticmethod
            def list_actor_enrichment_records():
                return {'Actor A': {'avfan_enrichment_status': ENRICHED_STATUS}}

            @staticmethod
            def list_code_prefix_enrichment_records():
                return {'AAA': {'avfan_enrichment_status': ENRICHED_STATUS}}

            @staticmethod
            def get_javtxt_actor_cache_by_codes(codes):
                return {}

        class FakePrefixLibrary:
            def __init__(self):
                self.calls = 0

            def list_prefixes(self):
                self.calls += 1
                return [{'prefix': 'AAA'}]

        class FakeFilterService:
            @staticmethod
            def load_settings():
                return {'rules': {'code': [], 'title': [], 'javtxt_tags': [], 'co_star_code': []}}

            @staticmethod
            def filter_video_rows(rows, settings=None):
                return list(rows or [])

        database = FakeDatabase()
        prefix_library = FakePrefixLibrary()
        service = DataCenterService(database, video_filter_service=FakeFilterService())
        service.code_prefix_library = prefix_library

        summary = service.get_summary_snapshot(force_refresh=True)['summary']

        self.assertIn('video_library', summary)
        self.assertEqual(database.calls['list_video_summary_rows'], 1)
        self.assertEqual(prefix_library.calls, 1)
        self.assertEqual(database.calls['list_actors'], 1)
        self.assertEqual(database.calls['list_actor_movies_by_names'], 1)
        self.assertEqual(database.calls['list_code_prefix_movies_by_prefixes'], 1)


class StartupMaintenancePersistenceRegressionTest(unittest.TestCase):
    def test_startup_maintenance_is_skipped_after_it_is_marked_complete(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            first_db = VideoDatabase(db_path)
            with patch.object(VideoDatabase, '_run_startup_maintenance', autospec=True) as run_mock:
                first_db.ensure_startup_maintenance()
                self.assertEqual(run_mock.call_count, 1)

            reopened_db = VideoDatabase(db_path)
            with patch.object(VideoDatabase, '_run_startup_maintenance', autospec=True) as run_mock:
                reopened_db.ensure_startup_maintenance()
                self.assertEqual(run_mock.call_count, 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
