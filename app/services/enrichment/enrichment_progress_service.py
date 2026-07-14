from threading import Lock

from app.core.app_logging import get_correlation_id, get_run_id

class EnrichmentProgressService:
    def __init__(self):
        self._lock = Lock()
        self._state = self._build_default_state()

    def start(
        self,
        target_label,
        total_count,
        source_label='',
        message='',
        count_unit='项',
        target_type='',
        source_key='',
        log_path='',
        task_kind='single',
        run_id='',
        correlation_id='',
    ):
        with self._lock:
            self._state = self._build_default_state()
            self._state.update(
                {
                    'is_running': True,
                    'task_kind': str(task_kind or 'single'),
                    'target_label': str(target_label or ''),
                    'source_label': str(source_label or ''),
                    'target_type': str(target_type or ''),
                    'source_key': str(source_key or ''),
                    'total_count': max(0, int(total_count or 0)),
                    'message': str(message or ''),
                    'count_unit': str(count_unit or '项'),
                    'log_path': str(log_path or ''),
                    'run_id': str(run_id or get_run_id() or ''),
                    'correlation_id': str(correlation_id or get_correlation_id() or ''),
                }
            )

    def update(self, processed_count, success_count, failed_count, current_item=''):
        with self._lock:
            total_count = max(0, int(self._state.get('total_count', 0) or 0))
            processed_count = max(0, int(processed_count or 0))
            progress_percent = 0.0
            if total_count > 0:
                progress_percent = round((processed_count / total_count) * 100.0, 1)

            self._state.update(
                {
                    'processed_count': processed_count,
                    'success_count': max(0, int(success_count or 0)),
                    'failed_count': max(0, int(failed_count or 0)),
                    'current_item': str(current_item or ''),
                    'progress_percent': progress_percent,
                }
            )

    def finish(self, message='', stopped=False):
        with self._lock:
            total_count = max(0, int(self._state.get('total_count', 0) or 0))
            processed_count = max(0, int(self._state.get('processed_count', 0) or 0))
            if total_count > 0 and processed_count >= total_count:
                self._state['progress_percent'] = 100.0
            self._state.update(
                {
                    'is_running': False,
                    'message': str(message or ''),
                    'stopped': bool(stopped),
                }
            )

    def set_message(self, message):
        with self._lock:
            self._state['message'] = str(message or '')

    def reset(self):
        with self._lock:
            self._state = self._build_default_state()

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    @staticmethod
    def _build_default_state():
        return {
            'is_running': False,
            'task_kind': '',
            'target_label': '',
            'source_label': '',
            'target_type': '',
            'source_key': '',
            'total_count': 0,
            'processed_count': 0,
            'success_count': 0,
            'failed_count': 0,
            'current_item': '',
            'progress_percent': 0.0,
            'message': '',
            'stopped': False,
            'count_unit': '项',
            'log_path': '',
            'run_id': '',
            'correlation_id': '',
        }
