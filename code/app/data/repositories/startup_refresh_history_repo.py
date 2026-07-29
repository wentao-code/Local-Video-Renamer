from datetime import datetime


class StartupRefreshHistoryRepositoryMixin:
    def _ensure_startup_refresh_history_table(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS startup_refresh_history (
                task_key TEXT PRIMARY KEY,
                task_title TEXT NOT NULL DEFAULT '',
                last_completed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

    def list_startup_refresh_history(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_startup_refresh_history_table(cursor)
            cursor.execute(
                '''
                SELECT task_key, task_title, last_completed_at
                FROM startup_refresh_history
                ORDER BY task_key
                '''
            )
            return {
                str(task_key or '').strip(): {
                    'task_key': str(task_key or '').strip(),
                    'task_title': str(task_title or '').strip(),
                    'last_completed_at': str(last_completed_at or '').strip(),
                }
                for task_key, task_title, last_completed_at in cursor.fetchall()
                if str(task_key or '').strip()
            }

    def record_startup_refresh_completion(self, task_key, task_title, completed_at=None):
        normalized_key = str(task_key or '').strip()
        if not normalized_key:
            raise ValueError('缺少启动刷新任务标识')
        completed_text = str(
            completed_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ).strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_startup_refresh_history_table(cursor)
            cursor.execute(
                '''
                INSERT INTO startup_refresh_history (
                    task_key, task_title, last_completed_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(task_key) DO UPDATE SET
                    task_title = excluded.task_title,
                    last_completed_at = excluded.last_completed_at,
                    updated_at = excluded.updated_at
                ''',
                (
                    normalized_key,
                    str(task_title or '').strip(),
                    completed_text,
                    completed_text,
                ),
            )
            conn.commit()
        return {
            'task_key': normalized_key,
            'task_title': str(task_title or '').strip(),
            'last_completed_at': completed_text,
        }
