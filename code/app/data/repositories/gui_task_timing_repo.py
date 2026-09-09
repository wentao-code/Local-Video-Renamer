from datetime import datetime


class GuiTaskTimingRepositoryMixin:
    _GUI_TASK_TIMING_COLUMNS = {
        'trace_task_id', 'task_category', 'title', 'status', 'started_at',
        'ended_at', 'last_resumed_at', 'paused_at', 'paused_seconds', 'active_seconds',
        'pause_count', 'resume_count', 'close_reason',
    }

    def _ensure_gui_task_timing_tables(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS gui_task_timing_records (
                task_id INTEGER PRIMARY KEY,
                trace_task_id TEXT NOT NULL DEFAULT '',
                task_category TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '等待中',
                started_at TEXT NOT NULL DEFAULT '',
                ended_at TEXT NOT NULL DEFAULT '',
                last_resumed_at TEXT NOT NULL DEFAULT '',
                paused_at TEXT NOT NULL DEFAULT '',
                paused_seconds REAL NOT NULL DEFAULT 0,
                active_seconds REAL NOT NULL DEFAULT 0,
                pause_count INTEGER NOT NULL DEFAULT 0,
                resume_count INTEGER NOT NULL DEFAULT 0,
                close_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_gui_task_timing_category_status '
            'ON gui_task_timing_records (task_category, status, updated_at DESC)'
        )
        self._ensure_column(cursor, 'gui_task_timing_records', 'paused_at', "TEXT NOT NULL DEFAULT ''")

    def save_gui_task_timing(self, record):
        payload = self._serialize_gui_task_timing(record)
        columns = [
            'task_id', 'trace_task_id', 'task_category', 'title', 'status',
            'started_at', 'ended_at', 'last_resumed_at', 'paused_at', 'paused_seconds',
            'active_seconds', 'pause_count', 'resume_count', 'close_reason',
        ]
        with self._connect() as conn:
            conn.execute(
                f'''INSERT INTO gui_task_timing_records ({', '.join(columns)})
                    VALUES ({', '.join('?' for _ in columns)})
                    ON CONFLICT(task_id) DO UPDATE SET
                    {', '.join(f'{column}=excluded.{column}' for column in columns if column != 'task_id')},
                    updated_at=CURRENT_TIMESTAMP''',
                [payload.get(column) for column in columns],
            )
            conn.commit()
        return payload

    def update_gui_task_timing(self, task_id, **changes):
        allowed = {
            key: value for key, value in changes.items()
            if key in self._GUI_TASK_TIMING_COLUMNS
        }
        if not allowed:
            return self.get_gui_task_timing(task_id)
        assignments = ', '.join(f'{key} = ?' for key in allowed)
        with self._connect() as conn:
            cursor = conn.execute(
                f'UPDATE gui_task_timing_records SET {assignments}, '
                'updated_at=CURRENT_TIMESTAMP WHERE task_id = ?',
                [*(allowed[key] for key in allowed), int(task_id)],
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_gui_task_timing(task_id)

    def get_gui_task_timing(self, task_id):
        with self._connect() as conn:
            cursor = conn.execute(
                'SELECT * FROM gui_task_timing_records WHERE task_id = ?',
                (int(task_id),),
            )
            row = cursor.fetchone()
            columns = [item[0] for item in cursor.description or []]
        return dict(zip(columns, row)) if row else None

    def list_gui_task_timings(self, task_category=None):
        where = ''
        params = []
        if task_category:
            where = 'WHERE task_category = ?'
            params.append(str(task_category))
        with self._connect() as conn:
            cursor = conn.execute(
                f'''SELECT * FROM gui_task_timing_records {where}
                    ORDER BY task_id''',
                params,
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description or []]
        return [dict(zip(columns, row)) for row in rows]

    def mark_running_gui_task_timings_paused(self, reason='应用重启时中断'):
        normalized_reason = str(reason or '').strip() or '应用重启时中断'
        paused_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._connect() as conn:
            cursor = conn.execute(
                '''UPDATE gui_task_timing_records
                   SET status = '已暂停', paused_at = ?,
                       close_reason = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE status = '正在执行' ''',
                (paused_at, normalized_reason),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    @staticmethod
    def _serialize_gui_task_timing(record):
        source = dict(record or {})
        return {
            'task_id': int(source.get('task_id') or 0),
            'trace_task_id': str(source.get('trace_task_id') or ''),
            'task_category': str(source.get('task_category') or ''),
            'title': str(source.get('title') or ''),
            'status': str(source.get('status') or '等待中'),
            'started_at': str(source.get('started_at') or ''),
            'ended_at': str(source.get('ended_at') or ''),
            'last_resumed_at': str(source.get('last_resumed_at') or ''),
            'paused_at': str(source.get('paused_at') or ''),
            'paused_seconds': float(source.get('paused_seconds') or 0),
            'active_seconds': float(source.get('active_seconds') or 0),
            'pause_count': int(source.get('pause_count') or 0),
            'resume_count': int(source.get('resume_count') or 0),
            'close_reason': str(source.get('close_reason') or ''),
            'created_at': str(source.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        }
