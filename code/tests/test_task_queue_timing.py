import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.task_queue import (
    TASK_CATEGORY_ENRICHMENT,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PAUSED,
    get_gui_task_queue,
)


_APP = QApplication.instance() or QApplication([])


def _process_events(rounds=5):
    for _ in range(rounds):
        _APP.processEvents()


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TimingPersistence:
    def __init__(self):
        self.records = {}

    def save_gui_task(self, record):
        return record

    def update_gui_task(self, task_id, **changes):
        return changes

    def save_gui_task_timing(self, record):
        self.records[int(record['task_id'])] = dict(record)
        return record

    def update_gui_task_timing(self, task_id, **changes):
        self.records.setdefault(int(task_id), {}).update(changes)
        return self.records[int(task_id)]

    def get_gui_task_timing(self, task_id):
        return self.records.get(int(task_id))


class GuiTaskQueueTimingTest(unittest.TestCase):
    def setUp(self):
        self.queue = get_gui_task_queue()
        self.queue.reset_for_tests()
        self.clock = FakeClock()
        self.persistence = TimingPersistence()
        self.queue.configure_timing_persistence(self.persistence, clock=self.clock)

    def tearDown(self):
        self.queue.reset_for_tests()

    def test_pause_time_is_excluded_and_resume_continues_same_timing_record(self):
        record = self.queue.enqueue(
            '计时任务',
            'test',
            lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            resume_kind='test',
            resumable=True,
        )
        _process_events()
        self.clock.advance(10)

        self.queue.request_pause(record.task_id, '用户暂停')
        self.queue.mark_completed(record.task_id)
        self.assertEqual(self.queue.records()[0].status, TASK_STATUS_PAUSED)
        self.assertAlmostEqual(self.persistence.records[record.task_id]['active_seconds'], 10.0)

        self.clock.advance(20)
        self.assertTrue(self.queue.resume_task(record.task_id))
        _process_events()
        self.clock.advance(5)
        self.queue.mark_completed(record.task_id)

        timing = self.persistence.records[record.task_id]
        self.assertEqual(self.queue.records()[0].status, TASK_STATUS_COMPLETED)
        self.assertAlmostEqual(timing['active_seconds'], 15.0)
        self.assertAlmostEqual(timing['paused_seconds'], 20.0, delta=0.01)
        self.assertEqual(timing['pause_count'], 1)
        self.assertEqual(timing['resume_count'], 1)
        self.assertTrue(timing['ended_at'])

    def test_new_trace_task_does_not_inherit_timing_from_reused_numeric_task_id(self):
        self.persistence.records[1] = {
            'task_id': 1,
            'trace_task_id': 'old-task',
            'active_seconds': 23475.0,
            'paused_seconds': 120.0,
        }

        record = self.queue.enqueue(
            '新任务',
            'test',
            lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            trace_task_id='new-task',
        )

        self.assertEqual(record.task_id, 1)
        self.assertEqual(record.trace_task_id, 'new-task')
        self.assertEqual(record.active_seconds, 0.0)
        self.assertEqual(record.paused_seconds, 0.0)
        self.assertEqual(self.persistence.records[1]['trace_task_id'], 'new-task')
        self.assertEqual(self.persistence.records[1]['active_seconds'], 0.0)

    def test_corrupted_same_trace_timing_is_reset_when_start_is_before_task_creation(self):
        record = self.queue.enqueue(
            '新任务',
            'test',
            lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            trace_task_id='same-trace',
        )
        self.persistence.records[record.task_id].update({
            'started_at': '2000-01-01 00:00:00',
            'active_seconds': 23475.0,
            'trace_task_id': record.trace_task_id,
        })
        self.queue.reset_for_tests()
        self.clock = FakeClock()
        self.queue.configure_timing_persistence(self.persistence, clock=self.clock)

        restored = self.queue.restore_persisted_record({
            **record.__dict__,
            'status': '等待中',
            'started_at': '',
        }, lambda _record: None)
        _process_events()

        self.assertIsNotNone(restored)
        self.assertEqual(restored.active_seconds, 0.0)


if __name__ == '__main__':
    unittest.main()
