import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QWidget

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.refresh_flags = []

    def get_code_prefix_detail_snapshot(self, prefix, force_refresh=False):
        self.refresh_flags.append(bool(force_refresh))
        return {
            'prefix_detail': {
                'prefix': prefix,
                'ladder_tier': 'S',
                'update_status': 'active',
                'video_count': 12,
                'avfan_total_pages': 3,
                'avfan_total_videos': 24,
                'eligible_video_count': 6,
                'eligible_enriched_video_count': 5,
                'earliest_release_date': '2024-01-01',
                'latest_release_date': '2024-02-03',
                'last_enriched_at': '',
                'update_frequency': {
                    'video_count': 6,
                    'month_count': 2,
                    'videos_per_month': 3.0,
                },
                'year_distribution': [],
                'top_actors': [],
                'video_category_distribution': [],
                'uncategorized_eligible_video_count': 0,
                'local_videos': [],
                'movies': [],
                'web_url': '',
            },
            'refreshed_at': '2026-07-06 14:04:00' if force_refresh else '2026-07-06 14:00:00',
            'cache_hit': not force_refresh,
        }

    def get_code_prefix_detail(self, prefix):
        return self.get_code_prefix_detail_snapshot(prefix, force_refresh=True)['prefix_detail']

    def admit_ladder_entry(self, *_args):
        return {}


class CodePrefixDetailViewerWindowTest(unittest.TestCase):
    def test_load_data_shows_update_frequency_from_snapshot_then_refreshes(self):
        parent = QWidget()
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixDetailViewerWindow(backend, 'ROE', parent)
            try:
                self.assertEqual(window.summary_grid.value_labels['prefix'].text(), 'ROE')
                self.assertIn('3.00', window.last_enriched_grid.value_labels['update_frequency'].text())
                self.assertEqual(backend.refresh_flags, [False, True])
                self.assertIn('2026-07-06 14:04:00', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()
                parent.deleteLater()

    def test_deferred_startup_refresh_keeps_allow_deferred_close_flag(self):
        parent = QWidget()
        backend = _BackendStub()
        captured = []

        def _capture_task(self, task, success_handler, error_title=None, block_ui=True, allow_deferred_close=False):
            captured.append(
                {
                    'block_ui': bool(block_ui),
                    'allow_deferred_close': bool(allow_deferred_close),
                }
            )
            success_handler(task())
            return True

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_task):
            window = CodePrefixDetailViewerWindow(backend, 'ROE', parent)
            try:
                captured.clear()
                window._deferred_force_refresh = True
                window._deferred_silent_errors = True
                window._deferred_allow_deferred_close = True

                window._perform_deferred_load()

                self.assertEqual(len(captured), 1)
                self.assertFalse(captured[0]['block_ui'])
                self.assertTrue(captured[0]['allow_deferred_close'])
            finally:
                window.hide()
                window.deleteLater()
                parent.deleteLater()

    def test_stale_prefix_response_is_discarded_after_switch(self):
        parent = QWidget()
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixDetailViewerWindow(backend, 'ROE', parent)
            try:
                window.prefix = 'ADN'
                window._active_request_token = 2
                window._active_request_prefix = 'ADN'
                original_prefix_text = window.summary_grid.value_labels['prefix'].text()
                original_refreshed_text = window.last_refreshed_label.text()

                window._on_load_data_finished(
                    {
                        'prefix_detail': {'prefix': 'ROE'},
                        'refreshed_at': '2026-07-08 10:00:00',
                        'cache_hit': False,
                        'request_token': 1,
                        'request_prefix': 'ROE',
                    }
                )

                self.assertEqual(window.prefix, 'ADN')
                self.assertEqual(window.summary_grid.value_labels['prefix'].text(), original_prefix_text)
                self.assertEqual(window.last_refreshed_label.text(), original_refreshed_text)
            finally:
                window.hide()
                window.deleteLater()
                parent.deleteLater()


if __name__ == '__main__':
    unittest.main()
