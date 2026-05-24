from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from app.core.project_paths import COMBO_TASK_LOG_DIR


class ComboTaskLogger:
    def __init__(self, combo_key, combo_label, log_dir=None):
        self.combo_key = str(combo_key or '').strip()
        self.combo_label = str(combo_label or '').strip()
        self.log_dir = Path(log_dir) if log_dir else COMBO_TASK_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.run_started_at = datetime.now()
        timestamp = self.run_started_at.strftime('%Y%m%d_%H%M%S')
        self.run_id = f'{timestamp}_{self.combo_key}'
        self.log_path = self.log_dir / f'{self.run_id}.log'
        self._lock = Lock()
        self._cleanup_old_logs()
        self.log(
            'INFO',
            f'组合任务日志已创建：{self.combo_label}',
            combo_key=self.combo_key,
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
        for old_file in log_files[4:]:
            try:
                old_file.unlink()
            except Exception:
                continue
