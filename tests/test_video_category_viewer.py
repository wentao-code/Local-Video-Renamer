import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.video_category_viewer import VideoCategoryViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendClientStub:
    base_url = 'http://127.0.0.1:65535'
    timeout = 30


class _RefreshClientStub:
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def list_videos_requiring_manual_category():
        return {
            'videos': [],
            'staged_count': 0,
        }


class VideoCategoryViewerWindowTest(unittest.TestCase):
    def test_filter_button_renders_in_bottom_toolbar_and_opens_dialog(self):
        created = {}

        class FakeFilterDialog:
            def __init__(self, parent=None):
                created['parent'] = parent

            def exec_(self):
                created['opened'] = True

        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch('app.gui.video_category_viewer.VideoFilterDialog', FakeFilterDialog),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                bottom_layout = window.layout().itemAt(2).layout()
                self.assertIs(bottom_layout.itemAt(2).widget(), window.btn_filter_rules)

                window.btn_filter_rules.click()

                self.assertIs(created.get('parent'), window)
                self.assertTrue(created.get('opened'))
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
