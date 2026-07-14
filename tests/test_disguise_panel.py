import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.disguise_panel import NetworkAssistantDisguise
from app.gui.main_window import VidNormApp


class _PageStack:
    def __init__(self):
        self.current_widget = None

    def setCurrentWidget(self, widget):
        self.current_widget = widget


class _WindowStub:
    def __init__(self):
        self.page_stack = _PageStack()
        self.disguise_page = object()
        self.normal_page = object()
        self.window_title = ''

    def setWindowTitle(self, title):
        self.window_title = title


class NetworkAssistantDisguiseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_send_button_requests_return_to_normal_interface(self):
        panel = NetworkAssistantDisguise()
        exit_requests = []
        panel.exit_requested.connect(lambda: exit_requests.append(True))

        self.assertEqual(panel.window_title_label.text(), '网络调试助手')
        self.assertEqual(panel.send_button.text(), '发送')
        self.assertFalse(panel.send_button.isFlat())

        panel.send_button.click()

        self.assertEqual(exit_requests, [True])

    def test_main_window_switches_between_normal_and_disguise_pages(self):
        window = _WindowStub()

        VidNormApp.enter_disguise_mode(window)
        self.assertIs(window.page_stack.current_widget, window.disguise_page)
        self.assertEqual(window.window_title, '网络调试助手')

        VidNormApp.exit_disguise_mode(window)
        self.assertIs(window.page_stack.current_widget, window.normal_page)


if __name__ == '__main__':
    unittest.main()
