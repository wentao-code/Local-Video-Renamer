import os
import sys
from pathlib import Path


def _is_windows_apps_alias(path):
    return any(part.lower() == 'windowsapps' for part in Path(path).parts)


def _as_console_python(path):
    candidate = Path(path)
    if candidate.name.lower() in {'pythonw.exe', 'pyw.exe'}:
        candidate = candidate.with_name('python.exe' if candidate.name.lower() == 'pythonw.exe' else 'py.exe')
    return candidate


def _valid_python(path):
    candidate = _as_console_python(path)
    if not candidate.is_file() or _is_windows_apps_alias(candidate):
        return None
    if candidate.name.lower() != 'python.exe':
        return None
    return candidate.resolve()


def resolve_console_python(current_executable=None, environ=None):
    """Resolve a real console Python without accepting the Windows Store alias."""
    environment = os.environ if environ is None else environ
    candidates = []
    current = str(current_executable or sys.executable or '').strip()
    if current:
        candidates.append(current)

    for prefix in (getattr(sys, 'prefix', ''), getattr(sys, 'exec_prefix', '')):
        if prefix:
            candidates.append(str(Path(prefix) / 'python.exe'))

    for path_entry in str(environment.get('PATH', '') or '').split(os.pathsep):
        if path_entry:
            candidates.append(str(Path(path_entry) / 'python.exe'))

    seen = set()
    for candidate in candidates:
        normalized = str(Path(candidate)).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved = _valid_python(candidate)
        if resolved is not None:
            return str(resolved)

    raise RuntimeError(
        '缺少可执行 Python：当前 Python 路径不可用或指向 WindowsApps 占位程序。'
        '请在 PyCharm 中选择有效的 Python 解释器，或将其目录加入 PATH。'
    )
