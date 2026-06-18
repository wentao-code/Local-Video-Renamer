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


if __name__ == '__main__':
    unittest.main()
