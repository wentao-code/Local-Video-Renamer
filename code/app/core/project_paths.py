"""Central filesystem layout for code, persistent user data, and runtime data."""

from __future__ import annotations

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
TRANSLATION_INPUT_DIR = USER_DATA_DIR / 'translation_videos'
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

ENV_FILE = USER_CONFIG_DIR / '.env'
ENV_EXAMPLE_FILE = PROJECT_ROOT / '.env.example'
ENRICHMENT_SETTINGS_FILE = USER_CONFIG_DIR / 'enrichment_settings.json'
RUNTIME_SETTINGS_FILE = USER_CONFIG_DIR / 'runtime_settings.json'
BACKGROUND_REFRESH_SETTINGS_FILE = USER_CONFIG_DIR / 'background_refresh_settings.json'
VIDEO_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'video_library_settings.json'
VIDEO_FILTER_SETTINGS_FILE = USER_CONFIG_DIR / 'video_filter_settings.json'
ACTOR_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'actor_library_settings.json'
CODE_PREFIX_LIBRARY_SETTINGS_FILE = USER_CONFIG_DIR / 'code_prefix_library_settings.json'
QUERY_HISTORY_FILE = USER_CONFIG_DIR / 'query_history.json'
TRANSLATION_INPUT_PATH_FILE = USER_CONFIG_DIR / 'translation_input_path.json'
SUBTITLE_GENERATION_RECORD_FILE = USER_CONFIG_DIR / 'subtitle_generation_records.json'
SUBTITLE_GENERATION_TASK_DIR = USER_CONFIG_DIR / 'subtitle_generation_tasks'
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

DATABASE_FILE = DATA_DIR / 'video_database.db'
QUEEN_LIBRARY_DB_FILE = DATA_DIR / 'queen_library.db'
QUEEN_LIBRARY_CRAWL_LOG_FILE = LOG_DIR / 'queen_library_crawl.log'
AVFAN_PROFILE_DIR = BROWSER_PROFILES_DIR / 'avfan'
COMBO_BROWSER_PROFILES_DIR = BROWSER_PROFILES_DIR / 'combo'


def ensure_storage_layout() -> None:
    """Create writable local storage directories."""
    for directory in (
        USER_CONFIG_DIR,
        TRANSLATION_INPUT_DIR,
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
    ):
        directory.mkdir(parents=True, exist_ok=True)
