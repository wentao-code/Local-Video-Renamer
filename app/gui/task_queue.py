from dataclasses import dataclass
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


TASK_STATUS_WAITING = '等待中'
TASK_STATUS_RUNNING = '正在执行'
TASK_STATUS_PAUSED = '已暂停'
TASK_STATUS_COMPLETED = '已完成'

RUN_MODE_VIEW = 'view'
RUN_MODE_TASK = 'task'

TASK_CATEGORY_VIEW = '查看任务'
TASK_CATEGORY_ENRICHMENT = '补全任务'
TASK_CATEGORY_MAINTENANCE = '维护任务'

PAUSABLE_TASK_CATEGORIES = {
    TASK_CATEGORY_ENRICHMENT,
    TASK_CATEGORY_MAINTENANCE,
}


def _now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


@dataclass
class TaskRecord:
    task_id: int
    title: str
    source: str
    task_category: str = TASK_CATEGORY_VIEW
    task_kind: str = ''
    status: str = TASK_STATUS_WAITING
    attempts: int = 0
    max_attempts: int = 5
    created_at: str = ''
    started_at: str = ''
    completed_at: str = ''
    last_error: str = ''
    exhausted: bool = False


class GuiTaskQueue(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._records = []
        self._waiting_records = []
        self._start_callbacks = {}
        self._running_task_id = None
        self._next_task_id = 1
        self._run_mode = RUN_MODE_TASK

    def enqueue(self, title, source, start_callback, max_attempts=5, task_category=TASK_CATEGORY_VIEW, task_kind=''):
        record = TaskRecord(
            task_id=self._next_task_id,
            title=str(title or '后台任务'),
            source=str(source or ''),
            task_category=str(task_category or TASK_CATEGORY_VIEW).strip() or TASK_CATEGORY_VIEW,
            task_kind=str(task_kind or '').strip(),
            max_attempts=max(1, int(max_attempts or 1)),
            created_at=_now_text(),
        )
        self._next_task_id += 1
        self._records.append(record)
        self._waiting_records.append(record)
        self._start_callbacks[record.task_id] = start_callback
        self.changed.emit()
        self._schedule_start_next()
        return record

    def run_mode(self):
        return self._run_mode

    def set_run_mode(self, run_mode):
        normalized_mode = RUN_MODE_VIEW if str(run_mode or '').strip() == RUN_MODE_VIEW else RUN_MODE_TASK
        if self._run_mode == normalized_mode:
            return
        self._run_mode = normalized_mode
        if normalized_mode == RUN_MODE_TASK:
            for record in self._waiting_records:
                if record.status == TASK_STATUS_PAUSED:
                    record.status = TASK_STATUS_WAITING
            self._schedule_start_next()
        else:
            for record in self._waiting_records:
                if self._should_pause_record(record):
                    record.status = TASK_STATUS_PAUSED
        self.changed.emit()

    def mark_completed(self, task_id):
        record = self._find_record(task_id)
        if record is None:
            return
        record.status = TASK_STATUS_COMPLETED
        record.completed_at = _now_text()
        if self._running_task_id == task_id:
            self._running_task_id = None
        self._start_callbacks.pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()

    def mark_failed(self, task_id, error_message):
        record = self._find_record(task_id)
        if record is None:
            return True
        record.last_error = str(error_message or '')
        if self._running_task_id == task_id:
            self._running_task_id = None
        if record.attempts < record.max_attempts:
            record.status = TASK_STATUS_WAITING
            self._waiting_records.append(record)
            self.changed.emit()
            self._schedule_start_next()
            return False
        record.status = TASK_STATUS_COMPLETED
        record.completed_at = _now_text()
        record.exhausted = True
        self._start_callbacks.pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()
        return True

    def records(self):
        return [TaskRecord(**record.__dict__) for record in self._records]

    def is_all_done(self):
        if not self._records:
            return True
        if self._running_task_id is not None:
            return False
        if self._waiting_records:
            return False
        return all(record.status == TASK_STATUS_COMPLETED for record in self._records)

    def reset_for_tests(self):
        self._records.clear()
        self._waiting_records.clear()
        self._start_callbacks.clear()
        self._running_task_id = None
        self._next_task_id = 1
        self._run_mode = RUN_MODE_TASK
        self.changed.emit()

    def _schedule_start_next(self):
        QTimer.singleShot(0, self._start_next)

    def _start_next(self):
        if self._running_task_id is not None:
            return
        if not self._waiting_records:
            return
        record = self._waiting_records.pop(0)
        if self._should_pause_record(record):
            record.status = TASK_STATUS_PAUSED
            self._waiting_records.insert(0, record)
            self.changed.emit()
            return
        callback = self._start_callbacks.get(record.task_id)
        if callback is None:
            self._schedule_start_next()
            return
        record.status = TASK_STATUS_RUNNING
        record.attempts += 1
        record.started_at = _now_text()
        self._running_task_id = record.task_id
        self.changed.emit()
        try:
            callback(record)
        except Exception as exc:
            self.mark_failed(record.task_id, str(exc))

    def _should_pause_record(self, record):
        return (
            self._run_mode == RUN_MODE_VIEW
            and str(getattr(record, 'task_category', '') or '').strip() in PAUSABLE_TASK_CATEGORIES
        )

    def _find_record(self, task_id):
        for record in self._records:
            if record.task_id == task_id:
                return record
        return None


_GLOBAL_TASK_QUEUE = GuiTaskQueue()


def get_gui_task_queue():
    return _GLOBAL_TASK_QUEUE
