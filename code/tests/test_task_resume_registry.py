import unittest
from types import SimpleNamespace

from app.gui.task_resume_registry import TaskResumeRegistry


class TaskResumeRegistryTest(unittest.TestCase):
    def test_builds_callback_from_registered_kind_and_payload(self):
        registry = TaskResumeRegistry()
        captured = []
        registry.register(
            'test',
            lambda payload, host: lambda: captured.append((payload, host)),
        )
        record = SimpleNamespace(
            resume_kind='test',
            resume_payload={'video_code': 'AAA-001'},
        )

        callback = registry.build(record, 'host')
        callback()

        self.assertEqual(captured, [({'video_code': 'AAA-001'}, 'host')])

    def test_unknown_kind_and_invalid_payload_are_not_buildable(self):
        registry = TaskResumeRegistry()
        self.assertIsNone(TaskResumeRegistry().build(SimpleNamespace(resume_kind='missing'), None))
        registry.register('test', lambda payload, host: lambda: None)
        self.assertIsNone(registry.build(SimpleNamespace(resume_kind='test', resume_payload='bad'), None))

    def test_recover_marks_unknown_tasks_non_resumable(self):
        updates = []

        class Persistence:
            def mark_running_gui_tasks_paused(self, reason):
                return 0

            def list_gui_tasks(self, statuses=None):
                return [{
                    'task_id': 7,
                    'status': '已暂停',
                    'title': 'unknown',
                    'resumable': True,
                    'resume_kind': 'missing',
                    'resume_payload': {},
                }]

            def update_gui_task(self, task_id, **changes):
                updates.append((task_id, changes))

        class Queue:
            def contains_task(self, task_id):
                return False

            def restore_persisted_record(self, record, callback):
                raise AssertionError('unknown task must not be restored')

        restored = TaskResumeRegistry().recover_persisted_tasks(Queue(), Persistence(), object())

        self.assertEqual(restored, [])
        self.assertEqual(updates[0][0], 7)
        self.assertEqual(updates[0][1]['status'], '不可恢复')
        self.assertIn('未注册', updates[0][1]['non_resumable_reason'])


if __name__ == '__main__':
    unittest.main()
