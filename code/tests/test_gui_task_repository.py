import json
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_sources import SUPPLEMENT_TASK_SOURCE
from app.data.database_handler import VideoDatabase


class GuiTaskRepositoryTest(unittest.TestCase):
    def test_persists_task_payload_and_updates_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'video.db')
            record = database.save_gui_task({
                'task_id': 7,
                'trace_task_id': 'task-trace-7',
                'title': '字幕生成与封装 AAA-001',
                'source': '主界面',
                'task_category': '查看任务',
                'task_kind': 'subtitle_pipeline',
                'log_path': 'D:/runtime/task_logs/subtitle-AAA-001.log',
                'status': '等待中',
                'resume_kind': 'subtitle_pipeline_video',
                'resume_payload': {'input_dir': 'D:/videos', 'video_code': 'AAA-001'},
                'resumable': True,
                'max_attempts': 3,
                'batch_current': 2,
                'batch_total': 5,
                'plan_pending_count': 8,
            })

            self.assertEqual(record['task_id'], 7)
            self.assertTrue(record['resumable'])
            self.assertEqual(record['batch_current'], 2)
            self.assertEqual(record['batch_total'], 5)
            self.assertEqual(record['plan_pending_count'], 8)
            self.assertEqual(record['log_path'], 'D:/runtime/task_logs/subtitle-AAA-001.log')
            stored = database.list_gui_tasks()[0]
            self.assertEqual(stored['log_path'], 'D:/runtime/task_logs/subtitle-AAA-001.log')
            self.assertEqual(
                record['resume_payload'],
                {'input_dir': 'D:/videos', 'video_code': 'AAA-001'},
            )

            updated = database.update_gui_task(
                7,
                status='已暂停',
                pause_reason='用户暂停',
                attempts=1,
                resume_payload_json={'video_code': 'AAA-001', 'input_dir': 'D:/videos'},
            )

            self.assertEqual(updated['status'], '已暂停')
            self.assertEqual(updated['pause_reason'], '用户暂停')
            self.assertEqual(updated['attempts'], 1)
            self.assertEqual(updated['resume_payload'], {'video_code': 'AAA-001', 'input_dir': 'D:/videos'})
            self.assertEqual(database.list_gui_tasks(statuses=['已暂停'])[0]['task_id'], 7)

    def test_marks_stale_running_tasks_paused_without_touching_completed_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'video.db')
            for task_id, status in ((1, '正在执行'), (2, '已完成'), (3, 'running')):
                database.save_gui_task({
                    'task_id': task_id,
                    'trace_task_id': f'task-trace-{task_id}',
                    'title': f'task-{task_id}',
                    'source': 'test',
                    'status': status,
                    'resume_kind': 'subtitle_pipeline_video' if task_id in {1, 3} else '',
                    'resume_payload': {'video_code': 'AAA-001'} if task_id in {1, 3} else {},
                    'resumable': task_id in {1, 3},
                })

            changed = database.mark_running_gui_tasks_paused('应用重启时中断')

            self.assertEqual(changed, 2)
            rows = {row['task_id']: row for row in database.list_gui_tasks()}
            self.assertEqual(rows[1]['status'], '已暂停')
            self.assertEqual(rows[1]['pause_reason'], '应用重启时中断')
            self.assertEqual(rows[2]['status'], '已完成')
            self.assertEqual(rows[3]['status'], '已暂停')

    def test_completed_plan_reconciles_legacy_running_gui_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'video.db')
            plan = database.create_enrichment_batch_plan(
                'video', 'video_library', SUPPLEMENT_TASK_SOURCE, 1, 1,
                candidates=[{'code': 'AAA-001'}],
            )
            database.finish_enrichment_batch_plan(plan['plan_id'], 'completed')
            database.save_gui_task({
                'task_id': 9,
                'trace_task_id': 'task-trace-9',
                'title': '遗留补全任务',
                'source': 'test',
                'status': 'running',
                'plan_id': plan['plan_id'],
            })

            changed = database.reconcile_terminal_enrichment_gui_tasks()

            self.assertEqual(changed, 1)
            row = database.get_gui_task(9)
            self.assertEqual(row['status'], '已完成')
            self.assertTrue(row['completed_at'])


if __name__ == '__main__':
    unittest.main()
