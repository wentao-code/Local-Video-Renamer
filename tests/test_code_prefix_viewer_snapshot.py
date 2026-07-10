import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QHeaderView

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow


_APP = QApplication.instance() or QApplication([])


def _capture_sync_async_task(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
):
    calls = list(getattr(self, '_captured_async_calls', []))
    calls.append(
        {
            'error_title': error_title,
            'block_ui': bool(block_ui),
            'allow_deferred_close': bool(allow_deferred_close),
        }
    )
    self._captured_async_calls = calls
    success_handler(task())
    return True


def _run_sync_task_with_failures(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
):
    calls = list(getattr(self, '_captured_async_calls', []))
    calls.append(
        {
            'error_title': error_title,
            'block_ui': bool(block_ui),
            'allow_deferred_close': bool(allow_deferred_close),
        }
    )
    self._captured_async_calls = calls
    try:
        success_handler(task())
    except Exception as exc:
        self._handle_async_task_failed(str(exc))
    return True


class _BackendStub:
    def __init__(self):
        self.calls = []

    def list_code_prefixes_snapshot(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=200,
        offset=0,
        force_refresh=False,
    ):
        self.calls.append((search_text, sort_field, sort_order, limit, offset, bool(force_refresh)))
        return {
            'prefixes': [
                {
                    'prefix': 'ADN',
                    'video_count': 12,
                    'enrichment_status': '',
                    'avfan_total_videos': 30,
                    'earliest_release_date': '2024-01-01',
                    'latest_release_date': '2024-02-01',
                }
            ],
            'total_count': 1,
            'limit': limit,
            'offset': offset,
            'refreshed_at': '2026-07-06 14:10:00' if force_refresh else '2026-07-06 14:00:00',
            'refresh_duration_ms': 18000 if force_refresh else 11000,
            'refresh_duration_text': '80s' if force_refresh else '11s',
            'cache_hit': not force_refresh,
        }


class _TimeoutAfterSnapshotBackendStub(_BackendStub):
    def list_code_prefixes_snapshot(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=200,
        offset=0,
        force_refresh=False,
    ):
        if force_refresh:
            raise RuntimeError('Read timed out')
        return super().list_code_prefixes_snapshot(
            search_text=search_text,
            sort_field=sort_field,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            force_refresh=force_refresh,
        )


class CodePrefixViewerSnapshotTest(unittest.TestCase):
    def test_table_expands_status_and_release_date_columns(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                header = window.table.horizontalHeader()

                self.assertEqual(header.sectionResizeMode(2), QHeaderView.Stretch)
                self.assertEqual(header.sectionResizeMode(4), QHeaderView.Stretch)
                self.assertEqual(header.sectionResizeMode(5), QHeaderView.Stretch)
                self.assertEqual(header.sectionResizeMode(7), QHeaderView.ResizeToContents)
            finally:
                window.hide()
                window.deleteLater()

    def test_startup_load_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                self.assertEqual(
                    backend.calls,
                    [
                        ('', 'prefix', 'asc', window.page_size, 0, False),
                        ('', 'prefix', 'asc', window.page_size, 0, True),
                    ],
                )
                self.assertIn('2026-07-06 14:10:00', window.last_refreshed_label.text())
                self.assertIn('18秒', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_startup_background_refresh_does_not_block_ui(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                self.assertEqual(
                    [item['block_ui'] for item in window._captured_async_calls],
                    [True, False],
                )
                self.assertEqual(
                    [item['allow_deferred_close'] for item in window._captured_async_calls],
                    [False, True],
                )
            finally:
                window.hide()
                window.deleteLater()

    def test_startup_background_refresh_timeout_does_not_popup(self):
        backend = _TimeoutAfterSnapshotBackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_task_with_failures),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
            patch('app.gui.code_prefix_viewer.QMessageBox.critical') as critical_mock,
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                self.assertFalse(critical_mock.called)
                self.assertIn('2026-07-06 14:00:00', window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_background_snapshot_refresh_close_does_not_show_task_popup(self):
        backend = _BackendStub()

        class _EventStub:
            def __init__(self):
                self.ignored = False

            def ignore(self):
                self.ignored = True

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
            patch('app.gui.code_prefix_viewer.QMessageBox.information') as info_mock,
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                window._async_task_thread = SimpleNamespace(isRunning=lambda: True)
                window._async_task_allows_deferred_close = True
                event = _EventStub()

                blocked = window.block_close_while_async_running(event)

                self.assertTrue(blocked)
                self.assertTrue(event.ignored)
                self.assertFalse(info_mock.called)
                self.assertTrue(window._async_close_pending)
            finally:
                window.hide()
                window.deleteLater()

    def test_deferred_startup_refresh_keeps_allow_deferred_close_flag(self):
        backend = _BackendStub()

        with (
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_sync_async_task),
            patch(
                'app.gui.code_prefix_viewer.load_code_prefix_library_settings',
                return_value={'sort_field': 'prefix', 'sort_order': 'asc'},
            ),
            patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
        ):
            window = CodePrefixViewerWindow(backend)
            try:
                window._captured_async_calls = []
                window._deferred_force_refresh = True
                window._deferred_silent_errors = True
                window._deferred_block_ui = False
                window._deferred_allow_deferred_close = True

                window._perform_deferred_load()

                self.assertEqual(len(window._captured_async_calls), 1)
                self.assertFalse(window._captured_async_calls[0]['block_ui'])
                self.assertTrue(window._captured_async_calls[0]['allow_deferred_close'])
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
