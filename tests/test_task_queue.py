import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.task_queue import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING,
    get_gui_task_queue,
)


_APP = QApplication.instance() or QApplication([])


def _process_events():
    for _ in range(5):
        _APP.processEvents()


class GuiTaskQueueTest(unittest.TestCase):
    def setUp(self):
        self.queue = get_gui_task_queue()
        self.queue.reset_for_tests()

    def tearDown(self):
        self.queue.reset_for_tests()

    def test_runs_one_task_at_a_time_and_keeps_fifo_order(self):
        started = []
        first = self.queue.enqueue('first', 'test', lambda record: started.append(record.task_id))
        second = self.queue.enqueue('second', 'test', lambda record: started.append(record.task_id))

        _process_events()

        self.assertEqual(started, [first.task_id])
        records = self.queue.records()
        self.assertEqual(records[0].status, TASK_STATUS_RUNNING)
        self.assertEqual(records[1].status, TASK_STATUS_WAITING)

        self.queue.mark_completed(first.task_id)
        _process_events()

        self.assertEqual(started, [first.task_id, second.task_id])
        records = self.queue.records()
        self.assertEqual(records[0].status, TASK_STATUS_COMPLETED)
        self.assertEqual(records[1].status, TASK_STATUS_RUNNING)

    def test_failed_task_moves_to_queue_tail_until_retry_limit(self):
        started = []
        first = self.queue.enqueue('first', 'test', lambda record: started.append(('first', record.attempts)), max_attempts=2)
        second = self.queue.enqueue('second', 'test', lambda record: started.append(('second', record.attempts)))

        _process_events()
        self.queue.mark_failed(first.task_id, 'boom')
        _process_events()

        self.assertEqual(started, [('first', 1), ('second', 1)])
        records = self.queue.records()
        self.assertEqual(records[0].status, TASK_STATUS_WAITING)
        self.assertEqual(records[0].last_error, 'boom')

        self.queue.mark_completed(second.task_id)
        _process_events()

        self.assertEqual(started, [('first', 1), ('second', 1), ('first', 2)])
        final_failure = self.queue.mark_failed(first.task_id, 'boom again')
        self.assertTrue(final_failure)

        records = self.queue.records()
        self.assertEqual(records[0].status, TASK_STATUS_COMPLETED)
        self.assertTrue(records[0].exhausted)
        self.assertEqual(records[0].last_error, 'boom again')

    def test_is_all_done_only_when_no_waiting_or_running_tasks_remain(self):
        self.assertTrue(self.queue.is_all_done())

        first = self.queue.enqueue('first', 'test', lambda _record: None)
        second = self.queue.enqueue('second', 'test', lambda _record: None)

        _process_events()

        self.assertFalse(self.queue.is_all_done())
        self.queue.mark_completed(first.task_id)
        _process_events()
        self.assertFalse(self.queue.is_all_done())
        self.queue.mark_completed(second.task_id)

        self.assertTrue(self.queue.is_all_done())


if __name__ == '__main__':
    unittest.main()
