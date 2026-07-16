import tempfile
import unittest
from pathlib import Path

from app.backend.service import BackendService
from app.core.snapshot_store import SnapshotStore


class _CandidateService:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error

    def list_candidates(self):
        if self.error:
            raise self.error
        return list(self.rows)


class PageSnapshotPersistenceTest(unittest.TestCase):
    @staticmethod
    def _base_service(root):
        service = BackendService.__new__(BackendService)
        service.snapshot_store = SnapshotStore(Path(root) / 'snapshots')
        service._snapshot_lock = None
        service._canglangge_snapshot_lock = None
        service._canglangge_snapshot = None
        service._ladder_board_snapshots = {}
        service._path_library_snapshot = None
        service.ensure_database_loaded = lambda: None
        service._current_snapshot_timestamp = lambda: '2026-07-16 13:00:00'
        service._append_snapshot_refresh_log = lambda **_kwargs: None
        return service

    def test_canglangge_snapshot_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service.canglangge_candidate_service = _CandidateService(
                [{'actor_name': 'Alice'}]
            )

            first = BackendService.list_canglangge_candidates(first_service)

            second_service = self._base_service(temp_dir)
            second_service.canglangge_candidate_service = _CandidateService(
                error=AssertionError('should reuse persisted Canglangge snapshot')
            )
            second = BackendService.list_canglangge_candidates(second_service)

            self.assertEqual(first['candidates'], second['candidates'])
            self.assertTrue(second_service.snapshot_store.messagepack_path('canglangge/index').exists())
            self.assertTrue(second_service.snapshot_store.json_path('canglangge/index').exists())

    def test_ladder_and_path_snapshots_survive_service_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service.ladder_board_service = type(
                'LadderStub',
                (),
                {'get_board': lambda _self, key: {'board_key': key, 'entries': []}},
            )()
            first_service.path_library = type(
                'PathStub',
                (),
                {'with_exists_status': lambda _self, row: dict(row)},
            )()
            first_service.db = type('DatabaseStub', (), {'list_paths': lambda _self: [{'id': 1, 'path': 'D:/A'}]})()

            first_board = BackendService.get_ladder_board(first_service, 'actor')
            first_paths = BackendService.list_paths(first_service)

            second_service = self._base_service(temp_dir)
            second_service.ladder_board_service = type(
                'LadderStub',
                (),
                {'get_board': lambda _self, _key: (_ for _ in ()).throw(AssertionError('ladder cache miss'))},
            )()
            second_service.path_library = type(
                'PathStub',
                (),
                {'with_exists_status': lambda _self, row: dict(row)},
            )()
            second_service.db = type(
                'DatabaseStub',
                (),
                {'list_paths': lambda _self: (_ for _ in ()).throw(AssertionError('path cache miss'))},
            )()

            self.assertEqual(BackendService.get_ladder_board(second_service, 'actor'), first_board)
            self.assertEqual(BackendService.list_paths(second_service), first_paths)

    def test_direct_query_pages_use_persisted_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service.db = type(
                'DatabaseStub',
                (),
                {
                    'list_masterpiece_entries': lambda _self: [{'code': 'SDDE-714'}],
                    'list_global_medals': lambda _self: [{'name': 'Legend'}],
                },
            )()
            first_service.queen_library_service = type(
                'QueenStub',
                (),
                {
                    'list_queens': lambda _self: [{'queen_name': 'Alice'}],
                    'list_keywords': lambda _self: [{'keyword': 'Alice'}],
                    'get_library_stats': lambda _self: {'queen_count': 1},
                    'get_queen_detail': lambda _self, name: {'queen': {'queen_name': name}},
                },
            )()

            expected = {
                'masterpiece': BackendService.list_masterpiece_entries(first_service),
                'medals': BackendService.list_global_medals(first_service),
                'queens': BackendService.list_queen_library_snapshot(first_service),
                'keywords': BackendService.list_queen_keywords_snapshot(first_service),
                'detail': BackendService.get_queen_detail_snapshot(first_service, 'Alice'),
            }

            second_service = self._base_service(temp_dir)
            failure = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('page cache miss'))
            second_service.db = type(
                'DatabaseStub',
                (),
                {'list_masterpiece_entries': failure, 'list_global_medals': failure},
            )()
            second_service.queen_library_service = type(
                'QueenStub',
                (),
                {
                    'list_queens': failure,
                    'list_keywords': failure,
                    'get_library_stats': failure,
                    'get_queen_detail': failure,
                },
            )()

            self.assertEqual(BackendService.list_masterpiece_entries(second_service), expected['masterpiece'])
            self.assertEqual(BackendService.list_global_medals(second_service), expected['medals'])
            self.assertEqual(BackendService.list_queen_library_snapshot(second_service), expected['queens'])
            self.assertEqual(BackendService.list_queen_keywords_snapshot(second_service), expected['keywords'])
            self.assertEqual(BackendService.get_queen_detail_snapshot(second_service, 'Alice'), expected['detail'])

    def test_candidate_modes_are_persisted_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service.candidate_library_service = type(
                'CandidateStub',
                (),
                {
                    'list_actor_candidates': lambda _self, limit=50: [{'actor_name': 'Alice'}],
                    'list_code_prefix_candidates': lambda _self, limit=50: [{'prefix': 'SDDE'}],
                },
            )()
            first_service._sync_persisted_code_filter_blacklist = lambda: None

            actors = BackendService.list_candidate_actors(first_service)
            prefixes = BackendService.list_candidate_code_prefixes(first_service)

            second_service = self._base_service(temp_dir)
            failure = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('candidate cache miss'))
            second_service.candidate_library_service = type(
                'CandidateStub',
                (),
                {'list_actor_candidates': failure, 'list_code_prefix_candidates': failure},
            )()
            second_service._sync_persisted_code_filter_blacklist = lambda: None

            self.assertEqual(BackendService.list_candidate_actors(second_service), actors)
            self.assertEqual(BackendService.list_candidate_code_prefixes(second_service), prefixes)

    def test_video_library_query_page_is_persisted_by_query_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service.video_filter_service = type(
                'FilterStub',
                (),
                {
                    'load_ruleset': lambda _self, scope='library': None,
                    'load_settings': lambda _self: {},
                    'filter_video_rows': lambda _self, rows: list(rows),
                },
            )()
            first_service.video_ladder_tag_service = type('LadderTagStub', (), {})()
            first_service._list_videos_query = lambda *args, **kwargs: [{'code': 'SDDE-714'}]
            first_service._count_videos_for_listing = lambda *args, **kwargs: 1

            first = BackendService.list_videos(first_service, limit=200)

            second_service = self._base_service(temp_dir)
            second_service.video_filter_service = first_service.video_filter_service
            second_service.video_ladder_tag_service = first_service.video_ladder_tag_service
            second_service._list_videos_query = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError('video page cache miss')
            )
            second_service._count_videos_for_listing = lambda *args, **kwargs: 1

            second = BackendService.list_videos(second_service, limit=200)

            self.assertEqual(second, first)
            self.assertTrue(second_service.snapshot_store.iter_keys('video_library'))

    def test_masterpiece_details_are_persisted_independently_by_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_service = self._base_service(temp_dir)
            first_service._masterpiece_detail_snapshots = {}
            first_service.get_masterpiece_detail = lambda code: {
                'detail': {'code': code, 'display_title': 'Independent detail'}
            }

            first = BackendService.get_masterpiece_detail_snapshot(first_service, 'SDDE-714')

            second_service = self._base_service(temp_dir)
            second_service._masterpiece_detail_snapshots = {}
            second_service.get_masterpiece_detail = lambda _code: (_ for _ in ()).throw(
                AssertionError('masterpiece detail snapshot cache miss')
            )
            second = BackendService.get_masterpiece_detail_snapshot(second_service, 'SDDE-714')

            key = 'masterpiece/detail/SDDE-714'
            self.assertEqual(second['detail'], first['detail'])
            self.assertTrue(second['cache_hit'])
            self.assertTrue(second_service.snapshot_store.messagepack_path(key).exists())
            self.assertTrue(second_service.snapshot_store.json_path(key).exists())


if __name__ == '__main__':
    unittest.main()
