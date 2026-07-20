import tempfile
import unittest
from pathlib import Path

from app.services.enrichment.task_trace_logger import TaskTraceLogger


class TaskTraceLoggerTest(unittest.TestCase):
    def test_log_phase_writes_phase_and_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = TaskTraceLogger(
                'single',
                'actor_library_supplement',
                '演员补充',
                log_dir=Path(temp_dir),
            )

            logger.log_phase('claim', 'completed', claimed_count=3)
            content = logger.log_path.read_text(encoding='utf-8')

        self.assertIn('阶段日志', content)
        self.assertIn('phase=claim', content)
        self.assertIn('phase_status=completed', content)
        self.assertIn('claimed_count=3', content)
