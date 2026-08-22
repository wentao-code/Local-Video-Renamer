from pathlib import Path

from app.core.project_paths import COMBO_TASK_LOG_DIR, LOG_DIR, PROJECT_ROOT, TASK_TRACE_LOG_DIR


class TaskLogResolver:
    """Resolve a bounded, read-only view of logs belonging to one task trace."""

    def __init__(self, log_dirs=None, explicit_base_dir=None):
        self.log_dirs = tuple(Path(item) for item in (log_dirs or (
            LOG_DIR,
            TASK_TRACE_LOG_DIR,
            COMBO_TASK_LOG_DIR,
        )))
        self.explicit_base_dir = Path(explicit_base_dir or PROJECT_ROOT)

    def resolve(self, trace_task_id, explicit_log_path='', max_lines=1000):
        trace = str(trace_task_id or '').strip()
        result = {
            'trace_task_id': trace,
            'explicit_paths': [],
            'matched_files': [],
            'lines': [],
            'errors': [],
            'truncated': False,
        }
        if not trace:
            result['errors'].append('缺少追踪 ID，无法定位任务日志')
            return result
        try:
            line_limit = max(1, int(max_lines or 1))
        except (TypeError, ValueError):
            line_limit = 1000

        candidates = []
        explicit = str(explicit_log_path or '').strip()
        if explicit:
            path = Path(explicit)
            if not path.is_absolute():
                path = self.explicit_base_dir / path
            path = path.resolve()
            result['explicit_paths'].append(str(path))
            candidates.append(path)
            if not path.is_file():
                result['errors'].append(f'显式日志文件不存在: {path}')

        for directory in self.log_dirs:
            try:
                if not directory.is_dir():
                    continue
                candidates.extend(
                    path for path in directory.glob('*.log*')
                    if path.is_file()
                )
            except OSError as exc:
                result['errors'].append(f'扫描日志目录失败 {directory}: {exc}')

        seen = set()
        for path in candidates:
            try:
                normalized = path.resolve()
            except OSError:
                normalized = path
            key = str(normalized).lower()
            if key in seen or not normalized.is_file():
                continue
            seen.add(key)
            try:
                with normalized.open('r', encoding='utf-8', errors='replace') as handle:
                    for line_number, line in enumerate(handle, 1):
                        if trace not in line:
                            continue
                        if len(result['lines']) >= line_limit:
                            result['truncated'] = True
                            break
                        result['lines'].append({
                            'path': str(normalized),
                            'line': line_number,
                            'text': line.rstrip('\r\n'),
                        })
                if any(item['path'] == str(normalized) for item in result['lines']):
                    result['matched_files'].append(str(normalized))
                if result['truncated']:
                    break
            except (OSError, UnicodeError) as exc:
                result['errors'].append(f'读取日志失败 {normalized}: {exc}')
        return result
