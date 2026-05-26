from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from app.core.project_paths import TASK_TRACE_LOG_DIR


class TaskTraceLogger:
    def __init__(self, task_kind, task_key, task_label, log_dir=None, keep_count=20):
        self.task_kind = str(task_kind or '').strip() or 'task'
        self.task_key = str(task_key or '').strip() or self.task_kind
        self.task_label = str(task_label or '').strip() or self.task_key
        self.log_dir = Path(log_dir) if log_dir else TASK_TRACE_LOG_DIR
        self.keep_count = max(1, int(keep_count or 1))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.run_started_at = datetime.now()
        timestamp = self.run_started_at.strftime('%Y%m%d_%H%M%S')
        self.run_id = f'{timestamp}_{self.task_kind}_{self.task_key}'
        self.log_path = self.log_dir / f'{self.run_id}.log'
        self._lock = Lock()
        self._cleanup_old_logs()
        self.log(
            'INFO',
            f'任务日志已创建：{self.task_label}',
            task_kind=self.task_kind,
            task_key=self.task_key,
            run_id=self.run_id,
            log_path=str(self.log_path),
        )

    def log(self, level, message, **fields):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        level_text = str(level or 'INFO').upper()
        detail_text = ''
        if fields:
            parts = [f'{key}={fields[key]}' for key in sorted(fields)]
            detail_text = ' | ' + ' | '.join(parts)
        line = f'[{timestamp}] [{level_text}] {message}{detail_text}\n'
        with self._lock:
            with self.log_path.open('a', encoding='utf-8') as handle:
                handle.write(line)

    def log_emphasis_block(self, title, lines=None, level='NOTICE'):
        border = '=' * 18
        text_lines = [str(line).strip() for line in (lines or []) if str(line).strip()]
        self.log(level, f'{border} {title} {border}')
        for text_line in text_lines:
            self.log(level, text_line)
        self.log(level, '=' * (len(title) + 38))

    def _cleanup_old_logs(self):
        log_files = sorted(
            self.log_dir.glob('*.log'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_file in log_files[self.keep_count:]:
            try:
                old_file.unlink()
            except Exception:
                continue
