import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.task_queue import get_gui_task_queue
from app.gui.task_resume_registry import TaskResumeRegistry


_APP = QApplication.instance() or QApplication([])


class TaskPersistenceStartupTest(unittest.TestCase):
    def setUp(self):
        self.queue = get_gui_task_queue()
        self.queue.reset_for_tests()

    def tearDown(self):
        self.queue.reset_for_tests()

    def test_restart_recovers_paused_resumable_task_and_continue_runs_it(self):
        rows = [{
            'task_id': 42,
            'trace_task_id': 'task-42',
            'title': '可恢复任务',
            'source': 'test',
            'status': '正在执行',
            'attempts': 1,
            'max_attempts': 3,
            'resume_kind': 'test',
            'resume_payload': {'value': 'resume'},
            'resumable': True,
        }]
        updates = []

        class Persistence:
            def mark_running_gui_tasks_paused(self, reason):
                for row in rows:
                    if row['status'] == '正在执行':
                        row['status'] = '已暂停'
                        row['pause_reason'] = reason
                return 1

            def list_gui_tasks(self, statuses=None):
                return [row for row in rows if not statuses or row['status'] in statuses]

            def update_gui_task(self, task_id, **changes):
                updates.append((task_id, changes))

            def save_gui_task(self, record):
                return record

        started = []
        registry = TaskResumeRegistry()
        registry.register('test', lambda payload, _host: lambda _record: started.append(payload['value']))
        restored = registry.recover_persisted_tasks(self.queue, Persistence(), object())

        self.assertEqual([record.task_id for record in restored], [42])
        self.assertEqual(self.queue.records()[0].status, '已暂停')
        self.assertTrue(self.queue.resume_task(42))
        _APP.processEvents()

        self.assertEqual(started, ['resume'])
        self.assertEqual(self.queue.records()[0].status, '正在执行')
        self.assertEqual(updates, [])


if __name__ == '__main__':
    unittest.main()
