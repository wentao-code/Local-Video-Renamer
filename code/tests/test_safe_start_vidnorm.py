import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.backend_protocol import BACKEND_API_REVISION, BACKEND_PROCESS_CODE_FINGERPRINT
from app.core.project_paths import PROJECT_ROOT
from safe_start_vidnorm import (
    BACKEND_INSTANCE_TOKEN_ENV,
    BACKEND_OWNED_ENV,
    build_gui_environment,
    choose_gui_interpreter,
    format_backend_failure,
    is_expected_backend,
    is_project_backend,
    run_launcher,
)


class SafeStartVidnormTest(unittest.TestCase):
    def test_run_launcher_reuses_existing_project_backend_without_restarting_it(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'reuse-token',
            'backend_process_id': 42876,
        }
        captured = {}

        class _GuiProcess:
            def wait(self):
                return 0

        def _fake_popen(args, cwd=None, env=None, **kwargs):
            captured['args'] = list(args or [])
            captured['cwd'] = cwd
            captured['env'] = dict(env or {})
            return _GuiProcess()

        with patch('safe_start_vidnorm.get_backend_health', return_value=health), patch(
            'safe_start_vidnorm.start_backend_process'
        ) as start_backend_mock, patch('safe_start_vidnorm.terminate_pid') as terminate_pid_mock, patch(
            'safe_start_vidnorm.wait_for_expected_backend'
        ) as wait_backend_mock, patch('safe_start_vidnorm.subprocess.Popen', side_effect=_fake_popen):
            exit_code = run_launcher(test_mode=False)

        self.assertEqual(exit_code, 0)
        start_backend_mock.assert_not_called()
        terminate_pid_mock.assert_not_called()
        wait_backend_mock.assert_not_called()
        self.assertEqual(captured['env'][BACKEND_INSTANCE_TOKEN_ENV], 'reuse-token')
        self.assertEqual(captured['env'][BACKEND_OWNED_ENV], '0')

    def test_run_launcher_replaces_stale_same_project_backend_before_starting_new_one(self):
        stale_health = {
            'backend_revision': 'stale-revision',
            'backend_code_fingerprint': 'stale-fingerprint',
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'old-token',
            'backend_process_id': 42876,
        }
        captured = {}

        class _BackendProcess:
            pid = 55667

            @staticmethod
            def poll():
                return 0

        class _GuiProcess:
            def wait(self):
                return 0

        def _fake_popen(args, cwd=None, env=None, **kwargs):
            captured['args'] = list(args or [])
            captured['cwd'] = cwd
            captured['env'] = dict(env or {})
            return _GuiProcess()

        with patch('safe_start_vidnorm.get_backend_health', return_value=stale_health), patch(
            'safe_start_vidnorm.uuid.uuid4'
        ) as uuid_mock, patch('safe_start_vidnorm.terminate_pid', return_value=True) as terminate_pid_mock, patch(
            'safe_start_vidnorm.wait_for_backend_release', return_value=True
        ) as wait_release_mock, patch(
            'safe_start_vidnorm.start_backend_process', return_value=_BackendProcess()
        ) as start_backend_mock, patch(
            'safe_start_vidnorm.wait_for_expected_backend'
        ) as wait_backend_mock, patch('safe_start_vidnorm.subprocess.Popen', side_effect=_fake_popen):
            uuid_mock.return_value.hex = 'fresh-token'
            exit_code = run_launcher(test_mode=False)

        self.assertEqual(exit_code, 0)
        terminate_pid_mock.assert_called_once_with('42876')
        wait_release_mock.assert_called_once_with(timeout_seconds=3)
        start_backend_mock.assert_called_once()
        wait_backend_mock.assert_called_once()
        self.assertEqual(captured['env'][BACKEND_INSTANCE_TOKEN_ENV], 'fresh-token')
        self.assertEqual(captured['env'][BACKEND_OWNED_ENV], '1')

    def test_is_project_backend_accepts_same_project_health(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'token-1',
        }

        self.assertTrue(is_project_backend(health))

    def test_is_expected_backend_requires_matching_token(self):
        health = {
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'project_root': str(PROJECT_ROOT),
            'backend_instance_token': 'token-1',
        }

        self.assertTrue(is_expected_backend(health, 'token-1'))
        self.assertFalse(is_expected_backend(health, 'token-2'))

    def test_build_gui_environment_marks_owned_backend(self):
        base_env = {'EXAMPLE': '1'}

        gui_env = build_gui_environment(base_env, 'abc123', owns_backend=True)

        self.assertEqual(gui_env['EXAMPLE'], '1')
        self.assertEqual(gui_env[BACKEND_INSTANCE_TOKEN_ENV], 'abc123')
        self.assertEqual(gui_env[BACKEND_OWNED_ENV], '1')

    def test_choose_gui_interpreter_prefers_pythonw_sibling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir)
            python_exe = scripts_dir / 'python.exe'
            pythonw_exe = scripts_dir / 'pythonw.exe'
            python_exe.write_text('', encoding='utf-8')
            pythonw_exe.write_text('', encoding='utf-8')

            resolved = choose_gui_interpreter(str(python_exe))

            self.assertEqual(resolved, str(pythonw_exe))

    def test_choose_gui_interpreter_falls_back_to_console_python(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir)
            python_exe = scripts_dir / 'python.exe'
            python_exe.write_text('', encoding='utf-8')

            resolved = choose_gui_interpreter(str(python_exe))

            self.assertEqual(resolved, str(python_exe))

    def test_format_backend_failure_prefers_initializing_message(self):
        message = format_backend_failure(process_alive=True, stale_backend_cleaned=False)

        self.assertIn('后端仍在初始化', message)


if __name__ == '__main__':
    unittest.main()
