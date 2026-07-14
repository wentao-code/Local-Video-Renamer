import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.task_queue import get_gui_task_queue
from app.gui.task_queue import TASK_CATEGORY_ENRICHMENT
from app.gui.task_queue_viewer import TaskQueueViewerWindow


_APP = QApplication.instance() or QApplication([])


class TaskQueueViewerWindowTest(unittest.TestCase):
    def setUp(self):
        self.queue = get_gui_task_queue()
        self.queue.reset_for_tests()

    def tearDown(self):
        self.queue.reset_for_tests()

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

            self.assertEqual(viewer.table.horizontalHeaderItem(2).text(), '分类')
            self.assertEqual(viewer.table.item(0, 2).text(), TASK_CATEGORY_ENRICHMENT)
        finally:
            viewer.close()
            viewer.deleteLater()


if __name__ == '__main__':
    unittest.main()
