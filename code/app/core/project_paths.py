"""Central filesystem layout for code, persistent user data, and runtime data."""

from __future__ import annotations

import shutil
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
CODE_ROOT = APP_DIR.parent
# This fallback keeps the code runnable during the one-time move into code/.
LAYOUT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == 'code' else CODE_ROOT
PROJECT_ROOT = CODE_ROOT

# Code lives in CODE_ROOT. These two sibling directories are local-only.
USER_DATA_DIR = LAYOUT_ROOT / 'user_data'
RUNTIME_DIR = LAYOUT_ROOT / 'runtime'

USER_CONFIG_DIR = USER_DATA_DIR / 'config'
DATA_DIR = USER_DATA_DIR / 'databases'
BROWSER_PROFILES_DIR = USER_DATA_DIR / 'browser_profiles'
BACKUP_DIR = USER_DATA_DIR / 'backups'
SNAPSHOT_DIR = USER_DATA_DIR / 'snapshots'
MESSAGEPACK_SNAPSHOT_DIR = SNAPSHOT_DIR / 'messagepack'
JSON_SNAPSHOT_DIR = SNAPSHOT_DIR / 'json'

LOG_DIR = RUNTIME_DIR / 'logs'
TASK_TRACE_LOG_DIR = RUNTIME_DIR / 'task_logs'
COMBO_TASK_LOG_DIR = RUNTIME_DIR / 'combo_task_logs'
LOCK_DIR = RUNTIME_DIR / 'locks'
TEMP_DIR = RUNTIME_DIR / 'tmp'
QUARK_BACKUP_ARCHIVE_DIR = RUNTIME_DIR / 'backup_archives'

ENV_FILE = USER_CONFIG_DIR / '.env'
ENV_EXAMPLE_FILE = PROJECT_ROOT / '.env.example'
ENRICHMENT_SETTINGS_FILE = USER_CONFIG_DIR / 'enrichment_settings.json'
RUNTIME_SETTINGS_FILE = USER_CONFIG_DIR / 'runtime_settings.json'
VIDEO_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'video_library_settings.json'
VIDEO_FILTER_SETTINGS_FILE = USER_CONFIG_DIR / 'video_filter_settings.json'
ACTOR_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'actor_library_settings.json'
CODE_PREFIX_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'code_prefix_library_settings.json'
QUERY_HISTORY_FILE = USER_CONFIG_DIR / 'query_history.json'
QUARK_BACKUP_CONFIG_FILE = USER_CONFIG_DIR / 'quark_backup.json'
QUARK_BACKUP_STATE_FILE = USER_CONFIG_DIR / 'quark_backup_state.json'
QUARK_CREDENTIAL_FILE = USER_CONFIG_DIR / 'quark_credentials.dat'
QUARK_BACKUP_LOCK_FILE = LOCK_DIR / 'quark_backup.lock'
GUI_INSTANCE_LOCK_FILE = LOCK_DIR / 'vidnorm.gui.lock'

APP_LOG_FILE = LOG_DIR / 'app.log'
ERROR_LOG_FILE = LOG_DIR / 'error.log'
HTTP_ACCESS_LOG_FILE = LOG_DIR / 'http_access.log'
DATA_CENTER_SNAPSHOT_FILE = SNAPSHOT_DIR / 'data_center_snapshot.json'
CODE_PREFIX_SNAPSHOT_FILE = SNAPSHOT_DIR / 'code_prefix_snapshot.json'
ACTOR_SNAPSHOT_FILE = SNAPSHOT_DIR / 'actor_snapshot.json'
ACTOR_DETAIL_SNAPSHOT_DIR = SNAPSHOT_DIR / 'actor_detail'
CODE_PREFIX_DETAIL_SNAPSHOT_DIR = SNAPSHOT_DIR / 'code_prefix_detail'
MASTERPIECE_SNAPSHOT_FILE = SNAPSHOT_DIR / 'masterpiece_snapshot.json'
VIDEO_CATEGORY_SNAPSHOT_FILE = SNAPSHOT_DIR / 'video_category_snapshot.json'
SNAPSHOT_REFRESH_LOG_FILE = LOG_DIR / 'snapshot_refresh.log'

