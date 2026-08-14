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


if __name__ == '__main__':
    unittest.main()
