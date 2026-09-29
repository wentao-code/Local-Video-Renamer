import os
import shutil
import subprocess
from pathlib import Path

from app.core.project_paths import BROWSER_PROFILES_DIR


STANDARD_REFERENCE_URL = (
    'http://www.aicaiaicai.com/forum.php?mod=forumdisplay&fid=109&forumdefstyle=yes'
)
STANDARD_REFERENCE_PROFILE_DIR = BROWSER_PROFILES_DIR / 'aicai_standard_reference'


def find_google_chrome():
    executable = shutil.which('chrome') or shutil.which('chrome.exe')
    if executable:
        return Path(executable)

    for root_key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        root = str(os.environ.get(root_key, '') or '').strip()
        if not root:
            continue
        candidate = Path(root) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'
        if candidate.is_file():
            return candidate
    return None


def open_standard_reference_login():
    chrome_path = find_google_chrome()
    if chrome_path is None:
        raise FileNotFoundError('找不到 Google Chrome。')

    STANDARD_REFERENCE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(chrome_path),
            f'--user-data-dir={STANDARD_REFERENCE_PROFILE_DIR}',
            '--new-window',
            STANDARD_REFERENCE_URL,
        ],
        close_fds=True,
    )
    return STANDARD_REFERENCE_PROFILE_DIR


def is_standard_reference_browser_open():
    profile_dir = Path(STANDARD_REFERENCE_PROFILE_DIR)
    return any(
        lock_path.exists() or lock_path.is_symlink()
        for lock_path in profile_dir.glob('SingletonLock*')
    )
