from app.core.project_paths import (
    ACTOR_LIBRARY_SETTINGS_FILE,
    CODE_PREFIX_LIBRARY_SETTINGS_FILE,
    CODE_ROOT,
    DATA_DIR,
    DATABASE_FILE,
    ENRICHMENT_SETTINGS_FILE,
    PROJECT_ROOT,
    QUEEN_LIBRARY_DB_FILE,
    USER_CONFIG_DIR,
    USER_DATA_DIR,
    RUNTIME_DIR,
    LAYOUT_ROOT,
    SNAPSHOT_DIR,
    VIDEO_FILTER_SETTINGS_FILE,
    VIDEO_LIBRARY_SETTINGS_FILE,
)


def test_user_settings_live_under_persistent_user_data():
    assert CODE_ROOT == PROJECT_ROOT
    assert CODE_ROOT.name == 'code'
    assert LAYOUT_ROOT / 'code' == CODE_ROOT
    assert USER_DATA_DIR == LAYOUT_ROOT / 'user_data'
    assert USER_CONFIG_DIR == USER_DATA_DIR / 'config'
    assert ACTOR_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'actor_library_settings.json'
    assert CODE_PREFIX_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'code_prefix_library_settings.json'
    assert ENRICHMENT_SETTINGS_FILE == USER_CONFIG_DIR / 'enrichment_settings.json'
    assert VIDEO_FILTER_SETTINGS_FILE == USER_CONFIG_DIR / 'video_filter_settings.json'
    assert VIDEO_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'video_library_settings.json'


def test_local_databases_live_under_persistent_user_data():
    assert DATA_DIR == USER_DATA_DIR / 'databases'
    assert DATABASE_FILE == DATA_DIR / 'video_database.db'
    assert QUEEN_LIBRARY_DB_FILE == DATA_DIR / 'queen_library.db'
    assert SNAPSHOT_DIR == USER_DATA_DIR / 'snapshots'


def test_runtime_artifacts_live_under_runtime_directory():
    assert RUNTIME_DIR == LAYOUT_ROOT / 'runtime'
