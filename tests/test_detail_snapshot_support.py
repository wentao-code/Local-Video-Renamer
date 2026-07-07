import tempfile
import unittest
from pathlib import Path

from app.backend.client import BackendClient
from app.backend.service import BackendService


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


if __name__ == '__main__':
    unittest.main()
