import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.data.database_handler import VideoDatabase
from app.services.local_video import (
    LocalVideoMediaInfo,
    LocalVideoImportService,
    LocalVideoScanService,
    format_duration_seconds,
    format_size_gb,
)


class LocalVideoMediaImportTest(unittest.TestCase):
    def test_formats_media_values_for_video_library_columns(self):
        self.assertEqual(format_duration_seconds(3723.2), '1:02:03')
        self.assertEqual(format_size_gb(1536 * 1024 * 1024), '1.5')

    def test_scan_and_import_persist_duration_and_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video_path = folder / 'ABP-123.mp4'
            video_path.write_bytes(b'not a real video')

            db = VideoDatabase(folder / 'video_database.db')
            scan_service = LocalVideoScanService(db)
            import_service = LocalVideoImportService(db)

            with patch(
                'app.services.local_video.local_video_scan_service.read_local_video_media_info',
                return_value=LocalVideoMediaInfo(duration='1:02:03', size_gb='0.456'),
            ):
                scan_result = scan_service.scan_folder(folder)

            self.assertEqual(scan_result['count'], 1)
            plan = scan_result['plans'][0]
            self.assertEqual(plan['metadata']['duration'], '1:02:03')
            self.assertEqual(plan['metadata']['size'], '0.456')

            import_service.import_videos(scan_result['plans'])
            row = db.list_videos()[0]

        self.assertEqual(row['code'], 'ABP-123')
        self.assertEqual(row['duration'], '1:02:03')
        self.assertEqual(row['size'], '0.456')

    def test_scan_updates_usb_inventory_and_records_deleted_video_capacity_change(self):
        mb = 1024 * 1024
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            deleted_video = folder / 'RCTD-311.mp4'
            kept_video = folder / 'ABP-123.mp4'
            deleted_video.write_bytes(b'deleted video')
            kept_video.write_bytes(b'kept video')

            db = VideoDatabase(folder / 'video_database.db')
            scan_service = LocalVideoScanService(db)
            storage_snapshots = [
                {'total_bytes': 64000 * mb, 'used_bytes': 54000 * mb, 'free_bytes': 10000 * mb},
                {'total_bytes': 64000 * mb, 'used_bytes': 45200 * mb, 'free_bytes': 18800 * mb},
            ]

            with patch(
                'app.services.local_video.local_video_scan_service.read_local_video_media_info',
                return_value=LocalVideoMediaInfo(duration='1:00:00', size_gb='8.8'),
            ), patch(
                'app.services.local_video.local_video_scan_service.PathLibrary.get_storage_info',
                side_effect=storage_snapshots,
            ):
                first_scan = scan_service.scan_folder(folder)
                deleted_video.unlink()
                second_scan = scan_service.scan_folder(folder)

            self.assertEqual(first_scan['inventory_sync']['inventory_count'], 2)
            self.assertEqual(first_scan['inventory_sync']['change_count'], 0)
            self.assertEqual(second_scan['inventory_sync']['inventory_count'], 1)
            self.assertEqual(second_scan['inventory_sync']['change_count'], 1)

            inventory_codes = {row['video_code'] for row in db.get_usb_video_inventory(folder)}
            self.assertEqual(inventory_codes, {'ABP-123'})

            logs = db.list_usb_video_change_logs(folder)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]['video_code'], 'RCTD-311')
            self.assertEqual(logs[0]['change_type'], 'deleted')
            self.assertEqual(logs[0]['capacity_delta_mb'], 8800)
            self.assertEqual(logs[0]['current_capacity_mb'], 18800)
            self.assertIn('视频编号RCTD-311删除', logs[0]['message'])

    def test_video_library_lists_only_entities_with_local_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.upsert_video_entity({'code': 'WEB-001', 'title': 'Web only'})
            db.upsert_video_entity(
                {'code': 'LOC-001', 'title': 'Local video'},
                local_record={
                    'duration': '1:00:00',
                    'size': '1.2',
                    'storage_location': 'Local folder',
                },
            )
            db.convert_legacy_tables_to_compatibility_views()

            rows = db.list_videos()

            self.assertEqual([row['code'] for row in rows], ['LOC-001'])
            self.assertEqual(db.count_videos(), 1)


if __name__ == '__main__':
    unittest.main()
