import json
import tempfile
import unittest
from pathlib import Path

from app.gui.runtime_settings import load_runtime_mode, save_runtime_mode
from app.gui.task_queue import RUN_MODE_TASK, RUN_MODE_VIEW


class RuntimeSettingsTest(unittest.TestCase):
    def test_missing_and_invalid_settings_default_to_task_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / 'runtime_settings.json'
            self.assertEqual(load_runtime_mode(settings_file), RUN_MODE_TASK)
            settings_file.write_text('{invalid', encoding='utf-8')
            self.assertEqual(load_runtime_mode(settings_file), RUN_MODE_TASK)
            settings_file.write_text(json.dumps({'run_mode': 'unknown'}), encoding='utf-8')
            self.assertEqual(load_runtime_mode(settings_file), RUN_MODE_TASK)

    def test_runtime_mode_survives_save_and_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / 'runtime_settings.json'
            save_runtime_mode(settings_file, RUN_MODE_VIEW)
            self.assertEqual(load_runtime_mode(settings_file), RUN_MODE_VIEW)


if __name__ == '__main__':
    unittest.main()
