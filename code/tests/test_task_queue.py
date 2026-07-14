import os
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QWidget

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.task_queue import (
    RUN_MODE_TASK,
    RUN_MODE_VIEW,
    TASK_CATEGORY_ENRICHMENT,
    TASK_CATEGORY_VIEW,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_PAUSED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING,
    get_gui_task_queue,
)


_APP = QApplication.instance() or QApplication([])


def _process_events(rounds=5):
    for _ in range(rounds):
        _APP.processEvents()


class _AsyncTaskHost(QWidget, AsyncTaskHostMixin):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Test Host')
        self._init_async_task_host()
        self.results = []


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

    def test_view_mode_pauses_enrichment_tasks_until_task_mode_resumes(self):
        started = []
        self.queue.set_run_mode(RUN_MODE_VIEW)

        record = self.queue.enqueue(
            '补全',
            'test',
            lambda task_record: started.append(task_record.task_id),
            task_category=TASK_CATEGORY_ENRICHMENT,
        )
        _process_events()

        self.assertEqual(started, [])
        records = self.queue.records()
        self.assertEqual(records[0].task_id, record.task_id)
        self.assertEqual(records[0].task_category, TASK_CATEGORY_ENRICHMENT)
        self.assertEqual(records[0].status, TASK_STATUS_PAUSED)

        self.queue.set_run_mode(RUN_MODE_TASK)
        _process_events()

        self.assertEqual(started, [record.task_id])
        self.assertEqual(self.queue.records()[0].status, TASK_STATUS_RUNNING)

    def test_view_tasks_still_run_in_view_mode(self):
        started = []
        self.queue.set_run_mode(RUN_MODE_VIEW)

        self.queue.enqueue(
            '查看',
            'test',
            lambda task_record: started.append(task_record.task_id),
            task_category=TASK_CATEGORY_VIEW,
        )
        _process_events()

        self.assertEqual(started, [1])

    def test_start_async_task_can_run_silently_without_queue_record(self):
        host = _AsyncTaskHost()
        try:
            host.start_async_task(
                lambda: {'ok': True},
                host.results.append,
                block_ui=False,
                show_in_task_queue=False,
            )

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                _process_events(5)
                if host.results and not host.is_async_task_running():
                    break

            self.assertEqual(host.results, [{'ok': True}])
            self.assertFalse(host.is_async_task_running())
            self.assertEqual(self.queue.records(), [])
        finally:
            host.deleteLater()

    def test_start_async_task_forwards_task_category_to_queue_record(self):
        host = _AsyncTaskHost()
        try:
            self.queue.set_run_mode(RUN_MODE_VIEW)

            host.start_async_task(
                lambda: {'ok': True},
                host.results.append,
                block_ui=False,
                task_category=TASK_CATEGORY_ENRICHMENT,
                task_kind='queen_crawl',
            )
            _process_events()

            records = self.queue.records()
            self.assertEqual(records[0].task_category, TASK_CATEGORY_ENRICHMENT)
            self.assertEqual(records[0].task_kind, 'queen_crawl')
            self.assertEqual(records[0].status, TASK_STATUS_PAUSED)
        finally:
            host.deleteLater()

    def test_start_async_task_forwards_max_attempts_to_queue_record(self):
        host = _AsyncTaskHost()
        try:
            host.start_async_task(
                lambda: {'ok': True},
                host.results.append,
                block_ui=False,
                max_attempts=1,
            )
            _process_events()

            records = self.queue.records()
            self.assertEqual(records[0].max_attempts, 1)
        finally:
            host.deleteLater()

    def test_plan_progress_is_kept_on_queue_record_and_can_be_updated(self):
        record = self.queue.enqueue(
            '计划补全',
            '主界面',
            lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            task_kind='video',
            plan_id='plan-1',
            plan_progress={
                'completed_batch_count': 1,
                'batch_count_limit': 3,
                'pending_count': 4,
                'success_count': 2,
                'failed_count': 1,
                'paused_reason': '网络异常',
            },
        )
        self.queue.update_plan_progress('plan-1', {'completed_batch_count': 2, 'pending_count': 3})

        current = self.queue.records()[0]
        self.assertEqual(current.plan_id, record.plan_id)
        self.assertEqual(current.batch_current, 2)
        self.assertEqual(current.batch_total, 3)
        self.assertEqual(current.plan_pending_count, 3)
        self.assertEqual(current.plan_success_count, 2)
        self.assertEqual(current.plan_failed_count, 1)
        self.assertEqual(current.pause_reason, '网络异常')

    def test_pause_request_keeps_runner_for_later_resume(self):
        started = []
        self.queue.enqueue(
            '计划补全',
            '主界面',
            lambda record: started.append(record.task_id),
            task_category=TASK_CATEGORY_ENRICHMENT,
            plan_id='plan-1',
        )
        _process_events()
        record = self.queue.records()[0]
        self.queue.request_pause(record.task_id, '切换查看模式')
        self.queue.mark_completed(record.task_id)
        self.assertEqual(self.queue.records()[0].status, TASK_STATUS_PAUSED)
        self.queue.set_run_mode(RUN_MODE_VIEW)
        self.queue.set_run_mode(RUN_MODE_TASK)
        _process_events()
        self.assertEqual(started, [record.task_id, record.task_id])


if __name__ == '__main__':
    unittest.main()
