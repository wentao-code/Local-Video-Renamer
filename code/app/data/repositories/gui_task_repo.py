import json
from datetime import datetime


class GuiTaskRepositoryMixin:
    _GUI_TASK_COLUMNS = {
        'trace_task_id', 'title', 'source', 'task_category', 'task_kind', 'status',
        'attempts', 'max_attempts', 'created_at', 'started_at', 'paused_at',
        'completed_at', 'last_error', 'exhausted', 'partial', 'plan_id',
        'plan_task_kind', 'batch_current', 'batch_total', 'plan_pending_count',
        'plan_success_count', 'plan_failed_count', 'pause_reason', 'last_run_id',
        'last_run_result_json', 'log_path',
        'pause_requested', 'resume_kind', 'resume_payload_json', 'resumable',
        'non_resumable_reason', 'account_id',
    }

    def _ensure_gui_task_tables(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS gui_task_records (
                task_id INTEGER PRIMARY KEY,
                trace_task_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                task_category TEXT NOT NULL DEFAULT '',
                task_kind TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '等待中',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT NOT NULL DEFAULT '',
                paused_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                exhausted INTEGER NOT NULL DEFAULT 0,
                partial INTEGER NOT NULL DEFAULT 0,
                plan_id TEXT NOT NULL DEFAULT '',
                plan_task_kind TEXT NOT NULL DEFAULT '',
                batch_current INTEGER NOT NULL DEFAULT 0,
                batch_total INTEGER NOT NULL DEFAULT 0,
                plan_pending_count INTEGER NOT NULL DEFAULT 0,
                plan_success_count INTEGER NOT NULL DEFAULT 0,
                plan_failed_count INTEGER NOT NULL DEFAULT 0,
                pause_reason TEXT NOT NULL DEFAULT '',
                last_run_id TEXT NOT NULL DEFAULT '',
                last_run_result_json TEXT NOT NULL DEFAULT '{}',
                log_path TEXT NOT NULL DEFAULT '',
                pause_requested INTEGER NOT NULL DEFAULT 0,
                resume_kind TEXT NOT NULL DEFAULT '',
                resume_payload_json TEXT NOT NULL DEFAULT '{}',
                resumable INTEGER NOT NULL DEFAULT 0,
                non_resumable_reason TEXT NOT NULL DEFAULT '',
                account_id INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        for column, definition in (
            ('batch_current', 'INTEGER NOT NULL DEFAULT 0'),
            ('batch_total', 'INTEGER NOT NULL DEFAULT 0'),
            ('plan_pending_count', 'INTEGER NOT NULL DEFAULT 0'),
            ('plan_success_count', 'INTEGER NOT NULL DEFAULT 0'),
            ('plan_failed_count', 'INTEGER NOT NULL DEFAULT 0'),
            ('log_path', "TEXT NOT NULL DEFAULT ''"),
            ('account_id', 'INTEGER NOT NULL DEFAULT 0'),
        ):
            self._ensure_column(cursor, 'gui_task_records', column, definition)
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_gui_task_records_status '
            'ON gui_task_records (status, updated_at DESC)'
        )

    def save_gui_task(self, record):
        payload = self._serialize_gui_task(record)
        columns = [
            'task_id', 'trace_task_id', 'title', 'source', 'task_category', 'task_kind',
            'status', 'attempts', 'max_attempts', 'created_at', 'started_at', 'paused_at',
            'completed_at', 'last_error', 'exhausted', 'partial', 'plan_id',
            'plan_task_kind', 'batch_current', 'batch_total', 'plan_pending_count',
            'plan_success_count', 'plan_failed_count', 'pause_reason', 'last_run_id',
            'last_run_result_json', 'log_path',
            'pause_requested', 'resume_kind', 'resume_payload_json', 'resumable',
            'non_resumable_reason', 'account_id',
        ]
        with self._connect() as conn:
            conn.execute(
                f'''INSERT INTO gui_task_records ({', '.join(columns)})
                    VALUES ({', '.join('?' for _ in columns)})
                    ON CONFLICT(task_id) DO UPDATE SET
                    {', '.join(f'{column}=excluded.{column}' for column in columns if column != 'task_id')},
                    updated_at=CURRENT_TIMESTAMP''',
                [payload.get(column) for column in columns],
            )
            conn.commit()
        return self._deserialize_gui_task(payload)

    def update_gui_task(self, task_id, **changes):
        allowed = {
            key: value for key, value in changes.items() if key in self._GUI_TASK_COLUMNS
        }
        if not allowed:
            return self.get_gui_task(task_id)
        serialized = {
            key: self._serialize_gui_field(key, value)
            for key, value in allowed.items()
        }
        assignments = ', '.join(f'{key} = ?' for key in serialized)
        with self._connect() as conn:
            cursor = conn.execute(
                f'UPDATE gui_task_records SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE task_id = ?',
                [*(serialized[key] for key in serialized), int(task_id)],
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get_gui_task(task_id)

    def list_gui_tasks(self, statuses=None):
        normalized = [str(value or '').strip() for value in statuses or [] if str(value or '').strip()]
        where = ''
        params = []
        if normalized:
            where = f"WHERE status IN ({', '.join('?' for _ in normalized)})"
            params.extend(normalized)
        with self._connect() as conn:
            cursor = conn.execute(f'SELECT * FROM gui_task_records {where} ORDER BY task_id', params)
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description or []]
        return [self._deserialize_gui_task(dict(zip(columns, row))) for row in rows]

    def mark_running_gui_tasks_paused(self, reason='应用重启时中断'):
        normalized_reason = str(reason or '').strip() or '应用重启时中断'
        with self._connect() as conn:
            cursor = conn.execute(
                '''UPDATE gui_task_records
                   SET status = '已暂停', pause_reason = ?, pause_requested = 0,
                       paused_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE status IN ('正在执行', 'running') ''',
                (normalized_reason,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def reconcile_terminal_enrichment_gui_tasks(self):
        """Close legacy GUI records after their persisted enrichment plan is terminal."""
        with self._connect() as conn:
            cursor = conn.execute(
                '''UPDATE gui_task_records
                   SET status = '已完成', pause_requested = 0, pause_reason = '',
                       completed_at = CASE WHEN completed_at = '' THEN CURRENT_TIMESTAMP ELSE completed_at END,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE plan_id <> ''
                     AND status IN ('正在执行', 'running', '等待中')
                     AND EXISTS (
                         SELECT 1
                         FROM enrichment_batch_plans AS plan
                         WHERE plan.plan_id = gui_task_records.plan_id
                           AND plan.status = 'completed'
                     )'''
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def get_gui_task(self, task_id):
        rows = self.list_gui_tasks()
        return next((row for row in rows if int(row.get('task_id') or 0) == int(task_id)), None)

    @staticmethod
    def _serialize_gui_field(key, value):
        if key in {'exhausted', 'partial', 'pause_requested', 'resumable'}:
            return int(bool(value))
        if key in {'last_run_result_json', 'resume_payload_json'}:
            if not isinstance(value, str):
                value = json.dumps(value or {}, ensure_ascii=False)
            return value or '{}'
        return value

    @staticmethod
    def _serialize_gui_task(record):
        source = dict(record or {})
        payload = dict(source)
        payload.update({
            'task_id': int(source.get('task_id') or 0),
            'trace_task_id': str(source.get('trace_task_id') or ''),
            'title': str(source.get('title') or ''),
            'source': str(source.get('source') or ''),
            'task_category': str(source.get('task_category') or ''),
            'task_kind': str(source.get('task_kind') or ''),
            'status': str(source.get('status') or '等待中'),
            'attempts': int(source.get('attempts') or 0),
            'max_attempts': int(source.get('max_attempts') or 5),
            'created_at': str(source.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            'started_at': str(source.get('started_at') or ''),
            'paused_at': str(source.get('paused_at') or ''),
            'completed_at': str(source.get('completed_at') or ''),
            'last_error': str(source.get('last_error') or ''),
            'exhausted': int(bool(source.get('exhausted'))),
            'partial': int(bool(source.get('partial'))),
            'plan_id': str(source.get('plan_id') or ''),
            'plan_task_kind': str(source.get('plan_task_kind') or ''),
            'batch_current': int(source.get('batch_current') or 0),
            'batch_total': int(source.get('batch_total') or 0),
            'plan_pending_count': int(source.get('plan_pending_count') or 0),
            'plan_success_count': int(source.get('plan_success_count') or 0),
            'plan_failed_count': int(source.get('plan_failed_count') or 0),
            'pause_reason': str(source.get('pause_reason') or ''),
            'last_run_id': str(source.get('last_run_id') or ''),
            'log_path': str(source.get('log_path') or ''),
            'pause_requested': int(bool(source.get('pause_requested'))),
            'resume_kind': str(source.get('resume_kind') or ''),
            'resumable': int(bool(source.get('resumable'))),
            'non_resumable_reason': str(source.get('non_resumable_reason') or ''),
            'account_id': int(source.get('account_id') or 0),
        })
        for target, candidates in (
            ('last_run_result_json', ('last_run_result_json', 'last_run_result')),
            ('resume_payload_json', ('resume_payload_json', 'resume_payload')),
        ):
            value = next((source[key] for key in candidates if key in source), {})
            payload[target] = value if isinstance(value, str) else json.dumps(value or {}, ensure_ascii=False)
            payload[target] = payload[target] or '{}'
        return payload

    @staticmethod
    def _deserialize_gui_task(payload):
        result = dict(payload or {})
        for column, field in (('last_run_result_json', 'last_run_result'), ('resume_payload_json', 'resume_payload')):
            raw = result.pop(column, '{}') or '{}'
            try:
                result[field] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                result[field] = {}
        for key in ('exhausted', 'partial', 'pause_requested', 'resumable'):
            result[key] = bool(result.get(key))
        return result
