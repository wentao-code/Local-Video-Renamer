from app.core.project_paths import (
    ACTOR_LIBRARY_SETTINGS_FILE,
    CODE_PREFIX_LIBRARY_SETTINGS_FILE,
    DATA_DIR,
    DATABASE_FILE,
    ENRICHMENT_SETTINGS_FILE,
    PROJECT_ROOT,
    QUEEN_LIBRARY_DB_FILE,
    USER_CONFIG_DIR,
    VIDEO_FILTER_SETTINGS_FILE,
    VIDEO_LIBRARY_SETTINGS_FILE,
)


def test_user_settings_live_under_config_user():
    assert USER_CONFIG_DIR == PROJECT_ROOT / 'config' / 'user'
    assert ACTOR_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'actor_library_settings.json'
    assert CODE_PREFIX_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'code_prefix_library_settings.json'
    assert ENRICHMENT_SETTINGS_FILE == USER_CONFIG_DIR / 'enrichment_settings.json'
    assert VIDEO_FILTER_SETTINGS_FILE == USER_CONFIG_DIR / 'video_filter_settings.json'
    assert VIDEO_LIBRARY_SETTINGS_FILE == USER_CONFIG_DIR / 'video_library_settings.json'


def test_local_databases_live_under_data_directory():
    assert DATA_DIR == PROJECT_ROOT / 'data'
    assert DATABASE_FILE == DATA_DIR / 'video_database.db'
    assert QUEEN_LIBRARY_DB_FILE == DATA_DIR / 'queen_library.db'
