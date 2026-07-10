import threading
import unittest

from app.backend.service import BackendService


class _BlockingQueenRefreshService:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.batch_sizes = []
        self.stop_checks = 0

    def refresh_all(self, show_browser=True, batch_size=None, progress_callback=None, should_stop=None):
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
        while not self.release.wait(timeout=0.01):
            self.stop_checks += 1
            if callable(should_stop) and should_stop():
                return {
                    'query_count': 20,
                    'processed_count': 10,
                    'remaining_count': 10,
                    'scanned_count': 10,
                    'imported_count': 3,
                    'skipped_count': 7,
                    'stopped': True,
                    'queens': [],
                    'keywords': [],
                }
        return {
            'query_count': 20,
            'processed_count': 20,
            'remaining_count': 0,
            'scanned_count': 20,
            'imported_count': 5,
            'skipped_count': 15,
            'stopped': False,
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

    def test_cancel_queen_library_refresh_marks_progress_stopped(self):
        service = BackendService.__new__(BackendService)
        service.queen_library_service = _BlockingQueenRefreshService()
        service._init_queen_refresh_task_state()

        started = service.refresh_queen_library(show_browser=False)

        self.assertTrue(started['progress']['is_running'])
        self.assertTrue(service.queen_library_service.started.wait(timeout=1))

        cancelled = service.cancel_queen_library_refresh()
        self.assertTrue(cancelled['stopped'])
        self.assertIn('停止', cancelled['message'])

        service._queen_refresh_thread.join(timeout=5)

        progress = service.get_queen_library_refresh_progress()['progress']
        self.assertFalse(progress['is_running'])
        self.assertTrue(progress['stopped'])
        self.assertFalse(progress['completed'])
        self.assertEqual(progress['processed_count'], 10)
        self.assertEqual(progress['remaining_count'], 10)


if __name__ == '__main__':
    unittest.main()
