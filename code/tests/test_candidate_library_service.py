import tempfile
import threading
import unittest
from pathlib import Path

from app.backend.service import BackendService
from app.data.database_handler import VideoDatabase
from app.services.library.candidate_library_service import CandidateLibraryService


class CandidateLibraryServiceTest(unittest.TestCase):
    def test_listing_candidates_reads_persisted_records_without_rebuilding(self):
        class FakeDatabase:
            def list_candidate_actor_records(self, limit=50):
                return [{'actor_name': '缓存演员', 'video_count': 7}]

            def list_candidate_code_prefix_records(self, limit=50):
                return [{'prefix': 'CACHE', 'video_count': 5}]

            def list_actors(self):
                raise AssertionError('读取候选列表不应重建候选库')

        service = CandidateLibraryService(FakeDatabase())

        self.assertEqual(service.list_actor_candidates(), [{'actor_name': '缓存演员', 'video_count': 7}])
        self.assertEqual(service.list_code_prefix_candidates(), [{'prefix': 'CACHE', 'video_count': 5}])

    def test_concurrent_refresh_reuses_the_in_progress_result(self):
        class FakeDatabase:
            def __init__(self):
                self.build_started = threading.Event()
                self.allow_build = threading.Event()
                self.actor_build_count = 0
                self.actor_records = []
                self.code_prefix_records = []

            def list_actors(self):
                self.actor_build_count += 1
                self.build_started.set()
                self.allow_build.wait(timeout=2)
                return []

            def list_hidden_actors(self):
                return set()

            def list_all_code_prefix_movies(self):
                return []

            def list_code_prefix_summaries(self):
                return []

            def list_hidden_code_prefixes(self):
                return set()

            def list_all_actor_movies(self):
                return []

            def replace_candidate_actor_records(self, rows):
                self.actor_records = list(rows)

            def replace_candidate_code_prefix_records(self, rows):
                self.code_prefix_records = list(rows)

        database = FakeDatabase()
        service = CandidateLibraryService(database)
        results = []

        first = threading.Thread(target=lambda: results.append(service.refresh_candidates()))
        second = threading.Thread(target=lambda: results.append(service.refresh_candidates()))
        first.start()
        self.assertTrue(database.build_started.wait(timeout=1))
        second.start()
        database.allow_build.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(database.actor_build_count, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(result['refresh_reused'] for result in results), [False, True])

    def test_failed_refresh_releases_the_refresh_guard(self):
        class FakeDatabase:
            def list_actors(self):
                raise RuntimeError('数据库读取失败')

        service = CandidateLibraryService(FakeDatabase())

        with self.assertRaisesRegex(RuntimeError, '数据库读取失败'):
            service.refresh_candidates()

        self.assertFalse(service._refresh_running)

    def test_database_persists_actor_and_code_prefix_candidate_records_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'candidates.db')
            database.replace_candidate_actor_records([{'actor_name': 'Actor B', 'video_count': 12}])
            database.replace_candidate_code_prefix_records([{'prefix': 'BBB', 'video_count': 9}])

            self.assertEqual(
                database.list_candidate_actor_records(),
                [{'actor_name': 'Actor B', 'video_count': 12}],
            )
            self.assertEqual(
                database.list_candidate_code_prefix_records(),
                [{'prefix': 'BBB', 'video_count': 9}],
            )

            database.delete_candidate_actor_record('Actor B')
            database.delete_candidate_code_prefix_record('bbb')

            self.assertEqual(database.list_candidate_actor_records(), [])
            self.assertEqual(database.list_candidate_code_prefix_records(), [])

    def test_refresh_records_sorted_candidates_and_excludes_library_and_hidden_items(self):
        class FakeDatabase:
            def __init__(self):
                self.actor_records = []
                self.code_prefix_records = []

            def list_actors(self):
                return [{'name': '演员甲'}]

            def list_hidden_actors(self):
                return {'演员丙'}

            def list_all_code_prefix_movies(self):
                return [
                    {'code': 'AAA-001', 'author': '演员甲 演员乙'},
                    {'code': 'AAA-002', 'author': '演员乙'},
                    {'code': 'BBB-001', 'author': '演员丙'},
                ]

            def list_code_prefix_summaries(self):
                return [{'prefix': 'AAA'}]

            def list_hidden_code_prefixes(self):
                return {'CCC'}

            def list_all_actor_movies(self):
                return [
                    {'actor_name': '演员甲', 'code': 'AAA-001'},
                    {'actor_name': '演员甲', 'code': 'BBB-001'},
                    {'actor_name': '演员乙', 'code': 'BBB-001'},
                    {'actor_name': '演员乙', 'code': 'BBB-002'},
                    {'actor_name': '演员甲', 'code': 'CCC-001'},
                ]

            def replace_candidate_actor_records(self, rows):
                self.actor_records = [dict(row) for row in rows]

            def replace_candidate_code_prefix_records(self, rows):
                self.code_prefix_records = [dict(row) for row in rows]

        database = FakeDatabase()

        result = CandidateLibraryService(database).refresh_candidates()

        self.assertEqual(
            result['actor_candidates'],
            [{'actor_name': '演员乙', 'video_count': 2}],
        )
        self.assertEqual(
            result['code_prefix_candidates'],
            [{'prefix': 'BBB', 'video_count': 2}],
        )
        self.assertEqual(database.actor_records, result['actor_candidates'])
        self.assertEqual(database.code_prefix_records, result['code_prefix_candidates'])


