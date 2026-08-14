import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.task_queue import get_gui_task_queue
from app.gui.task_queue import TASK_CATEGORY_ENRICHMENT
from app.gui.task_queue import TASK_STATUS_PAUSED
from app.gui.task_queue_viewer import TaskQueueViewerWindow


_APP = QApplication.instance() or QApplication([])


class TaskQueueViewerWindowTest(unittest.TestCase):
    def setUp(self):
        self.queue = get_gui_task_queue()
        self.queue.reset_for_tests()

    def tearDown(self):
        self.queue.reset_for_tests()

    def test_pause_button_pauses_selected_running_task(self):
        self.queue.enqueue(
            'pause me', 'test', lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            resume_kind='test',
            resume_payload={'value': 1},
            resumable=True,
        )
        _APP.processEvents()
        viewer = TaskQueueViewerWindow()
        try:
            viewer.table.selectRow(0)
            viewer.refresh_rows()
            self.assertEqual(viewer.btn_pause_resume.text(), '暂停')
            viewer.pause_resume_selected_tasks()
            self.assertTrue(viewer.task_queue.records()[0].pause_requested)
        finally:
            viewer.deleteLater()

    def test_resume_button_resumes_selected_paused_task(self):
        record = self.queue.enqueue(
            'resume me', 'test', lambda _record: None,
            task_category=TASK_CATEGORY_ENRICHMENT,
            resume_kind='test',
            resume_payload={'value': 1},
            resumable=True,
        )
        _APP.processEvents()
        self.queue.request_pause(record.task_id, '用户暂停')
        self.queue.mark_completed(record.task_id)
        viewer = TaskQueueViewerWindow()
        try:
            viewer.table.selectRow(0)
            viewer.refresh_rows()
            self.assertEqual(viewer.task_queue.records()[0].status, TASK_STATUS_PAUSED)
            self.assertEqual(viewer.btn_pause_resume.text(), '继续')
            viewer.pause_resume_selected_tasks()
            self.assertEqual(viewer.task_queue.records()[0].status, '等待中')
        finally:
            viewer.deleteLater()

    def test_summary_turns_green_when_all_tasks_are_done(self):
        viewer = TaskQueueViewerWindow()
        try:
            self.queue.enqueue('first', 'test', lambda _record: None)
            _APP.processEvents()
            viewer.refresh_rows()

            self.assertNotIn('#16a34a', viewer.summary_label.styleSheet())

            running = self.queue.records()[0]
            self.queue.mark_completed(running.task_id)
            _APP.processEvents()
            viewer.refresh_rows()

            self.assertIn('#16a34a', viewer.summary_label.styleSheet())
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_completed_rows_are_green_and_exhausted_failed_rows_are_red(self):
        viewer = TaskQueueViewerWindow()
        try:
            success = self.queue.enqueue('success', 'test', lambda _record: None)
            _APP.processEvents()
            self.queue.mark_completed(success.task_id)

            failed = self.queue.enqueue('failed', 'test', lambda _record: None, max_attempts=1)
            _APP.processEvents()
            self.queue.mark_failed(failed.task_id, 'boom')
            _APP.processEvents()
            viewer.refresh_rows()

            self.assertEqual(viewer.table.item(0, 1).foreground().color().name(), '#16a34a')
            self.assertEqual(viewer.table.item(1, 1).foreground().color().name(), '#dc2626')
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_rows_show_task_category(self):
        viewer = TaskQueueViewerWindow()
        try:
            self.queue.enqueue(
                '补全',
                'test',
                lambda _record: None,
                task_category=TASK_CATEGORY_ENRICHMENT,
            )
            _APP.processEvents()
            viewer.refresh_rows()

            self.assertEqual(viewer.table.horizontalHeaderItem(3).text(), '分类')
            self.assertEqual(viewer.table.item(0, 3).text(), TASK_CATEGORY_ENRICHMENT)
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_rows_show_global_trace_task_id(self):
        viewer = TaskQueueViewerWindow()
        try:
            self.queue.enqueue('字幕任务', 'test', lambda _record: None, trace_task_id='task-subtitle-001')
            _APP.processEvents()
            viewer.refresh_rows()

            self.assertEqual(viewer.table.horizontalHeaderItem(1).text(), '追踪ID')
            self.assertEqual(viewer.table.item(0, 1).text(), 'task-subtitle-001')
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_rows_show_formatted_effective_duration(self):
        viewer = TaskQueueViewerWindow()
        try:
            self.queue.enqueue('计时任务', 'test', lambda _record: None)
            _APP.processEvents()
            record = self.queue._records[0]
            record.active_seconds = 3723.5
            viewer.refresh_rows()

            self.assertEqual(viewer.table.horizontalHeaderItem(14).text(), '耗时')
            self.assertEqual(viewer.table.item(0, 14).text(), '01:02:03')
        finally:
            viewer.close()
            viewer.deleteLater()

    def test_delete_selected_button_cancels_selected_waiting_task(self):
        viewer = TaskQueueViewerWindow()
        try:
            first = self.queue.enqueue('first', 'test', lambda _record: None)
            second = self.queue.enqueue('second', 'test', lambda _record: None)
            _APP.processEvents()
            viewer.refresh_rows()
            viewer.table.selectRow(1)
            viewer.confirm_delete = lambda _records: True

            self.assertTrue(viewer.btn_delete_selected.isEnabled())
            viewer.delete_selected_tasks()
            _APP.processEvents()

            self.assertEqual(self.queue.records()[0].task_id, first.task_id)
            self.assertEqual(self.queue.records()[1].status, '已删除')
        finally:
            viewer.close()
            viewer.deleteLater()


if __name__ == '__main__':
    unittest.main()
