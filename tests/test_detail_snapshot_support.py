import tempfile
import unittest
from pathlib import Path

from app.backend.client import BackendClient
from app.backend.service import BackendService
from app.core.ladder_board import LADDER_BOARD_ACTOR


class _FilterServiceStub:
    def __init__(self, settings=None):
        self._settings = dict(settings or {})

    def load_settings(self):
        return dict(self._settings)


class BackendServiceActorDetailSnapshotTest(unittest.TestCase):
    def _build_service(self, snapshot_file, filter_settings=None):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.video_filter_service = _FilterServiceStub(filter_settings)
        service._snapshot_lock = None
        service._actor_snapshot_file_lock = None
        service._actor_library_snapshots = {}
        service._actor_detail_snapshots = {}
        service._actor_snapshot_file = Path(snapshot_file)
        service._actor_detail_snapshot_dir = Path(snapshot_file).parent / 'actor_detail'
        service._actor_snapshot_filter_fingerprint = BackendService._build_actor_snapshot_filter_fingerprint(
            filter_settings
        )
        return service

    def test_detail_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'actor_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-07 10:00:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.get_actor_detail = lambda actor_name: {
                'actor': {
                    'name': actor_name,
                    'actor_id': 'avfan-7',
                }
            }

            first = BackendService.get_actor_detail_snapshot(first_service, 'Alice')

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-07 10:00:00')

            second_service = self._build_service(snapshot_file)
            second_service.get_actor_detail = lambda actor_name: (_ for _ in ()).throw(
                AssertionError('should reuse persisted actor detail snapshot')
            )
            BackendService._load_actor_snapshots(second_service)

            second = BackendService.get_actor_detail_snapshot(second_service, 'Alice')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-07 10:00:00')
            self.assertEqual(second['actor']['name'], 'Alice')
            self.assertTrue((Path(temp_dir) / 'actor_detail' / 'alice.json').exists())

    def test_directory_detail_snapshot_is_reused_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'actor_snapshot.json'
            detail_dir = Path(temp_dir) / 'actor_detail'
            detail_dir.mkdir(parents=True, exist_ok=True)
            (detail_dir / 'alice.json').write_text(
                """
{
  "actor": {"name": "Alice"},
  "refreshed_at": "2026-07-07 10:00:00",
  "refresh_duration_ms": 9,
  "refresh_duration_text": "9ms"
}
                """.strip(),
                encoding='utf-8',
            )
            service = self._build_service(snapshot_file)
            service.get_actor_detail = lambda actor_name: (_ for _ in ()).throw(
                AssertionError('should reuse actor detail snapshot file')
            )

            BackendService._load_actor_snapshots(service)
            second = BackendService.get_actor_detail_snapshot(service, 'Alice')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['actor']['name'], 'Alice')

    def test_legacy_detail_snapshots_migrate_into_actor_detail_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'actor_snapshot.json'
            snapshot_file.write_text(
                """
{
  "version": 1,
  "filter_settings_fingerprint": "{}",
  "library_snapshots": {},
  "detail_snapshots": {
    "alice": {
      "actor": {"name": "Alice"},
      "refreshed_at": "2026-07-07 10:00:00",
      "refresh_duration_ms": 12,
      "refresh_duration_text": "12ms"
    }
  }
}
                """.strip(),
                encoding='utf-8',
            )
            service = self._build_service(snapshot_file)

            BackendService._load_actor_snapshots(service)

            self.assertIn('alice', service._actor_detail_snapshots)
            self.assertTrue((Path(temp_dir) / 'actor_detail' / 'alice.json').exists())

    def test_actor_ladder_updates_do_not_clear_unrelated_detail_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'actor_snapshot.json'
            service = self._build_service(snapshot_file)
            service._actor_library_snapshots = {'list': {'actors': [], 'refreshed_at': '2026-07-07 10:00:00'}}
            service._actor_detail_snapshots = {
                'alice': {'actor': {'name': 'Alice'}, 'refreshed_at': '2026-07-07 10:00:00'},
                'bob': {'actor': {'name': 'Bob'}, 'refreshed_at': '2026-07-07 10:00:00'},
            }
            service.ladder_board_service = type(
                'LadderBoardStub',
                (),
                {
                    'admit_entry': lambda _self, board_key, entity_name, tier: {'board_key': board_key},
                    'update_medal': lambda _self, board_key, entity_name, medal: {'board_key': board_key},
                },
            )()
            service._store_ladder_board_snapshot = lambda board_key, board: board

            BackendService.admit_ladder_entry(service, LADDER_BOARD_ACTOR, 'Alice', 'S')

            self.assertNotIn('alice', service._actor_detail_snapshots)
            self.assertIn('bob', service._actor_detail_snapshots)
            self.assertEqual(service._actor_library_snapshots, {})

            BackendService.update_ladder_entry_medal(service, LADDER_BOARD_ACTOR, 'Bob', 'Legend')

            self.assertIn('bob', service._actor_detail_snapshots)

    def test_force_refresh_actor_list_does_not_auto_pre_generate_detail_snapshots(self):
        snapshot_file = Path(tempfile.gettempdir()) / 'actor_snapshot_force_refresh.json'
        service = self._build_service(snapshot_file)
        service.list_actors = lambda *args, **kwargs: {
            'actors': [{'name': 'Alice'}],
            'total_count': 1,
            'offset': 0,
            'limit': None,
        }
        service._current_snapshot_timestamp = lambda: '2026-07-07 10:00:00'
        service._append_snapshot_refresh_log = lambda **kwargs: None
        service._pre_generate_all_actor_detail_snapshots = lambda: (_ for _ in ()).throw(
            AssertionError('should not auto pre-generate actor detail snapshots')
        )

        result = BackendService.list_actors_snapshot(service, force_refresh=True)

        self.assertFalse(result['cache_hit'])

    def test_background_actor_snapshot_can_skip_update_status(self):
        snapshot_file = Path(tempfile.gettempdir()) / 'actor_snapshot_lightweight_refresh.json'
        service = self._build_service(snapshot_file)
        calls = []

        def list_actors(*args, **kwargs):
            calls.append(kwargs)
            return {
                'actors': [{'name': 'Alice'}],
                'total_count': 1,
                'offset': 0,
                'limit': None,
            }

        service.list_actors = list_actors
        service._current_snapshot_timestamp = lambda: '2026-07-07 10:00:00'
        service._append_snapshot_refresh_log = lambda **kwargs: None

        result = BackendService.list_actors_snapshot(service, force_refresh=True, include_update_status=False)

        self.assertFalse(result['cache_hit'])
        self.assertEqual(calls[-1]['include_update_status'], False)

    def test_actor_detail_snapshot_file_uses_safe_encoded_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'actor_snapshot.json'
            service = self._build_service(snapshot_file)
            service._current_snapshot_timestamp = lambda: '2026-07-07 10:00:00'
            service.get_actor_detail = lambda actor_name: {'actor': {'name': actor_name}}

            BackendService.get_actor_detail_snapshot(service, 'A/B:C?')

            self.assertTrue((Path(temp_dir) / 'actor_detail' / 'a%2Fb%3Ac%3F.json').exists())


