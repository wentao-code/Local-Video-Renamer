import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.timeout_settings_viewer import TimeoutSettingsViewerWindow


def _run_sync_task(self, task, success_handler, error_title=None, **kwargs):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.updated = []
        self.reset_calls = []

    @staticmethod
    def _rows(custom=None):
        custom_value = custom
        return [
            {
                'setting_key': 'network_probe',
                'operation_name': '网络检测',
                'default_value_seconds': 0.8,
                'custom_value_seconds': custom_value,
                'effective_value_seconds': 0.8 if custom_value is None else custom_value,
                'uses_default': custom_value is None,
                'minimum_value_seconds': 0.1,
                'maximum_value_seconds': 30,
            }
        ]

    def list_operation_timeouts(self):
        return self._rows()

    def update_operation_timeouts(self, values):
        self.updated.append(values)
        return self._rows(float(values['network_probe']))

    def reset_operation_timeouts(self, setting_keys=None):
        self.reset_calls.append(setting_keys)
        return self._rows()


class TimeoutSettingsViewerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_renders_columns_and_saves_decimal_override(self):
        backend = _BackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_task):
            window = TimeoutSettingsViewerWindow(backend)
            try:
                self.assertEqual(window.table.columnCount(), 5)
                self.assertEqual(window.table.rowCount(), 1)
                editor = window.custom_editors['network_probe']
                editor.setText('1.25')
                window.save_changes()
                self.assertEqual(backend.updated, [{'network_probe': '1.25'}])
                self.assertIn('#c62828', window.indicator_labels['network_probe'].styleSheet())
                self.assertEqual(window.table.item(0, 3).text(), '1.25')
            finally:
                window.close()

    def test_selected_and_all_reset_call_backend(self):
        backend = _BackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_task):
            window = TimeoutSettingsViewerWindow(backend)
            try:
                window.table.selectRow(0)
                window.reset_selected()
                window.reset_all()
                self.assertEqual(backend.reset_calls, [['network_probe'], None])
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
