import threading
import unittest

from app.backend.service import BackendService


class _BlockingQueenRefreshService:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.batch_sizes = []

    def refresh_all(self, show_browser=True, batch_size=None, progress_callback=None):
        self.batch_sizes.append(batch_size)
        self.started.set()
        if callable(progress_callback):
            progress_callback({
                'processed_count': 10,
                'total_count': 20,
                'imported_count': 3,
                'skipped_count': 7,
                'scanned_count': 10,
                'completed': False,
            })
        self.release.wait(timeout=5)
        return {
            'query_count': 20,
            'processed_count': 20,
            'scanned_count': 20,
            'imported_count': 5,
            'skipped_count': 15,
            'queens': [{'queen_name': 'A'}],
            'keywords': [{'keyword': 'K'}],
        }


class QueenRefreshBackgroundTest(unittest.TestCase):
    def test_refresh_queen_library_starts_background_task_and_reports_progress(self):
        service = BackendService.__new__(BackendService)
        service.queen_library_service = _BlockingQueenRefreshService()
        service._init_queen_refresh_task_state()

        started = service.refresh_queen_library(show_browser=False)

        self.assertTrue(started['progress']['is_running'])
        self.assertTrue(service.queen_library_service.started.wait(timeout=1))
        self.assertEqual(service.queen_library_service.batch_sizes, [10])

        progress = service.get_queen_library_refresh_progress()['progress']
        self.assertTrue(progress['is_running'])
        self.assertEqual(progress['processed_count'], 10)
        self.assertEqual(progress['total_count'], 20)

        service.queen_library_service.release.set()
        service._queen_refresh_thread.join(timeout=5)

        completed = service.get_queen_library_refresh_progress()['progress']
        self.assertFalse(completed['is_running'])
        self.assertTrue(completed['completed'])
        self.assertEqual(completed['processed_count'], 20)
        self.assertEqual(completed['queens'], [{'queen_name': 'A'}])


if __name__ == '__main__':
    unittest.main()
