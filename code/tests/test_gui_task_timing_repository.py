import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.data.database_handler import VideoDatabase


class GuiTaskTimingRepositoryTest(unittest.TestCase):
    def test_saves_and_filters_timing_records_by_task_category(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'video.db')
            database.save_gui_task_timing({
                'task_id': 11,
                'trace_task_id': 'trace-11',
                'task_category': '补全任务',
                'title': '补全 AAA-001',
                'status': '正在执行',
                'started_at': '2026-08-14 10:00:00',
                'last_resumed_at': '2026-08-14 10:00:00',
                'active_seconds': 12.5,
                'paused_seconds': 3.0,
                'pause_count': 1,
                'resume_count': 1,
            })
            database.save_gui_task_timing({
                'task_id': 12,
                'trace_task_id': 'trace-12',
                'task_category': '字幕任务',
                'title': '字幕 BBB-002',
                'status': '已完成',
                'active_seconds': 8.0,
            })

            record = database.get_gui_task_timing(11)
            self.assertEqual(record['task_category'], '补全任务')
            self.assertEqual(record['active_seconds'], 12.5)
            self.assertEqual(record['paused_seconds'], 3.0)
            self.assertEqual(record['pause_count'], 1)
            self.assertEqual(
                [row['task_id'] for row in database.list_gui_task_timings('字幕任务')],
                [12],
            )

            updated = database.update_gui_task_timing(
                11,
                status='已暂停',
                active_seconds=18.25,
                paused_seconds=4.5,
                close_reason='用户暂停',
            )
            self.assertEqual(updated['status'], '已暂停')
            self.assertEqual(updated['active_seconds'], 18.25)
            self.assertEqual(updated['close_reason'], '用户暂停')

    def test_marks_stale_running_timing_records_paused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'video.db')
            database.save_gui_task_timing({
                'task_id': 21,
                'task_category': '字幕任务',
                'status': '正在执行',
                'started_at': '2026-08-14 10:00:00',
                'last_resumed_at': '2026-08-14 10:00:00',
            })

            self.assertEqual(database.mark_running_gui_task_timings_paused('应用重启时中断'), 1)
            timing = database.get_gui_task_timing(21)
            self.assertEqual(timing['status'], '已暂停')
            self.assertEqual(timing['close_reason'], '应用重启时中断')
            self.assertTrue(timing['paused_at'])

            paused_at = datetime.strptime(timing['paused_at'], '%Y-%m-%d %H:%M:%S')
            elapsed = abs((datetime.now() - paused_at).total_seconds())
            self.assertLess(elapsed, 5)


if __name__ == '__main__':
    unittest.main()
