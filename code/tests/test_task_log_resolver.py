import tempfile
import unittest
from pathlib import Path

from app.gui.task_log_resolver import TaskLogResolver


class TaskLogResolverTest(unittest.TestCase):
    def test_resolves_trace_lines_and_explicit_log_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            central = root / 'logs'
            trace = root / 'task_logs'
            combo = root / 'combo_task_logs'
            for directory in (central, trace, combo):
                directory.mkdir()
            (central / 'app.log').write_text(
                'other line\ntrace-7 started\ntrace-7 finished\n', encoding='utf-8'
            )
            explicit = trace / 'task-7.log'
            explicit.write_text('trace-7 per-file result\n', encoding='utf-8')

            result = TaskLogResolver(
                log_dirs=(central, trace, combo),
            ).resolve('trace-7', explicit_log_path=str(explicit))

            self.assertEqual(result['trace_task_id'], 'trace-7')
            self.assertEqual(len(result['matched_files']), 2)
            self.assertEqual(len(result['lines']), 3)
            self.assertTrue(any('per-file result' in item['text'] for item in result['lines']))
            self.assertEqual(result['errors'], [])

    def test_resolver_limits_lines_and_reports_missing_explicit_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            (log_dir / 'app.log').write_text(
                '\n'.join(f'trace-8 line-{index}' for index in range(5)),
                encoding='utf-8',
            )

            result = TaskLogResolver(log_dirs=(log_dir,)).resolve(
                'trace-8',
                explicit_log_path=str(log_dir / 'missing.log'),
                max_lines=2,
            )

            self.assertEqual(len(result['lines']), 2)
            self.assertTrue(result['truncated'])
            self.assertTrue(any('missing.log' in error for error in result['errors']))


if __name__ == '__main__':
    unittest.main()
