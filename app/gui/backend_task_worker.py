from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from app.gui.i18n import tr


class BackendTaskWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            result = self.task()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class AsyncTaskHostMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _init_async_task_host(self):
        self._async_task_thread = None
        self._async_task_worker = None
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        self._async_busy_widgets = []
        self._async_task_blocks_ui = False
        self._async_task_allows_deferred_close = False
        self._async_close_pending = False

    def is_async_task_running(self):
        return self._async_task_thread is not None

    def set_async_busy_widgets(self, widgets):
        self._async_busy_widgets = list(widgets or [])

    def reload_rows_after(self, operation, load_rows, **payload):
        operation()
        return {
            'rows': load_rows(),
            **payload,
        }

    def start_async_task(
        self,
        task,
        success_handler,
        error_title=None,
        block_ui=True,
        allow_deferred_close=False,
    ):
        if self._async_task_thread is not None:
            return False

        self._async_task_blocks_ui = bool(block_ui)
        self._async_task_allows_deferred_close = bool(allow_deferred_close)
        self._async_close_pending = False
        if self._async_task_blocks_ui:
            self._set_async_busy(True)
        self._async_task_success_handler = success_handler
        self._async_task_error_title = str(error_title or tr('common.operation_failed'))
        self._async_task_thread = QThread(self)
        self._async_task_worker = BackendTaskWorker(task)
        self._async_task_worker.moveToThread(self._async_task_thread)
        self._async_task_thread.started.connect(self._async_task_worker.run)
        self._async_task_worker.finished.connect(self._handle_async_task_finished)
        self._async_task_worker.failed.connect(self._handle_async_task_failed)
        self._async_task_worker.finished.connect(self._async_task_thread.quit)
        self._async_task_worker.failed.connect(self._async_task_thread.quit)
        self._async_task_thread.finished.connect(self._cleanup_async_task_thread)
        self._async_task_thread.start()
        return True

    def _handle_async_task_finished(self, result):
        handler = self._async_task_success_handler
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        if handler is not None:
            handler(result)

    def _handle_async_task_failed(self, message):
        error_title = self._async_task_error_title or tr('common.operation_failed')
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        QMessageBox.critical(self, error_title, str(message or tr('backend_task.unknown_error')))

    def _cleanup_async_task_thread(self):
        if self._async_task_worker is not None:
            self._async_task_worker.deleteLater()
        if self._async_task_thread is not None:
            self._async_task_thread.deleteLater()
        close_pending = bool(self._async_close_pending)
        self._async_task_worker = None
        self._async_task_thread = None
        if self._async_task_blocks_ui:
            self._set_async_busy(False)
        self._async_task_blocks_ui = False
        self._async_task_allows_deferred_close = False
        self._async_close_pending = False
        if close_pending:
            QTimer.singleShot(0, self.close)

    def block_close_while_async_running(self, event, title=None, message=None):
        title = title or tr('common.task_in_progress')
        message = message or tr('common.task_wait')
        if self._async_task_thread and self._async_task_thread.isRunning():
            if self._async_task_allows_deferred_close:
                self._async_close_pending = True
                self.hide()
                event.ignore()
                return True
            QMessageBox.information(self, title, message)
            event.ignore()
            return True
        return False

    def _set_async_busy(self, busy):
        for widget in self._async_busy_widgets:
            if widget is not None:
                widget.setEnabled(not busy)
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
