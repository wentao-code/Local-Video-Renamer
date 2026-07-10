import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.main_window import VidNormApp
from app.gui.queen_library_viewer import KeywordLibraryWindow, QueenDetailWindow, QueenLibraryWindow


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


class _QueenBackendStub:
    def __init__(self):
        self.refresh_calls = []
        self.cancel_calls = 0

    def list_queen_library_snapshot(self, force_refresh=False):
        return {
            'queens': [
                {'queen_name': '\u5c0f7s', 'video_count': 1, 'profile_confirmed': True},
                {'queen_name': '\u767d\u4e00\u6657', 'video_count': 2},
                {'queen_name': '\u4e00\u8336', 'video_count': 3},
                {'queen_name': '\u4e00\u8336s', 'video_count': 4},
                {'queen_name': '\u4e8e\u4e8e\u9c7c', 'video_count': 5},
                {'queen_name': '\u5931\u5fc3', 'video_count': 6},
                {'queen_name': '\u5c0f\u9c7c', 'video_count': 7},
                {'queen_name': '\u5c0f\u9c7c\u5927\u5927', 'video_count': 8},
                {'queen_name': '\u5c0f\u9c7c\u5d3d', 'video_count': 9},
                {'queen_name': '\u5c0f\u9c7c\u7239', 'video_count': 10},
            ]
        }

    def list_queen_keywords_snapshot(self, force_refresh=False):
        return {'keywords': [{'keyword': '\u5957\u8def\u76f4\u64ad_'}]}

    def refresh_queen_library(self, show_browser=True):
        self.refresh_calls.append(bool(show_browser))
        return {
            'progress': {
                'is_running': True,
                'completed': False,
                'stopped': False,
                'processed_count': 0,
                'total_count': 3,
                'imported_count': 0,
                'skipped_count': 0,
                'scanned_count': 0,
                'message': '正在启动批量抓取...',
            }
        }

    def cancel_queen_library_refresh(self):
        self.cancel_calls += 1
        return {
            'stopped': True,
            'message': '已请求停止女王库抓取，当前批次完成后停止。',
        }


class _QueenDetailBackendStub:
    def __init__(self, confirmed=False):
        self.saved_profiles = []
        self.saved_video_metadata = []
        self.rename_calls = []
        self.confirmed = confirmed

    def get_queen_detail_snapshot(self, queen_name, force_refresh=False):
        profile = {
            'queen_name': queen_name,
            'body_type': '\u82d7\u6761' if self.confirmed else '',
            'style': '\u6e29\u548c' if self.confirmed else '',
            'face': '\u5426' if self.confirmed else '',
            'age_group': '\u719f\u5973' if self.confirmed else '',
            'like_level': 'B' if self.confirmed else '',
            'profile_confirmed': self.confirmed,
        }
        return {
            'queen_name': queen_name,
            'profile': profile,
            'videos': [
                {
                    'id': 1,
                    'video_title': '\u6807\u9898',
                    'raw_title': '\u539f\u59cb',
                    'content_type': '\u804a\u5929',
                    'content_level': 'B',
                },
            ],
        }

    def update_queen_profile(self, queen_name, profile):
        self.saved_profiles.append((queen_name, dict(profile or {})))
        self.confirmed = True
        saved = dict(profile or {})
        saved['queen_name'] = queen_name
        saved['profile_confirmed'] = True
        return {'profile': saved}

    def rename_queen(self, queen_name, new_queen_name, profile=None):
        self.rename_calls.append((queen_name, new_queen_name, dict(profile or {})))
        return {
            'queen_name': new_queen_name,
            'profile': {
                'queen_name': new_queen_name,
                'body_type': '\u82d7\u6761',
                'style': '\u6e29\u548c',
                'face': '\u5426',
                'age_group': '\u719f\u5973',
                'like_level': 'B',
                'profile_confirmed': True,
            },
            'videos': [
                {
                    'id': 1,
                    'queen_name': new_queen_name,
                    'video_title': '\u6807\u9898',
                    'raw_title': '\u539f\u59cb',
                    'content_type': '\u804a\u5929',
                    'content_level': 'B',
                },
            ],
        }

    def update_queen_video_metadata(self, record_id, content_type, content_level):
        self.saved_video_metadata.append((record_id, content_type, content_level))
        return {
            'video': {
                'id': record_id,
                'content_type': content_type,
                'content_level': content_level,
            }
        }


class _KeywordBackendStub:
    def list_queen_keywords_snapshot(self, force_refresh=False):
        return {
            'keywords': [
                {'keyword': f'\u5173\u952e\u8bcd{index}'}
                for index in range(1, 8)
            ]
        }


