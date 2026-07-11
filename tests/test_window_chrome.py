import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog, QWidget

from app.gui.backend_task_worker import AsyncTaskHostMixin, enable_minimize_button
from app.gui.i18n import tr


_APP = QApplication.instance() or QApplication([])


class _AsyncDialog(AsyncTaskHostMixin, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_async_task_host()


class WindowChromeTest(unittest.TestCase):
    def test_async_task_dialogs_are_minimizable_by_default(self):
        dialog = _AsyncDialog()
        try:
            self.assertTrue(dialog.windowFlags() & Qt.WindowMinimizeButtonHint)
        finally:
            dialog.deleteLater()

    def test_parented_dialog_keeps_dialog_window_type_when_minimize_is_added(self):
        parent = QWidget()
        dialog = _AsyncDialog(parent)
        try:
            self.assertIsNone(dialog.parent())
            self.assertTrue(dialog.windowFlags() & Qt.WindowMinimizeButtonHint)
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def test_enable_minimize_button_only_adds_minimize_related_hints(self):
        parent = QWidget()
        dialog = QDialog(parent)
        try:
            original_flags = dialog.windowFlags()
            enable_minimize_button(dialog)

            self.assertIsNone(dialog.parent())
            self.assertTrue(dialog.windowFlags() & Qt.WindowSystemMenuHint)
            self.assertTrue(dialog.windowFlags() & Qt.WindowMinimizeButtonHint)
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def test_enable_minimize_button_detaches_parent_owner(self):
        parent = QWidget()
        dialog = QDialog(parent)
        try:
            self.assertIs(dialog.parent(), parent)

            enable_minimize_button(dialog)

            self.assertIsNone(dialog.parent())
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def test_async_task_title_does_not_use_failure_text_as_task_name(self):
        dialog = _AsyncDialog()
        try:
            dialog.setWindowTitle('视频库')

            self.assertEqual(
                dialog._build_async_task_title(tr('common.read_failed')),
                '视频库 读取数据',
            )
            self.assertEqual(
                dialog._build_async_task_title(tr('common.prompt')),
                '视频库 后台任务',
            )
        finally:
            dialog.deleteLater()

    def test_async_task_title_can_be_inferred_from_success_handler(self):
        dialog = _AsyncDialog()
        try:
            dialog.setWindowTitle('演员库')

            def _on_delete_finished(_result):
                return None

            def _on_sync_finished(_result):
                return None

            self.assertEqual(
                dialog._build_async_task_title(success_handler=_on_delete_finished),
                '演员库 删除数据',
            )
            self.assertEqual(
                dialog._build_async_task_title(success_handler=_on_sync_finished),
                '演员库 同步数据',
            )
        finally:
            dialog.deleteLater()

    def test_explicit_async_task_title_has_priority(self):
        dialog = _AsyncDialog()
        try:
            dialog.setWindowTitle('主界面')

            self.assertEqual(
                dialog._build_async_task_title(
                    error_title=tr('common.read_failed'),
                    task_title='主界面 扫描本地视频',
                ),
                '主界面 扫描本地视频',
            )
        finally:
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
