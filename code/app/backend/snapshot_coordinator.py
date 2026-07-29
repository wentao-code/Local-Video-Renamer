from contextlib import nullcontext
from datetime import datetime
from threading import Lock


class SnapshotCoordinator:
    """Owns generic page-snapshot storage, locking, and invalidation."""

    def __init__(self, store=None):
        self.store = store
        self._locks = {}
        self._locks_guard = Lock()

    def lock_for(self, name):
        normalized_name = str(name or 'default').strip() or 'default'
        with self._locks_guard:
            return self._locks.setdefault(normalized_name, Lock())

    def guard(self, name='default'):
        return self.lock_for(name) if self.store is not None else nullcontext()

    def read(self, key):
        if self.store is None:
            return None
        payload = self.store.read(key)
        return payload if isinstance(payload, dict) else None

    def write(self, key, payload):
        if self.store is not None and isinstance(payload, dict):
            self.store.write(key, payload)

    def delete(self, key):
        if self.store is not None:
            self.store.delete(key)

    def delete_prefix(self, prefix):
        if self.store is not None:
            self.store.delete_prefix(prefix)

    @staticmethod
    def format_duration(duration_ms):
        total_seconds = max(0, int(round(int(duration_ms or 0) / 1000.0)))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours}小时{minutes}分{seconds}秒'
        if minutes > 0:
            return f'{minutes}分{seconds}秒'
        return f'{seconds}秒'

    @classmethod
    def build_payload(cls, refreshed_at=None, **fields):
        refresh_duration_ms = int(fields.pop('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(fields.pop('refresh_duration_text', '') or '').strip()
        return {
            **fields,
            'refreshed_at': str(
                refreshed_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ).strip(),
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or cls.format_duration(refresh_duration_ms),
        }

    @staticmethod
    def refreshed_at(snapshot):
        return str((snapshot or {}).get('refreshed_at', '') or '').strip()
