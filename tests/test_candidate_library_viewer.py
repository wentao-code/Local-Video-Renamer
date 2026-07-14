import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.candidate_library_viewer import CandidateLibraryWindow
from app.gui.main_window import VidNormApp


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
    **kwargs,
):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.admitted_actors = []
        self.admitted_prefixes = []

    def list_candidate_actors(self):
        return [{'actor_name': 'Actor B', 'video_count': 12}]

    def list_candidate_code_prefixes(self):
        return [{'prefix': 'BBB', 'video_count': 9}]

    def refresh_candidate_library(self):
        return {'actor_count': 1, 'code_prefix_count': 1}

    def admit_candidate_actor(self, actor_name):
        self.admitted_actors.append(actor_name)
        return 1

    def admit_candidate_code_prefix(self, prefix):
        self.admitted_prefixes.append(prefix)
        return 1


class CandidateLibraryWindowTest(unittest.TestCase):
    def test_loading_and_refreshing_candidate_data_do_not_retry_on_failure(self):
        backend = _BackendStub()
        calls = []

        def capture_async_task(self, task, success_handler, error_title=None, **kwargs):
            calls.append(kwargs.get('max_attempts'))
            return True

        with patch.object(AsyncTaskHostMixin, 'start_async_task', capture_async_task):
            window = CandidateLibraryWindow(backend)
            try:
                window.refresh_candidates()
                self.assertEqual(calls, [1, 1])
            finally:
                window.hide()
                window.deleteLater()

    def test_main_window_opens_candidate_library_window(self):
        app = VidNormApp.__new__(VidNormApp)
        app.backend_client = object()
        created = {}

        class FakeViewer:
            def __init__(self, backend_client, parent=None):
                created['backend_client'] = backend_client
                created['parent'] = parent

            def exec_(self):
                created['opened'] = True

        with patch('app.gui.main_window.CandidateLibraryWindow', FakeViewer):
            VidNormApp.show_candidate_library_viewer(app)

        self.assertIs(created.get('backend_client'), app.backend_client)
        self.assertIs(created.get('parent'), app)
        self.assertTrue(created.get('opened'))

    def test_switches_candidate_views_and_admits_the_displayed_actor(self):
        backend = _BackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch.object(
            QMessageBox,
            'information',
        ):
            window = CandidateLibraryWindow(backend)
            try:
                self.assertEqual(window.table.horizontalHeaderItem(1).text(), '演员')
                self.assertEqual(window.table.item(0, 1).text(), 'Actor B')

                actor_admit_button = window.table.cellWidget(0, 3).findChild(QPushButton)
                actor_admit_button.click()
                self.assertEqual(backend.admitted_actors, ['Actor B'])
                self.assertEqual(window.table.rowCount(), 0)

                window.btn_code_prefixes.click()
                self.assertEqual(window.table.horizontalHeaderItem(1).text(), '番号')
                self.assertEqual(window.table.item(0, 1).text(), 'BBB')
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