class BackendServiceMasterpieceDetailSnapshotTest(unittest.TestCase):
    def _build_service(self, snapshot_file):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service._snapshot_lock = None
        service._masterpiece_snapshot_file_lock = None
        service._masterpiece_snapshot_file = Path(snapshot_file)
        service._masterpiece_detail_snapshots = {}
        return service

    def test_detail_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'masterpiece_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-07 10:05:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.get_masterpiece_detail = lambda code: {
                'detail': {
                    'code': code,
                    'display_title': 'Perfect First Scene',
                }
            }

            first = BackendService.get_masterpiece_detail_snapshot(first_service, 'PFSA-001')

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-07 10:05:00')

            second_service = self._build_service(snapshot_file)
            second_service.get_masterpiece_detail = lambda code: (_ for _ in ()).throw(
                AssertionError('should reuse persisted masterpiece detail snapshot')
            )
            BackendService._load_masterpiece_snapshots(second_service)

            second = BackendService.get_masterpiece_detail_snapshot(second_service, 'PFSA-001')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-07 10:05:00')
            self.assertEqual(second['detail']['code'], 'PFSA-001')


class BackendClientDetailSnapshotTest(unittest.TestCase):
    def test_list_actor_snapshot_can_request_lightweight_update_status(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'actors': [], 'refreshed_at': '2026-07-07 10:08:00'}

        client._get = fake_get

        result = client.list_actors_snapshot(force_refresh=True, include_update_status=False)

        self.assertEqual(result['refreshed_at'], '2026-07-07 10:08:00')
        self.assertEqual(calls, [('/database/actors?refresh=1&update_status=0', 120)])

    def test_get_actor_detail_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'actor': {'name': 'Alice'}, 'refreshed_at': '2026-07-07 10:10:00'}

        client._get = fake_get

        result = client.get_actor_detail_snapshot('Alice', force_refresh=True)

        self.assertEqual(result['actor']['name'], 'Alice')
        self.assertEqual(
            calls,
            [('/database/actors/detail?name=Alice&refresh=1', 120)],
        )

    def test_get_masterpiece_detail_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'detail': {'code': 'PFSA-001'}, 'refreshed_at': '2026-07-07 10:15:00'}

        client._get = fake_get

        result = client.get_masterpiece_detail_snapshot('PFSA-001', force_refresh=True)

        self.assertEqual(result['detail']['code'], 'PFSA-001')
        self.assertEqual(
            calls,
            [('/masterpiece/detail?code=PFSA-001&refresh=1', 120)],
        )

    def test_rebuild_detail_snapshots_uses_twenty_minute_timeout(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_post(path, payload=None, timeout=None):
            calls.append((path, payload, timeout))
            return {'success': True}

        client._post = fake_post

        result = client.rebuild_detail_snapshots()

        self.assertTrue(result['success'])
        self.assertEqual(calls, [('/snapshots/details/rebuild', None, 1200)])


if __name__ == '__main__':
    unittest.main()
