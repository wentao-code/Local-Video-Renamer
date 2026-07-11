import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.gui.video_list_detail_viewer import VideoListDetailWindow


_APP = QApplication.instance() or QApplication([])


class PlainDialogChromeTest(unittest.TestCase):
    def test_video_list_detail_window_is_minimizable(self):
        window = VideoListDetailWindow('Videos', 'Rows', [])
        try:
            self.assertTrue(window.windowFlags() & Qt.WindowMinimizeButtonHint)
        finally:
            window.deleteLater()


if __name__ == '__main__':
    unittest.main()
