import json
import tempfile
import unittest
from pathlib import Path

from app.core.snapshot_store import SnapshotStore


class SnapshotStoreTest(unittest.TestCase):
    def test_write_creates_separate_messagepack_and_json_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))
            payload = {'version': 1, 'rows': [{'code': 'SDDE-714'}]}

            store.write('data_center/dashboard', payload)

            self.assertEqual(store.read('data_center/dashboard'), payload)
            self.assertTrue(store.messagepack_path('data_center/dashboard').exists())
            self.assertTrue(store.json_path('data_center/dashboard').exists())
            self.assertEqual(store.messagepack_path('data_center/dashboard').parent.name, 'data_center')
            self.assertEqual(store.json_path('data_center/dashboard').parent.name, 'data_center')
            self.assertIn('messagepack', store.messagepack_path('data_center/dashboard').parts)
            self.assertIn('json', store.json_path('data_center/dashboard').parts)

    def test_read_prefers_messagepack_over_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))
            store.write('actor_library/index', {'source': 'messagepack'})
            store.json_path('actor_library/index').write_text(
                json.dumps({'source': 'json'}),
                encoding='utf-8',
            )

            self.assertEqual(store.read('actor_library/index'), {'source': 'messagepack'})

    def test_corrupt_messagepack_falls_back_to_json_and_repairs_messagepack(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))
            payload = {'rows': [1, 2, 3]}
            store.write('candidate_library/actors', payload)
            store.messagepack_path('candidate_library/actors').write_bytes(b'not-messagepack')

            self.assertEqual(store.read('candidate_library/actors'), payload)

            store.json_path('candidate_library/actors').unlink()
            self.assertEqual(store.read('candidate_library/actors'), payload)

    def test_legacy_json_is_read_and_migrated_to_both_new_formats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_path = root / 'legacy_snapshot.json'
            payload = {'version': 1, 'value': 'legacy'}
            legacy_path.write_text(json.dumps(payload), encoding='utf-8')
            store = SnapshotStore(root / 'snapshots')

            self.assertEqual(store.read('masterpiece/index', legacy_paths=[legacy_path]), payload)
            self.assertTrue(store.messagepack_path('masterpiece/index').exists())
            self.assertTrue(store.json_path('masterpiece/index').exists())

    def test_json_remains_operational_when_messagepack_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir), messagepack_available=False)
            payload = {'rows': ['json-only']}

            store.write('queen_library/index', payload)

            self.assertFalse(store.messagepack_path('queen_library/index').exists())
            self.assertTrue(store.json_path('queen_library/index').exists())
            self.assertEqual(store.read('queen_library/index'), payload)

    def test_delete_prefix_removes_both_formats_without_touching_other_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))
            store.write('video_category/tier_1', {'tier': 1})
            store.write('video_category/tier_2', {'tier': 2})
            store.write('data_center/dashboard', {'dashboard': True})

            store.delete_prefix('video_category')

            self.assertIsNone(store.read('video_category/tier_1'))
            self.assertIsNone(store.read('video_category/tier_2'))
            self.assertEqual(store.read('data_center/dashboard'), {'dashboard': True})

    def test_iter_keys_unifies_messagepack_and_json_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))
            store.write('actor_detail/alice', {'name': 'Alice'})
            store.write('actor_detail/bob', {'name': 'Bob'})
            store.messagepack_path('actor_detail/bob').unlink()
            store.write('code_prefix_detail/SDDE', {'prefix': 'SDDE'})

            self.assertEqual(
                store.iter_keys('actor_detail'),
                ['actor_detail/alice', 'actor_detail/bob'],
            )

    def test_snapshot_key_must_be_a_safe_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SnapshotStore(Path(temp_dir))

            for key in ('', '../escape', '/absolute', 'a/../../escape'):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    store.json_path(key)


if __name__ == '__main__':
    unittest.main()
