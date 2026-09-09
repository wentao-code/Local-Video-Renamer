import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.python_runtime import resolve_console_python


class PythonRuntimeTest(unittest.TestCase):
    def test_skips_windowsapps_alias_and_finds_later_path_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            alias = root / 'WindowsApps' / 'python.exe'
            real_python = root / 'Anaconda3' / 'python.exe'
            alias.parent.mkdir()
            real_python.parent.mkdir()
            alias.write_bytes(b'alias')
            real_python.write_bytes(b'python')

            with patch('app.core.python_runtime.sys.prefix', ''), patch(
                'app.core.python_runtime.sys.exec_prefix', ''
            ):
                resolved = resolve_console_python(
                    current_executable=str(alias),
                    environ={'PATH': os.pathsep.join((str(alias.parent), str(real_python.parent)))},
                )

            self.assertEqual(Path(resolved), real_python.resolve())

    def test_prefers_current_real_virtual_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            real_python = Path(temp_dir) / 'video_env' / 'python.exe'
            real_python.parent.mkdir()
            real_python.write_bytes(b'python')

            with patch('app.core.python_runtime.sys.executable', ''), patch(
                'app.core.python_runtime.sys.prefix', str(real_python.parent)
            ), patch(
                'app.core.python_runtime.sys.exec_prefix', str(real_python.parent)
            ):
                resolved = resolve_console_python(
                    current_executable='',
                    environ={'PATH': ''},
                )

            self.assertEqual(Path(resolved), real_python.resolve())

    def test_raises_clear_error_when_only_windowsapps_alias_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            alias = Path(temp_dir) / 'WindowsApps' / 'python.exe'
            alias.parent.mkdir()
            alias.write_bytes(b'alias')

            with patch('app.core.python_runtime.sys.prefix', ''), patch(
                'app.core.python_runtime.sys.exec_prefix', ''
            ), self.assertRaisesRegex(RuntimeError, '可执行 Python'):
                resolve_console_python(
                    current_executable=str(alias),
                    environ={'PATH': str(alias.parent)},
                )


if __name__ == '__main__':
    unittest.main()