LEGACY_DATA_CENTER_SNAPSHOT_FILE = PROJECT_ROOT / '.data_center_snapshot.json'
LEGACY_CODE_PREFIX_SNAPSHOT_FILE = PROJECT_ROOT / '.code_prefix_snapshot.json'
DATABASE_FILE = DATA_DIR / 'video_database.db'
QUEEN_LIBRARY_DB_FILE = DATA_DIR / 'queen_library.db'
QUEEN_LIBRARY_CRAWL_LOG_FILE = LOG_DIR / 'queen_library_crawl.log'
AVFAN_PROFILE_DIR = BROWSER_PROFILES_DIR / 'avfan'
COMBO_BROWSER_PROFILES_DIR = BROWSER_PROFILES_DIR / 'combo'


def _legacy_conflict_target(target: Path) -> Path:
    """Return an unused sibling path for a legacy runtime artifact."""
    index = 1
    while True:
        suffix = '.legacy' if index == 1 else f'.legacy-{index}'
        candidate = target.with_name(f'{target.stem}{suffix}{target.suffix}')
        if not candidate.exists():
            return candidate
        index += 1


def _move_entry_if_safe(source: Path, target: Path, *, relocate_conflicts: bool = False) -> None:
    """Move legacy data without overwriting a newer destination entry."""
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.move(str(source), str(target))
        return
    if not source.is_dir() or not target.is_dir():
        if relocate_conflicts:
            shutil.move(str(source), str(_legacy_conflict_target(target)))
        return
    for child in source.iterdir():
        _move_entry_if_safe(child, target / child.name, relocate_conflicts=relocate_conflicts)
    try:
        source.rmdir()
    except OSError:
        pass


def migrate_legacy_storage_layout(project_root: Path = LAYOUT_ROOT) -> None:
    """Move pre-layout local files to the new directories without data loss."""
    root = Path(project_root)
    user_data = root / 'user_data'
    runtime = root / 'runtime'
    user_config = user_data / 'config'

    legacy_user_config = root / 'config' / 'user'
    if legacy_user_config.is_dir():
        for entry in legacy_user_config.iterdir():
            target_dir = runtime / 'locks' if entry.suffix == '.lock' else user_config
            _move_entry_if_safe(entry, target_dir / entry.name)
        try:
            legacy_user_config.rmdir()
        except OSError:
            pass

    _move_entry_if_safe(root / '.env', user_config / '.env')
    for source_name, target in (
        ('data', user_data / 'databases'),
        ('browser_profiles', user_data / 'browser_profiles'),
        ('backups', user_data / 'backups'),
        ('runtime_snapshots', user_data / 'snapshots'),
    ):
        _move_entry_if_safe(root / source_name, target)
    _move_entry_if_safe(runtime / 'snapshots', user_data / 'snapshots')
    for source_name, target in (
        ('logs', runtime / 'logs'),
        ('task_logs', runtime / 'task_logs'),
        ('combo_task_logs', runtime / 'combo_task_logs'),
        ('tmp', runtime / 'tmp'),
    ):
        _move_entry_if_safe(root / source_name, target, relocate_conflicts=True)


def ensure_storage_layout() -> None:
    """Migrate once when needed and create writable local storage directories."""
    migrate_legacy_storage_layout()
    for directory in (
        USER_CONFIG_DIR,
        DATA_DIR,
        BROWSER_PROFILES_DIR,
        BACKUP_DIR,
        SNAPSHOT_DIR,
        MESSAGEPACK_SNAPSHOT_DIR,
        JSON_SNAPSHOT_DIR,
        LOG_DIR,
        TASK_TRACE_LOG_DIR,
        COMBO_TASK_LOG_DIR,
        LOCK_DIR,
        TEMP_DIR,
        QUARK_BACKUP_ARCHIVE_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
