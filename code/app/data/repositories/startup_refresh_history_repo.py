from datetime import datetime

from app.core.app_logging import get_task_id, new_task_id


class StartupRefreshHistoryRepositoryMixin:
    def _ensure_startup_refresh_history_table(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS startup_refresh_history (
                task_key TEXT PRIMARY KEY,
                task_title TEXT NOT NULL DEFAULT '',
                last_completed_at TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        self._ensure_column(cursor, 'startup_refresh_history', 'task_id', "TEXT NOT NULL DEFAULT ''")

    def list_startup_refresh_history(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_startup_refresh_history_table(cursor)
            cursor.execute(
                '''
                SELECT task_key, task_title, last_completed_at, task_id
                FROM startup_refresh_history
                ORDER BY task_key
                '''
            )
            return {
                str(task_key or '').strip(): {
                    'task_key': str(task_key or '').strip(),
                    'task_title': str(task_title or '').strip(),
                    'last_completed_at': str(last_completed_at or '').strip(),
                    'task_id': str(task_id or '').strip(),
                }
                for task_key, task_title, last_completed_at, task_id in cursor.fetchall()
                if str(task_key or '').strip()
            }

    def record_startup_refresh_completion(self, task_key, task_title, completed_at=None, task_id=''):
        normalized_key = str(task_key or '').strip()
        if not normalized_key:
            raise ValueError('缺少启动刷新任务标识')
        completed_text = str(
            completed_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ).strip()
        normalized_task_id = str(task_id or get_task_id() or new_task_id()).strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_startup_refresh_history_table(cursor)
            cursor.execute(
                '''
                INSERT INTO startup_refresh_history (
                    task_key, task_title, last_completed_at, task_id, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_key) DO UPDATE SET
                    task_title = excluded.task_title,
                    last_completed_at = excluded.last_completed_at,
                    task_id = excluded.task_id,
                    updated_at = excluded.updated_at
                ''',
                (
                    normalized_key,
                    str(task_title or '').strip(),
                    completed_text,
                    normalized_task_id,
                    completed_text,
                ),
            )
            conn.commit()
        return {
            'task_key': normalized_key,
            'task_title': str(task_title or '').strip(),
            'last_completed_at': completed_text,
            'task_id': normalized_task_id,
        }
