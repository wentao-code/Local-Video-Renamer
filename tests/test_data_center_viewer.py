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
            'refreshed_at': '2026-06-21 12:35:56' if force_refresh else '2026-06-21 12:34:56',
        }

    @staticmethod
    def get_enrichment_progress():
        return {}


class DataCenterViewerTest(unittest.TestCase):
    def test_startup_load_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                self.assertEqual(backend.summary_refresh_flags, [False, True])
                self.assertIn('2026-06-21 12:35:56', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_manual_refresh_still_uses_force_refresh_after_startup_refresh(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                window.load_data(force_refresh=True)

                self.assertEqual(backend.summary_refresh_flags, [False, True, True])
                self.assertIn('2026-06-21 12:35:56', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_show_analysis_window_opens_data_analysis_entry_dialog(self):
        backend = _BackendStub()
        created = {}

        class FakeAnalysisWindow:
            def __init__(self, backend_client, parent=None):
                created['backend_client'] = backend_client
                created['parent'] = parent

            def show(self):
                created['opened'] = True

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                with patch('app.gui.data_center_viewer.DataAnalysisWindow', FakeAnalysisWindow):
                    window.show_analysis_window()
            finally:
                window.hide()
                window.deleteLater()

        self.assertIs(created.get('backend_client'), backend)
        self.assertIs(created.get('parent'), window)
        self.assertTrue(created.get('opened'))


if __name__ == '__main__':
    unittest.main()
