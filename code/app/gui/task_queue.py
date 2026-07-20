from dataclasses import dataclass, field
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


TASK_STATUS_WAITING = '等待中'
TASK_STATUS_RUNNING = '正在执行'
TASK_STATUS_PAUSED = '已暂停'
TASK_STATUS_CANCELLING = '取消中'
TASK_STATUS_COMPLETED = '已完成'
TASK_STATUS_PARTIAL = '部分完成'
TASK_STATUS_DELETED = '已删除'

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
    partial: bool = False
    plan_id: str = ''
    plan_task_kind: str = ''
    batch_current: int = 0
    batch_total: int = 0
    plan_pending_count: int = 0
    plan_success_count: int = 0
    plan_failed_count: int = 0
    pause_reason: str = ''
    last_run_id: str = ''
    last_run_result: dict = field(default_factory=dict)
    pause_requested: bool = False


class GuiTaskQueue(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._records = []
        self._waiting_records = []
        self._start_callbacks = {}
        self._cancel_callbacks = {}
        self._running_task_id = None
        self._next_task_id = 1
        self._run_mode = RUN_MODE_TASK

    def enqueue(
        self,
        title,
        source,
        start_callback,
        max_attempts=5,
        task_category=TASK_CATEGORY_VIEW,
        task_kind='',
        plan_id='',
        plan_progress=None,
        cancel_callback=None,
    ):
        record = TaskRecord(
            task_id=self._next_task_id,
            title=str(title or '后台任务'),
            source=str(source or ''),
            task_category=str(task_category or TASK_CATEGORY_VIEW).strip() or TASK_CATEGORY_VIEW,
            task_kind=str(task_kind or '').strip(),
            max_attempts=max(1, int(max_attempts or 1)),
            created_at=_now_text(),
            plan_id=str(plan_id or '').strip(),
            plan_task_kind=str(task_kind or '').strip(),
        )
        self._apply_plan_progress(record, plan_progress)
        self._next_task_id += 1
        self._records.append(record)
        self._waiting_records.append(record)
        self._start_callbacks[record.task_id] = start_callback
        if cancel_callback is not None:
            if not hasattr(self, '_cancel_callbacks'):
                self._cancel_callbacks = {}
            self._cancel_callbacks[record.task_id] = cancel_callback
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
                    record.pause_reason = ''
            self._schedule_start_next()
        else:
            for record in self._waiting_records:
                if self._should_pause_record(record):
                    record.status = TASK_STATUS_PAUSED
                    record.pause_reason = '查看模式'
        self.changed.emit()

    def mark_completed(self, task_id):
        record = self._find_record(task_id)
        if record is None:
            return
        if record.status in {TASK_STATUS_DELETED, TASK_STATUS_CANCELLING}:
            return
        if record.pause_requested:
            record.status = TASK_STATUS_PAUSED
            record.pause_requested = False
            if not any(item.task_id == task_id for item in self._waiting_records):
                self._waiting_records.insert(0, record)
            if self._running_task_id == task_id:
                self._running_task_id = None
            self.changed.emit()
            self._schedule_start_next()
            return
        record.status = TASK_STATUS_COMPLETED
        record.completed_at = _now_text()
        if self._running_task_id == task_id:
            self._running_task_id = None
        self._start_callbacks.pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()

    def mark_partial(self, task_id, error_message):
        record = self._find_record(task_id)
        if record is None:
            return
        record.status = TASK_STATUS_PARTIAL
        record.partial = True
        record.last_error = str(error_message or '')
        record.completed_at = _now_text()
        if self._running_task_id == task_id:
            self._running_task_id = None
        self._start_callbacks.pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()

    def mark_failed(self, task_id, error_message, retryable=True):
        record = self._find_record(task_id)
        if record is None:
            return True
        if record.status in {TASK_STATUS_DELETED, TASK_STATUS_CANCELLING}:
            return False
        record.last_error = str(error_message or '')
        if self._running_task_id == task_id:
            self._running_task_id = None
        if retryable and record.attempts < record.max_attempts:
            record.status = TASK_STATUS_WAITING
            self._waiting_records.append(record)
            self.changed.emit()
            self._schedule_start_next()
            return False
        record.status = TASK_STATUS_COMPLETED
        record.completed_at = _now_text()
        record.exhausted = True
        self._start_callbacks.pop(task_id, None)
        getattr(self, '_cancel_callbacks', {}).pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()
        return True

    def retry_later(self, task_id, error_message, delay_ms=20000):
        """Return a transiently blocked task to the queue without counting a failure."""
        record = self._find_record(task_id)
        if record is None or record.status in {TASK_STATUS_DELETED, TASK_STATUS_CANCELLING}:
            return False
        record.status = TASK_STATUS_WAITING
        record.last_error = str(error_message or '').strip()
        record.pause_reason = record.last_error
        record.attempts = max(0, int(record.attempts or 0) - 1)
        record.exhausted = False
        record.completed_at = ''
        if self._running_task_id == task_id:
            self._running_task_id = None
        if not any(item.task_id == task_id for item in self._waiting_records):
            self._waiting_records.append(record)
        self.changed.emit()
        QTimer.singleShot(max(0, int(delay_ms or 0)), self._schedule_start_next)
        return True

    def mark_deleted(self, task_id, reason='用户删除任务'):
        record = self._find_record(task_id)
        if record is None:
            return False
        record.status = TASK_STATUS_DELETED
        record.last_error = str(reason or '').strip()
        record.pause_reason = record.last_error
        record.completed_at = _now_text()
        self._waiting_records = [item for item in self._waiting_records if item.task_id != task_id]
        self._start_callbacks.pop(task_id, None)
        getattr(self, '_cancel_callbacks', {}).pop(task_id, None)
        if self._running_task_id == task_id:
            self._running_task_id = None
        self.changed.emit()
        self._schedule_start_next()
        return True

    def restore_cancel_failure(self, task_id, error_message):
        record = self._find_record(task_id)
        if record is None or record.status != TASK_STATUS_CANCELLING:
            return False
        record.status = TASK_STATUS_RUNNING
        record.last_error = str(error_message or '').strip()
        record.pause_reason = ''
        self.changed.emit()
        return True

    def records(self):
        return [TaskRecord(**record.__dict__) for record in self._records]

    def update_record_plan(self, task_id, plan_id='', task_kind='', progress=None):
        record = self._find_record(task_id)
        if record is None:
            return
        if plan_id:
            record.plan_id = str(plan_id).strip()
        if task_kind:
            record.plan_task_kind = str(task_kind).strip()
        self._apply_plan_progress(record, progress)
        self.changed.emit()

    def update_plan_progress(self, plan_id, progress):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return
        for record in self._records:
            if record.plan_id == normalized_plan_id:
                self._apply_plan_progress(record, progress)
        self.changed.emit()

    def has_plan(self, plan_id):
        normalized_plan_id = str(plan_id or '').strip()
        return bool(normalized_plan_id) and any(
            record.plan_id == normalized_plan_id for record in self._records
        )

    def request_pause(self, task_id, reason=''):
        record = self._find_record(task_id)
        if record is None:
            return
        record.pause_reason = str(reason or '').strip()
        if self._running_task_id == task_id:
            record.pause_requested = True
        elif record.status in {TASK_STATUS_WAITING, TASK_STATUS_PAUSED}:
            record.status = TASK_STATUS_PAUSED
        self.changed.emit()

    def cancel_task(self, task_id, reason='用户删除任务'):
        record = self._find_record(task_id)
        if record is None or record.status in {
            TASK_STATUS_COMPLETED,
            TASK_STATUS_PARTIAL,
            TASK_STATUS_DELETED,
        }:
            return False
        normalized_reason = str(reason or '').strip() or '用户删除任务'
        if self._running_task_id == task_id or record.status in {
            TASK_STATUS_RUNNING,
            TASK_STATUS_CANCELLING,
        }:
            if record.status == TASK_STATUS_CANCELLING:
                return True
            record.status = TASK_STATUS_CANCELLING
            record.pause_reason = normalized_reason
            callback = getattr(self, '_cancel_callbacks', {}).get(task_id)
            if callable(callback):
                callback(record)
            self.changed.emit()
            return True
        self._waiting_records = [item for item in self._waiting_records if item.task_id != task_id]
        record.status = TASK_STATUS_DELETED
        record.last_error = normalized_reason
        record.pause_reason = normalized_reason
        record.completed_at = _now_text()
        self._start_callbacks.pop(task_id, None)
        getattr(self, '_cancel_callbacks', {}).pop(task_id, None)
        self.changed.emit()
        self._schedule_start_next()
        return True

    def cancel_tasks(self, task_ids, reason='用户删除任务'):
        return sum(1 for task_id in task_ids or [] if self.cancel_task(task_id, reason))

    def is_all_done(self):
        if not self._records:
            return True
        if self._running_task_id is not None:
            return False
        if self._waiting_records:
            return False
        return all(
            record.status in {TASK_STATUS_COMPLETED, TASK_STATUS_PARTIAL, TASK_STATUS_DELETED}
            for record in self._records
        )

    def reset_for_tests(self):
        self._records.clear()
        self._waiting_records.clear()
        self._start_callbacks.clear()
        self._cancel_callbacks = {}
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
        if record.status == TASK_STATUS_DELETED:
            self._schedule_start_next()
            return
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

    @staticmethod
    def _apply_plan_progress(record, progress):
        payload = dict(progress or {})
        record.batch_current = int(
            payload.get('completed_batch_count', payload.get('batch_current', record.batch_current)) or 0
        )
        record.batch_total = int(
            payload.get('batch_count_limit', payload.get('batch_total', record.batch_total)) or 0
        )
        record.plan_pending_count = int(
            payload.get('pending_count', payload.get('plan_pending_count', record.plan_pending_count)) or 0
        )
        record.plan_success_count = int(
            payload.get('success_count', payload.get('completed_count', record.plan_success_count)) or 0
        )
        record.plan_failed_count = int(
            payload.get('failed_count', payload.get('plan_failed_count', record.plan_failed_count)) or 0
        )
        if 'paused_reason' in payload:
            record.pause_reason = str(payload.get('paused_reason') or '').strip()
        if 'current_status' in payload and record.status not in {
            TASK_STATUS_RUNNING,
            TASK_STATUS_CANCELLING,
        }:
            record.status = str(payload.get('current_status') or record.status).strip() or record.status
        if 'last_run_id' in payload:
            record.last_run_id = str(payload.get('last_run_id') or '').strip()
        if 'last_run_result' in payload:
            record.last_run_result = dict(payload.get('last_run_result') or {})

    def _find_record(self, task_id):
        for record in self._records:
            if record.task_id == task_id:
                return record
        return None


_GLOBAL_TASK_QUEUE = GuiTaskQueue()


def get_gui_task_queue():
    return _GLOBAL_TASK_QUEUE
