import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.main_window import VidNormApp
from app.gui.queen_library_viewer import QueenLibraryWindow


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
                {'queen_name': '\u5c0f7s', 'video_count': 1},
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
                self.assertEqual(first_button.text(), '\u5c0f7s')
                self.assertNotIn('\u6761', first_button.text())
                self.assertEqual(first_button.width(), 104)
                self.assertEqual(first_button.height(), 36)
                self.assertEqual(window.grid_layout.getItemPosition(8)[:2], (0, 8))
                self.assertEqual(window.grid_layout.getItemPosition(9)[:2], (1, 0))
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
