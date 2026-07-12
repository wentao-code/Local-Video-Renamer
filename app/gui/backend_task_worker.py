from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from app.gui.i18n import tr
from app.gui.task_queue import get_gui_task_queue


def enable_minimize_button(widget, detach_parent=True):
    if widget is None or not hasattr(widget, 'windowFlags'):
        return
    if detach_parent and hasattr(widget, 'parent') and widget.parent() is not None:
        widget.setParent(None)
    widget.setWindowFlags(
        widget.windowFlags()
        | Qt.WindowSystemMenuHint
        | Qt.WindowMinimizeButtonHint
    )


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
        enable_minimize_button(self)
        self._async_task_thread = None
        self._async_task_worker = None
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        self._async_busy_widgets = []
        self._async_task_blocks_ui = False
        self._async_task_allows_deferred_close = False
        self._async_close_pending = False
        self._async_task_queue_record = None
        self._async_task_failed_message = None

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
        task_title=None,
        show_in_task_queue=True,
    ):
        queue_task_title = self._build_async_task_title(
            error_title=error_title,
            success_handler=success_handler,
            task_title=task_title,
        )

        def start_task(record=None):
            if self._async_task_thread is not None:
                if record is not None:
                    get_gui_task_queue().mark_failed(record.task_id, tr('common.task_in_progress'))
                return
            self._async_task_queue_record = record
            self._async_task_failed_message = None
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

        if not show_in_task_queue:
            start_task()
            return True

        get_gui_task_queue().enqueue(queue_task_title, self._async_task_source_name(), start_task)
        return True

    def _build_async_task_title(self, error_title=None, success_handler=None, task_title=None):
        window_title = self._async_task_source_name()
        explicit_title = str(task_title or '').strip()
        if explicit_title:
            return explicit_title
        action_name = self._infer_async_task_action(success_handler)
        if action_name:
            return f'{window_title} {action_name}'
        title = str(error_title or '').strip()
        if title == tr('common.read_failed'):
            return f'{window_title} 读取数据'
        if title in ('', tr('common.operation_failed'), tr('common.prompt')):
            return f'{window_title} 后台任务'
        if title.endswith('失败'):
            action_name = title[:-2].strip()
            if action_name:
                return f'{window_title} {action_name}任务'
        return f'{window_title} 后台任务'

    def _infer_async_task_action(self, success_handler=None):
        handler_name = str(getattr(success_handler, '__name__', '') or '').lower()
        if not handler_name:
            return ''
        action_patterns = [
            ('load', '读取数据'),
            ('refresh', '刷新数据'),
            ('scan', '扫描本地视频'),
            ('import', '导入数据库'),
            ('execute_rename', '执行重命名'),
            ('rename', '修改名称'),
            ('add', '添加数据'),
            ('delete', '删除数据'),
            ('reset', '重置数据'),
            ('sync', '同步数据'),
            ('search', '搜索数据'),
            ('crawl', '抓取数据'),
            ('enrich', '补全数据'),
            ('admit', '入选数据'),
            ('stage', '暂存数据'),
            ('batch_stage', '批量暂存数据'),
        ]
        for pattern, action_name in action_patterns:
            if pattern in handler_name:
                return action_name
        return ''

    def _async_task_source_name(self):
        if hasattr(self, 'windowTitle'):
            title = str(self.windowTitle() or '').strip()
            if title:
                return title
        return self.__class__.__name__

    def _handle_async_task_finished(self, result):
        handler = self._async_task_success_handler
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        if handler is not None:
            handler(result)

    def _handle_async_task_failed(self, message):
        self._async_task_failed_message = str(message or tr('backend_task.unknown_error'))

    def _cleanup_async_task_thread(self):
        if self._async_task_worker is not None:
            self._async_task_worker.deleteLater()
        if self._async_task_thread is not None:
            self._async_task_thread.deleteLater()
        close_pending = bool(self._async_close_pending)
        failed_message = self._async_task_failed_message
        error_title = self._async_task_error_title or tr('common.operation_failed')
        queue_record = self._async_task_queue_record
        self._async_task_success_handler = None
        self._async_task_error_title = ''
        self._async_task_worker = None
        self._async_task_thread = None
        if self._async_task_blocks_ui:
            self._set_async_busy(False)
        self._async_task_blocks_ui = False
        self._async_task_allows_deferred_close = False
        self._async_close_pending = False
        self._async_task_failed_message = None
        self._async_task_queue_record = None
        if queue_record is not None:
            if failed_message:
                final_failure = get_gui_task_queue().mark_failed(queue_record.task_id, failed_message)
                if final_failure:
                    QMessageBox.critical(self, error_title, failed_message)
            else:
                get_gui_task_queue().mark_completed(queue_record.task_id)
        if close_pending and not failed_message:
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