class QueenLibraryViewerEntryTest(unittest.TestCase):
    def test_main_window_opens_queen_library_viewer(self):
        app = VidNormApp.__new__(VidNormApp)
        app.backend_client = object()
        created = {}

        class FakeViewer:
            def __init__(self, backend_client, parent=None):
                created['backend_client'] = backend_client
                created['parent'] = parent

            def exec_(self):
                created['opened'] = True

        with patch('app.gui.main_window.QueenLibraryWindow', FakeViewer):
            VidNormApp.show_queen_library_viewer(app)

        self.assertIs(created.get('backend_client'), app.backend_client)
        self.assertIs(created.get('parent'), app)
        self.assertTrue(created.get('opened'))

    def test_queen_library_refresh_button_runs_batch_crawl_with_visible_browser(self):
        backend = _QueenBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = QueenLibraryWindow(backend)
            try:
                window.start_crawl()

                self.assertEqual(backend.refresh_calls, [True])
                self.assertIn('0/3', window.status_label.text())
                self.assertIn('抓取', window.btn_start_crawl.text())
                self.assertTrue(window.btn_stop_crawl.isEnabled())
                self.assertTrue(window.grid_layout.alignment() & Qt.AlignTop)
                first_button = window.grid_layout.itemAt(0).widget()
                self.assertEqual(first_button.text(), '\u767d\u4e00\u6657')
                self.assertNotIn('\u6761', first_button.text())
                highlighted_button = window.grid_layout.itemAt(2).widget()
                self.assertEqual(highlighted_button.text(), '\u5c0f7s')
                self.assertIn('#238636', highlighted_button.styleSheet())
                self.assertEqual(first_button.width(), 104)
                self.assertEqual(first_button.height(), 36)
                self.assertEqual(window.grid_layout.getItemPosition(8)[:2], (0, 8))
                self.assertEqual(window.grid_layout.getItemPosition(9)[:2], (1, 0))

                window._apply_crawl_progress({
                    'is_running': False,
                    'completed': True,
                    'stopped': False,
                    'processed_count': 3,
                    'total_count': 3,
                    'imported_count': 4,
                    'skipped_count': 8,
                    'scanned_count': 12,
                    'log_path': 'D:/tmp/queen_crawl.log',
                    'queens': backend.list_queen_library_snapshot(True)['queens'],
                    'keywords': backend.list_queen_keywords_snapshot(True)['keywords'],
                })

                self.assertIn('queen_crawl.log', window.status_label.text())
                self.assertFalse(window.btn_stop_crawl.isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_queen_library_stop_button_requests_cancel_and_updates_status(self):
        backend = _QueenBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = QueenLibraryWindow(backend)
            try:
                window._set_crawl_running_state(True)

                window.stop_crawl()

                self.assertEqual(backend.cancel_calls, 1)
                self.assertIn('停止', window.status_label.text())
                self.assertFalse(window.btn_stop_crawl.isEnabled())
                self.assertFalse(window.btn_start_crawl.isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_queen_detail_profile_confirm_locks_fields_and_modify_unlocks(self):
        backend = _QueenDetailBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = QueenDetailWindow(backend, '\u5c0f7s')
            try:
                window.profile_fields['body_type'].setCurrentText('\u82d7\u6761')
                window.profile_fields['style'].setCurrentText('\u7c97\u66b4')
                window.profile_fields['face'].setCurrentText('\u662f')
                window.profile_fields['age_group'].setCurrentText('\u5c11\u5987')
                window.profile_fields['like_level'].setCurrentText('A')

                window.confirm_profile()

                self.assertEqual(backend.saved_profiles[0][0], '\u5c0f7s')
                self.assertEqual(backend.saved_profiles[0][1]['like_level'], 'A')
                self.assertFalse(window.profile_fields['body_type'].isEnabled())
                self.assertFalse(window.btn_confirm_profile.isEnabled())
                self.assertTrue(window.btn_modify_profile.isEnabled())

                window.modify_profile()

                self.assertTrue(window.profile_fields['body_type'].isEnabled())
                self.assertTrue(window.btn_confirm_profile.isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_queen_detail_rows_render_and_save_content_metadata_dropdowns(self):
        backend = _QueenDetailBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = QueenDetailWindow(backend, '\u5c0f7s')
            try:
                content_combo = window.table.cellWidget(0, 2)
                level_combo = window.table.cellWidget(0, 3)

                self.assertEqual(content_combo.currentText(), '\u804a\u5929')
                self.assertEqual(level_combo.currentText(), 'B')

                content_combo.setCurrentText('\u8c03\u6559')
                level_combo.setCurrentText('S')

                self.assertIn((1, '\u8c03\u6559', 'B'), backend.saved_video_metadata)
                self.assertIn((1, '\u8c03\u6559', 'S'), backend.saved_video_metadata)
            finally:
                window.hide()
                window.deleteLater()

    def test_queen_detail_name_edit_can_save_and_updates_current_name(self):
        backend = _QueenDetailBackendStub(confirmed=True)
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = QueenDetailWindow(backend, '\u65e7\u540d')
            try:
                self.assertTrue(window.queen_name_input.isReadOnly())
                self.assertTrue(window.btn_edit_queen_name.isEnabled())

                window.start_edit_queen_name()
                self.assertFalse(window.queen_name_input.isReadOnly())
                self.assertTrue(window.btn_save_queen_name.isEnabled())

                window.queen_name_input.setText('\u65b0\u540d')
                window.save_queen_name()

                self.assertEqual(backend.rename_calls[0][0], '\u65e7\u540d')
                self.assertEqual(backend.rename_calls[0][1], '\u65b0\u540d')
                self.assertEqual(window.queen_name, '\u65b0\u540d')
                self.assertEqual(window.queen_name_input.text(), '\u65b0\u540d')
                self.assertTrue(window.queen_name_input.isReadOnly())
                self.assertIn('\u65b0\u540d', window.windowTitle())
            finally:
                window.hide()
                window.deleteLater()

    def test_keyword_library_uses_six_columns_per_row(self):
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = KeywordLibraryWindow(_KeywordBackendStub())
            try:
                self.assertEqual(window.grid_layout.getItemPosition(5)[:2], (0, 5))
                self.assertEqual(window.grid_layout.getItemPosition(6)[:2], (1, 0))
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
