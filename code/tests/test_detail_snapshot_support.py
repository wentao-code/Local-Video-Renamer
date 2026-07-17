import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.backend.client import BackendClient
from app.backend.service import BackendService
from app.core.ladder_board import LADDER_BOARD_ACTOR
from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.snapshot_store import SnapshotStore


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
        service.db = type(
            'DatabaseStub',
            (),
            {
                'sync_pending_masterpiece_actor_registrations': lambda self: {
                    'pending_total': 0,
                    'added_count': 0,
                    'failed_count': 0,
                    'failures': [],
                }
            },
        )()
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

    def test_actor_detail_dual_writes_and_reuses_messagepack_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot_file = root / 'legacy' / 'actor_snapshot.json'
            first_service = self._build_service(snapshot_file)
            first_service.snapshot_store = SnapshotStore(root / 'snapshots')
            first_service._current_snapshot_timestamp = lambda: '2026-07-16 12:00:00'
            first_service.get_actor_detail = lambda actor_name: {'actor': {'name': actor_name}}

            first = BackendService.get_actor_detail_snapshot(first_service, 'Alice')

            self.assertFalse(first['cache_hit'])
            self.assertTrue(first_service.snapshot_store.messagepack_path('actor_detail/alice').exists())
            self.assertTrue(first_service.snapshot_store.json_path('actor_detail/alice').exists())

            second_service = self._build_service(snapshot_file)
            second_service.snapshot_store = SnapshotStore(root / 'snapshots')
            second_service.get_actor_detail = lambda _name: (_ for _ in ()).throw(
                AssertionError('should reuse MessagePack actor detail snapshot')
            )

            BackendService._load_actor_snapshots(second_service)
            second = BackendService.get_actor_detail_snapshot(second_service, 'Alice')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['actor']['name'], 'Alice')

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

    def test_blacklisted_actor_detail_snapshot_is_rejected_before_cache(self):
        snapshot_file = Path(tempfile.gettempdir()) / 'actor_snapshot_blacklisted.json'
        service = self._build_service(snapshot_file)
        service.db = type(
            'DatabaseStub',
            (),
            {'is_actor_blacklisted': lambda self, _actor_name: True},
        )()

        with self.assertRaises(ValueError):
            BackendService.get_actor_detail_snapshot(service, 'Hidden Actor')
            self.assertEqual(service._actor_library_snapshots, {})

            BackendService.update_ladder_entry_medal(service, LADDER_BOARD_ACTOR, 'Bob', 'Legend')

            self.assertIn('bob', service._actor_detail_snapshots)

    def test_force_refresh_actor_list_does_not_auto_pre_generate_detail_snapshots(self):
        snapshot_file = Path(tempfile.gettempdir()) / 'actor_snapshot_force_refresh.json'
        service = self._build_service(snapshot_file)
        sync_calls = []
        service.db = type(
            'DatabaseStub',
            (),
            {
                'sync_pending_masterpiece_actor_registrations': lambda self: (
                    sync_calls.append(True)
                    or {'pending_total': 1, 'added_count': 1, 'failed_count': 0, 'failures': []}
                )
            },
        )()
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
        self.assertEqual(sync_calls, [True])

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