class BackendServiceCandidateLibraryTest(unittest.TestCase):
    def test_list_candidate_actors_only_reads_cached_candidates(self):
        class FakeCandidateService:
            def list_actor_candidates(self, limit=50):
                return [{'actor_name': '缓存演员', 'video_count': 7}]

            def refresh_candidates(self):
                raise AssertionError('读取候选列表不应触发刷新')

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.candidate_library_service = FakeCandidateService()

        self.assertEqual(
            BackendService.list_candidate_actors(service),
            {'candidates': [{'actor_name': '缓存演员', 'video_count': 7}]},
        )

    def test_refresh_candidate_library_delegates_to_candidate_service(self):
        class FakeCandidateService:
            def refresh_candidates(self):
                return {'actor_count': 2, 'code_prefix_count': 3, 'refresh_reused': False}

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.candidate_library_service = FakeCandidateService()

        self.assertEqual(
            BackendService.refresh_candidate_library(service),
            {'actor_count': 2, 'code_prefix_count': 3, 'refresh_reused': False},
        )
    def test_admit_candidate_actor_reuses_library_add_and_removes_candidate_record(self):
        class FakeDatabase:
            def __init__(self):
                self.deleted_names = []

            def delete_candidate_actor_record(self, actor_name):
                self.deleted_names.append(actor_name)
                return 1

        class FakeAdminService:
            def __init__(self):
                self.added = []

            def add_actor(self, actor_name, birthday='', age=''):
                self.added.append((actor_name, birthday, age))
                return 1

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.db = FakeDatabase()
        service.library_admin_service = FakeAdminService()
        service._invalidate_actor_snapshots = lambda: None

        result = BackendService.admit_candidate_actor(service, 'Actor B')

        self.assertEqual(result, {'created_count': 1})
        self.assertEqual(service.library_admin_service.added, [('Actor B', '', '')])
        self.assertEqual(service.db.deleted_names, ['Actor B'])

    def test_admit_candidate_code_prefix_reuses_library_add_and_removes_candidate_record(self):
        class FakeDatabase:
            def __init__(self):
                self.deleted_prefixes = []

            def delete_candidate_code_prefix_record(self, prefix):
                self.deleted_prefixes.append(prefix)
                return 1

        class FakeAdminService:
            def __init__(self):
                self.added = []

            def add_code_prefix(self, prefix):
                self.added.append(prefix)
                return 1

        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.db = FakeDatabase()
        service.library_admin_service = FakeAdminService()
        service._invalidate_code_prefix_snapshots = lambda: None

        result = BackendService.admit_candidate_code_prefix(service, 'bbb')

        self.assertEqual(result, {'created_count': 1})
        self.assertEqual(service.library_admin_service.added, ['BBB'])
        self.assertEqual(service.db.deleted_prefixes, ['BBB'])


if __name__ == '__main__':
    unittest.main()
