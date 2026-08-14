import json

from app.core.app_logging import get_logger


LOGGER = get_logger(__name__)


class TaskResumeRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, resume_kind, factory):
        normalized_kind = str(resume_kind or '').strip()
        if not normalized_kind or not callable(factory):
            raise ValueError('恢复任务类型和工厂函数不能为空')
        self._factories[normalized_kind] = factory

    def build(self, record, host):
        resume_kind = self._get(record, 'resume_kind')
        factory = self._factories.get(str(resume_kind or '').strip())
        if factory is None:
            return None
        payload = self._get(record, 'resume_payload', {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                return None
        if not isinstance(payload, dict):
            return None
        try:
            callback = factory(dict(payload), host)
        except Exception:
            LOGGER.exception('恢复任务工厂创建失败 resume_kind=%s', resume_kind)
            return None
        return callback if callable(callback) else None

    def recover_persisted_tasks(self, queue, persistence, host):
        persistence.mark_running_gui_tasks_paused('应用重启时中断')
        restored = []
        rows = persistence.list_gui_tasks(statuses=['已暂停', '等待中'])
        for record in rows:
            task_id = int(self._get(record, 'task_id', 0) or 0)
            if not task_id or queue.contains_task(task_id):
                continue
            if not bool(self._get(record, 'resumable', False)):
                persistence.update_gui_task(
                    task_id,
                    status='不可恢复',
                    non_resumable_reason='任务没有恢复描述',
                )
                continue
            callback = self.build(record, host)
            if callback is None:
                persistence.update_gui_task(
                    task_id,
                    status='不可恢复',
                    non_resumable_reason=f"未注册恢复类型: {self._get(record, 'resume_kind', '')}",
                )
                continue
            restored_record = queue.restore_persisted_record(record, callback)
            if restored_record is not None:
                restored.append(restored_record)
        return restored

    @staticmethod
    def _get(record, key, default=None):
        if isinstance(record, dict):
            return record.get(key, default)
        return getattr(record, key, default)
