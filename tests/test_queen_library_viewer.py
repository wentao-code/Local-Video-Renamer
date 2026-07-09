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
            'queens': self.list_queen_library_snapshot(True)['queens'],
            'keywords': self.list_queen_keywords_snapshot(True)['keywords'],
            'query_count': 3,
            'scanned_count': 12,
            'imported_count': 4,
            'skipped_count': 8,
            'log_path': 'D:/tmp/queen_crawl.log',
        }


class _QueenDetailBackendStub:
    def __init__(self, confirmed=False):
        self.saved_profiles = []
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
                {'id': 1, 'video_title': '\u6807\u9898', 'raw_title': '\u539f\u59cb'},
            ],
        }

    def update_queen_profile(self, queen_name, profile):
        self.saved_profiles.append((queen_name, dict(profile or {})))
        self.confirmed = True
        saved = dict(profile or {})
        saved['queen_name'] = queen_name
        saved['profile_confirmed'] = True
        return {'profile': saved}


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
                self.assertIn('处理 3 个搜索词', window.status_label.text())
                self.assertIn('新增 4 条', window.status_label.text())
                self.assertIn('queen_crawl.log', window.status_label.text())
                self.assertEqual(window.btn_start_crawl.text(), '启动抓取')
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
