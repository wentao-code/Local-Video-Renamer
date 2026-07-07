import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_viewer import DataCenterWindow


_APP = QApplication.instance() or QApplication([])


def _capture_sync_async_task(self, task, success_handler, error_title=None, block_ui=True):
    calls = list(getattr(self, '_captured_async_calls', []))
    calls.append(
        {
            'error_title': error_title,
            'block_ui': bool(block_ui),
        }
    )
    self._captured_async_calls = calls
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
                'video_library': {
                    'sources': {
                        'avfan': {},
                        'javtxt': {},
                        'supplement': {
                            'label': '视频库 · 补充任务',
                            'total_count': 2,
                            'pending_count': 2,
                            'count_label': '待补全',
                            'pending_label': '待补全',
                        },
                    },
                },
                'code_prefix_library': {
                    'sources': {
                        'avfan': {},
                        'javtxt': {},
                        'supplement': {
                            'label': '番号库 · 补充任务',
                            'total_count': 1,
                            'pending_count': 1,
                            'count_label': '待补全',
                            'pending_label': '待补全',
                        },
                    },
                },
                'actor_library': {
                    'sources': {
                        'avfan': {},
                        'javtxt': {},
                        'binghuo': {},
                        'baomu': {
                            'label': '演员库 · 保木',
                            'total_count': 4,
                            'pending_count': 1,
                            'count_label': '已完成',
                        },
                        'supplement': {
                            'label': '演员库 · 补充任务',
                            'total_count': 3,
                            'pending_count': 3,
                            'count_label': '待补全',
                            'pending_label': '待补全',
                        },
                    },
                },
            },
            'refreshed_at': '2026-06-21 12:35:56' if force_refresh else '2026-06-21 12:34:56',
            'refresh_duration_ms': 80000 if force_refresh else 55000,
            'refresh_duration_text': '80s' if force_refresh else '55s',
        }

    @staticmethod
    def get_enrichment_progress():
        return {}


class DataCenterViewerTest(unittest.TestCase):
    def test_startup_load_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                self.assertEqual(backend.summary_refresh_flags, [False, True])
                self.assertIn('2026-06-21 12:35:56', window.last_refreshed_label.text())
                self.assertIn('80秒', window.last_refresh_duration_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_startup_background_refresh_does_not_block_ui(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                self.assertEqual(
                    [item['block_ui'] for item in window._captured_async_calls],
                    [True, False],
                )
            finally:
                window.hide()
                window.deleteLater()

    def test_manual_refresh_still_uses_force_refresh_after_startup_refresh(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task):
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

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task):
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

    def test_viewer_creates_supplement_progress_cards(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task):
            window = DataCenterWindow(backend)
            try:
                self.assertEqual(window.video_supplement_card.title_label.text(), '视频库 · 补充任务')
                self.assertEqual(window.code_prefix_supplement_card.title_label.text(), '番号库 · 补充任务')
                self.assertEqual(window.actor_supplement_card.title_label.text(), '演员库 · 补充任务')
                self.assertEqual(window.actor_baomu_card.title_label.text(), '演员库 · 保木')
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
