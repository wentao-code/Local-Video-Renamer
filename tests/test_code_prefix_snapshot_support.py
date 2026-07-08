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


class BackendServiceCodePrefixSnapshotTest(unittest.TestCase):
    def _build_service(self, snapshot_file, filter_settings=None):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.video_filter_service = _FilterServiceStub(filter_settings)
        service._snapshot_lock = None
        service._code_prefix_snapshot_file_lock = None
        service._code_prefix_library_snapshots = {}
        service._code_prefix_detail_snapshots = {}
        service._code_prefix_snapshot_file = Path(snapshot_file)
        service._code_prefix_detail_snapshot_dir = Path(snapshot_file).parent / 'code_prefix_detail'
        service._code_prefix_snapshot_filter_fingerprint = BackendService._build_code_prefix_snapshot_filter_fingerprint(
            filter_settings
        )
        return service

    def test_list_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-06 13:00:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.list_code_prefixes = lambda *args, **kwargs: {
                'prefixes': [{'prefix': 'ADN', 'video_count': 8}],
                'total_count': 1,
                'offset': 0,
                'limit': 200,
            }

            first = BackendService.list_code_prefixes_snapshot(first_service)

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-06 13:00:00')

            second_service = self._build_service(snapshot_file)
            second_service.list_code_prefixes = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError('should reuse persisted list snapshot')
            )
            BackendService._load_code_prefix_snapshots(second_service)

            second = BackendService.list_code_prefixes_snapshot(second_service)

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-06 13:00:00')
            self.assertEqual(second['prefixes'][0]['prefix'], 'ADN')

    def test_detail_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-06 13:05:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.get_code_prefix_detail = lambda prefix: {
                'prefix_detail': {
                    'prefix': prefix,
                    'video_count': 12,
                    'avfan_total_videos': 18,
                }
            }

            first = BackendService.get_code_prefix_detail_snapshot(first_service, 'ADN')

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-06 13:05:00')

            second_service = self._build_service(snapshot_file)
            second_service.get_code_prefix_detail = lambda prefix: (_ for _ in ()).throw(
                AssertionError('should reuse persisted detail snapshot')
            )
            BackendService._load_code_prefix_snapshots(second_service)

            second = BackendService.get_code_prefix_detail_snapshot(second_service, 'ADN')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-06 13:05:00')
            self.assertEqual(second['prefix_detail']['prefix'], 'ADN')
            self.assertTrue((Path(temp_dir) / 'code_prefix_detail' / 'ADN.json').exists())

    def test_directory_detail_snapshot_is_reused_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            detail_dir = Path(temp_dir) / 'code_prefix_detail'
            detail_dir.mkdir(parents=True, exist_ok=True)
            (detail_dir / 'ADN.json').write_text(
                """
{
  "prefix_detail": {"prefix": "ADN"},
  "refreshed_at": "2026-07-06 13:05:00",
  "refresh_duration_ms": 11,
  "refresh_duration_text": "11ms"
}
                """.strip(),
                encoding='utf-8',
            )
            service = self._build_service(snapshot_file)
            service.get_code_prefix_detail = lambda prefix: (_ for _ in ()).throw(
                AssertionError('should reuse code prefix detail snapshot file')
            )

            BackendService._load_code_prefix_snapshots(service)
            second = BackendService.get_code_prefix_detail_snapshot(service, 'ADN')

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['prefix_detail']['prefix'], 'ADN')

    def test_legacy_detail_snapshots_migrate_into_code_prefix_detail_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            snapshot_file.write_text(
                """
{
  "version": 1,
  "filter_settings_fingerprint": "{}",
  "library_snapshots": {},
  "detail_snapshots": {
    "ADN": {
      "prefix_detail": {"prefix": "ADN"},
      "refreshed_at": "2026-07-06 13:05:00",
      "refresh_duration_ms": 10,
      "refresh_duration_text": "10ms"
    }
  }
}
                """.strip(),
                encoding='utf-8',
            )
            service = self._build_service(snapshot_file)

            BackendService._load_code_prefix_snapshots(service)

            self.assertIn('ADN', service._code_prefix_detail_snapshots)
            self.assertTrue((Path(temp_dir) / 'code_prefix_detail' / 'ADN.json').exists())

    def test_force_refresh_code_prefix_list_does_not_auto_pre_generate_detail_snapshots(self):
        snapshot_file = Path(tempfile.gettempdir()) / 'code_prefix_snapshot_force_refresh.json'
        service = self._build_service(snapshot_file)
        service.list_code_prefixes = lambda *args, **kwargs: {
            'prefixes': [{'prefix': 'ADN'}],
            'total_count': 1,
            'offset': 0,
            'limit': None,
        }
        service._current_snapshot_timestamp = lambda: '2026-07-06 13:05:00'
        service._append_snapshot_refresh_log = lambda **kwargs: None
        service._pre_generate_all_code_prefix_detail_snapshots = lambda: (_ for _ in ()).throw(
            AssertionError('should not auto pre-generate code prefix detail snapshots')
        )

        result = BackendService.list_code_prefixes_snapshot(service, force_refresh=True)

        self.assertFalse(result['cache_hit'])

    def test_code_prefix_detail_snapshot_file_uses_safe_encoded_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'code_prefix_snapshot.json'
            service = self._build_service(snapshot_file)
            service._current_snapshot_timestamp = lambda: '2026-07-06 13:05:00'
            service.get_code_prefix_detail = lambda prefix: {'prefix_detail': {'prefix': prefix}}

            BackendService.get_code_prefix_detail_snapshot(service, 'AB/CD?')

            self.assertTrue((Path(temp_dir) / 'code_prefix_detail' / 'AB%2FCD%3F.json').exists())


class BackendClientCodePrefixSnapshotTest(unittest.TestCase):
    def test_list_code_prefixes_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'prefixes': [], 'refreshed_at': '2026-07-06 13:10:00'}

        client._get = fake_get

        result = client.list_code_prefixes_snapshot(
            search_text='AD',
            sort_field='prefix',
            sort_order='desc',
            limit=50,
            offset=100,
            force_refresh=True,
        )

        self.assertEqual(result['refreshed_at'], '2026-07-06 13:10:00')
        self.assertEqual(
            calls,
            [('/database/code-prefixes?q=AD&sort_field=prefix&sort_order=desc&limit=50&offset=100&refresh=1', 120)],
        )

    def test_get_code_prefix_detail_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'prefix_detail': {'prefix': 'ADN'}, 'refreshed_at': '2026-07-06 13:15:00'}

        client._get = fake_get

        result = client.get_code_prefix_detail_snapshot('ADN', force_refresh=True)

        self.assertEqual(result['prefix_detail']['prefix'], 'ADN')
        self.assertEqual(
            calls,
            [('/database/code-prefixes/detail?prefix=ADN&refresh=1', 120)],
        )


if __name__ == '__main__':
    unittest.main()
