import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_viewer import DataCenterWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.summary_refresh_flags = []
        self.analysis_opened = False

    def get_data_center_summary(self, force_refresh=False):
        self.summary_refresh_flags.append(bool(force_refresh))
        return {
            'summary': {
                'video_library': {'sources': {'avfan': {}, 'javtxt': {}}},
                'code_prefix_library': {'sources': {'avfan': {}, 'javtxt': {}}},
                'actor_library': {'sources': {'avfan': {}, 'javtxt': {}, 'binghuo': {}}},
            },
            'refreshed_at': '2026-06-21 12:34:56',
        }

    @staticmethod
    def get_enrichment_progress():
        return {}


class DataCenterViewerTest(unittest.TestCase):
    def test_uses_cached_summary_on_open_and_force_refresh_on_button_click(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                self.assertEqual(backend.summary_refresh_flags, [False])

                window.load_data(force_refresh=True)

                self.assertEqual(backend.summary_refresh_flags, [False, True])
                self.assertIn('2026-06-21 12:34:56', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
