import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class ActorBackendStub:
    def __init__(self):
        self.rows = [
            {
                'name': 'Alpha',
                'actor_id': '',
                'birthday': '',
                'age': '',
                'raw_age': '',
                'enrichment_status': '',
            }
        ]
        self.added = []
        self.list_calls = 0

    def list_actors(self, search_text=''):
        self.list_calls += 1
        search = str(search_text or '').strip().lower()
        if not search:
            return [dict(row) for row in self.rows]
        return [dict(row) for row in self.rows if search in str(row.get('name', '')).lower()]

    def add_actor(self, actor_name, birthday='', age=''):
        self.added.append((actor_name, birthday, age))
        self.rows.append(
            {
                'name': actor_name,
                'actor_id': '',
                'birthday': birthday,
                'age': age,
                'raw_age': age,
                'enrichment_status': '',
            }
        )
        return 1


class CodePrefixBackendStub:
    def __init__(self):
        self.rows = [
            {
                'prefix': 'ABC',
                'video_count': 1,
                'enrichment_status': '',
                'avfan_total_videos': 0,
                'earliest_release_date': '',
                'latest_release_date': '',
            }
        ]
        self.added = []
        self.list_calls = 0

    def list_code_prefixes(self, search_text=''):
        self.list_calls += 1
        search = str(search_text or '').strip().upper()
        if not search:
            return [dict(row) for row in self.rows]
        return [dict(row) for row in self.rows if search in str(row.get('prefix', '')).upper()]

    def add_code_prefix(self, prefix):
        self.added.append(prefix)
        self.rows.append(
            {
                'prefix': prefix,
                'video_count': 0,
                'enrichment_status': '',
                'avfan_total_videos': 0,
                'earliest_release_date': '',
                'latest_release_date': '',
            }
        )
        return 1


class ViewerInlineAddTest(unittest.TestCase):
    def test_actor_viewer_adds_top_inline_row_and_confirms(self):
        backend = ActorBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = ActorViewerWindow(backend)
            try:
                backend.list_calls = 0
                window.handle_add_button()

                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(0, 0).text(), '')
                self.assertTrue(window.table.item(0, 0).flags() & Qt.ItemIsEditable)

                window.table.item(0, 0).setText('Beta')
                with patch.object(QMessageBox, 'information'):
                    window.handle_add_button()

                self.assertEqual(backend.added, [('Beta', '', '')])
                self.assertEqual(backend.list_calls, 0)
                self.assertIn('Beta', [window.table.item(row, 0).text() for row in range(window.table.rowCount())])
            finally:
                window.hide()
                window.deleteLater()

    def test_code_prefix_viewer_warns_before_duplicate_add(self):
        backend = CodePrefixBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixViewerWindow(backend)
            try:
                window.handle_add_button()
                window.table.item(0, 0).setText('abc')

                with patch.object(QMessageBox, 'warning') as warning_mock:
                    window.handle_add_button()

                self.assertEqual(backend.added, [])
                self.assertTrue(warning_mock.called)
            finally:
                window.hide()
                window.deleteLater()

    def test_code_prefix_viewer_adds_without_reloading_full_library(self):
        backend = CodePrefixBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CodePrefixViewerWindow(backend)
            try:
                backend.list_calls = 0
                window.handle_add_button()
                window.table.item(0, 0).setText('ipx')

                with patch.object(QMessageBox, 'information'):
                    window.handle_add_button()

                self.assertEqual(backend.added, ['IPX'])
                self.assertEqual(backend.list_calls, 0)
                self.assertIn('IPX', [window.table.item(row, 0).text() for row in range(window.table.rowCount())])
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