class BackendServiceCodePrefixDetailSnapshotTest(unittest.TestCase):
    def test_blacklisted_code_prefix_detail_snapshot_is_rejected_before_cache(self):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.db = type(
            'DatabaseStub',
            (),
            {'is_code_prefix_blacklisted': lambda self, _prefix: True},
        )()

        with self.assertRaises(ValueError):
            BackendService.get_code_prefix_detail_snapshot(service, 'ROE')


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
    def test_refresh_masterpiece_actors_uses_registry_refresh_endpoint(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []
        client._post = lambda path, payload=None, timeout=None: calls.append((path, payload, timeout)) or {
            'blacklisted_count': 1,
            'removed_count': 1,
        }

        result = client.refresh_masterpiece_actors()

        self.assertEqual(result['removed_count'], 1)
        self.assertEqual(calls, [('/masterpiece/actors/refresh', None, None)])

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


class BackendServiceDetailSnapshotRebuildJobTest(unittest.TestCase):
    def test_rebuild_starts_once_and_reuses_running_job(self):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service._detail_snapshot_rebuild_lock = threading.Lock()
        service._detail_snapshot_rebuild_thread = None
        service._detail_snapshot_rebuild_state = {'status': 'idle'}
        service.db = type(
            'DatabaseStub',
            (),
            {
                'sync_pending_masterpiece_actor_registrations': lambda self: {
                    'pending_total': 1,
                    'added_count': 1,
                    'failed_count': 0,
                    'failures': [],
                }
            },
        )()
        started = threading.Event()
        release = threading.Event()
        actor_calls = []

        def rebuild_actors():
            actor_calls.append(True)
            started.set()
            release.wait(2)
            return {'actor_total': 2, 'actor_refreshed': 2, 'actor_failed': 0}

        service._rebuild_actor_detail_snapshots = rebuild_actors
        service._rebuild_code_prefix_detail_snapshots = lambda: {
            'code_prefix_total': 1,
            'code_prefix_refreshed': 1,
            'code_prefix_failed': 0,
        }

        started_at = time.perf_counter()
        first = BackendService.rebuild_detail_snapshots(service)
        elapsed = time.perf_counter() - started_at
        self.assertTrue(started.wait(1))
        second = BackendService.rebuild_detail_snapshots(service)
        release.set()
        service._detail_snapshot_rebuild_thread.join(2)
        completed = BackendService.get_detail_snapshot_rebuild_status(service)

        self.assertLess(elapsed, 0.2)
        self.assertEqual(first['status'], 'running')
        self.assertTrue(second['reused'])
        self.assertEqual(actor_calls, [True])
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['actor_refreshed'], 2)
        self.assertEqual(completed['masterpiece_actor_added'], 1)

    def test_rebuild_detail_snapshots_polls_background_job_without_long_request(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        post_calls = []
        get_calls = []
        statuses = iter(
            [
                {'status': 'running', 'job_id': 'detail-1'},
                {
                    'status': 'completed',
                    'job_id': 'detail-1',
                    'actor_total': 2,
                    'actor_refreshed': 2,
                    'code_prefix_total': 1,
                    'code_prefix_refreshed': 1,
                },
            ]
        )

        def fake_post(path, payload=None, timeout=None):
            post_calls.append((path, payload, timeout))
            return next(statuses)

        def fake_get(path, timeout=None):
            get_calls.append((path, timeout))
            return next(statuses)

        client._post = fake_post
        client._get = fake_get

        result = client.rebuild_detail_snapshots(poll_interval=0)

        self.assertEqual(result['status'], 'completed')
        from app.core.operation_timeout_settings import get_operation_timeout_seconds
        expected_timeout = max(30, get_operation_timeout_seconds('snapshot_refresh_rebuild'))
        self.assertEqual(post_calls, [('/snapshots/details/rebuild', None, expected_timeout)])
        self.assertEqual(get_calls, [('/snapshots/details/rebuild/status', expected_timeout)])

    def test_enrich_masterpiece_detail_uses_long_timeout_for_two_browser_sources(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_post(path, payload=None, timeout=None):
            calls.append((path, payload, timeout))
            return {'detail': {'code': 'ALDN-514'}, 'enrichment_results': []}

        client._post = fake_post

        result = client.enrich_masterpiece_detail('ALDN-514')

        self.assertEqual(result['detail']['code'], 'ALDN-514')
        expected_timeout = max(30, get_operation_timeout_seconds('snapshot_refresh_rebuild'))
        self.assertEqual(calls, [('/masterpiece/detail/enrich', {'code': 'ALDN-514'}, expected_timeout)])


if __name__ == '__main__':
    unittest.main()
