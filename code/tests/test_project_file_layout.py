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
    migrate_legacy_storage_layout,
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


def test_legacy_local_files_migrate_without_overwriting_new_data(tmp_path):
    (tmp_path / 'config' / 'user').mkdir(parents=True)
    (tmp_path / 'config' / 'user' / 'runtime_settings.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'config' / 'user' / 'vidnorm.gui.lock').write_text('lock', encoding='utf-8')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'video_database.db').write_text('database', encoding='utf-8')
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs' / 'app.log').write_text('runtime', encoding='utf-8')
    (tmp_path / '.env').write_text('BACKEND_PORT=8766', encoding='utf-8')

    migrate_legacy_storage_layout(tmp_path)

    assert (tmp_path / 'user_data' / 'config' / 'runtime_settings.json').is_file()
    assert (tmp_path / 'user_data' / 'config' / '.env').is_file()
    assert (tmp_path / 'user_data' / 'databases' / 'video_database.db').is_file()
    assert (tmp_path / 'runtime' / 'logs' / 'app.log').is_file()
    assert (tmp_path / 'runtime' / 'locks' / 'vidnorm.gui.lock').is_file()


def test_legacy_runtime_files_are_preserved_when_new_runtime_file_exists(tmp_path):
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs' / 'app.log').write_text('legacy', encoding='utf-8')
    (tmp_path / 'runtime' / 'logs').mkdir(parents=True)
    (tmp_path / 'runtime' / 'logs' / 'app.log').write_text('new', encoding='utf-8')

    migrate_legacy_storage_layout(tmp_path)

    runtime_logs = tmp_path / 'runtime' / 'logs'
    assert (runtime_logs / 'app.log').read_text(encoding='utf-8') == 'new'
    assert any(path.read_text(encoding='utf-8') == 'legacy' for path in runtime_logs.iterdir())
    assert not (tmp_path / 'logs').exists()
