import json
import os
import tempfile
from pathlib import Path

from app.core.project_paths import RUNTIME_SETTINGS_FILE
from app.gui.task_queue import RUN_MODE_TASK, RUN_MODE_VIEW


def normalize_runtime_mode(value):
    return RUN_MODE_VIEW if str(value or '').strip() == RUN_MODE_VIEW else RUN_MODE_TASK


def load_runtime_mode(settings_file=RUNTIME_SETTINGS_FILE):
    path = Path(settings_file)
    if not path.exists():
        return RUN_MODE_TASK
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return RUN_MODE_TASK
    return normalize_runtime_mode((payload or {}).get('run_mode'))


def save_runtime_mode(settings_file=RUNTIME_SETTINGS_FILE, run_mode=RUN_MODE_TASK):
    path = Path(settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({'run_mode': normalize_runtime_mode(run_mode)}, ensure_ascii=False, indent=2)
    fd, temp_name = tempfile.mkstemp(prefix=f'{path.name}.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
