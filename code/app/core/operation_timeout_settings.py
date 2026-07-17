import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.project_paths import DATABASE_FILE


OPERATION_TIMEOUT_SPECS = (
    {'key': 'backend_request', 'name': '\u666e\u901a\u540e\u7aef\u8bf7\u6c42', 'default': 30, 'minimum': 1, 'maximum': 3600},
    {'key': 'list_detail_load', 'name': '\u5217\u8868/\u8be6\u60c5\u52a0\u8f7d', 'default': 120, 'minimum': 1, 'maximum': 3600},
    {'key': 'snapshot_refresh_rebuild', 'name': '\u5feb\u7167\u5237\u65b0/\u91cd\u5efa', 'default': 1200, 'minimum': 30, 'maximum': 7200},
    {'key': 'automatic_login', 'name': '\u81ea\u52a8\u767b\u5f55', 'default': 660, 'minimum': 30, 'maximum': 3600},
    {'key': 'manual_verification', 'name': '\u4eba\u5de5\u9a8c\u8bc1', 'default': 600, 'minimum': 30, 'maximum': 3600},
    {'key': 'manual_login', 'name': '\u624b\u52a8\u767b\u5f55', 'default': 300, 'minimum': 30, 'maximum': 3600},
    {'key': 'avfan_page_load', 'name': '\u5929\u9668\u9601\u9875\u9762\u52a0\u8f7d', 'default': 60, 'minimum': 5, 'maximum': 600},
    {'key': 'javtxt_page_load', 'name': '\u8f9b\u805a\u9601\u9875\u9762\u52a0\u8f7d', 'default': 60, 'minimum': 5, 'maximum': 600},
    {'key': 'binghuo_page_load', 'name': '\u5e76\u706b\u9875\u9762\u52a0\u8f7d', 'default': 60, 'minimum': 5, 'maximum': 600},
    {'key': 'baomu_page_load', 'name': '\u4fdd\u6728\u9875\u9762\u52a0\u8f7d', 'default': 60, 'minimum': 5, 'maximum': 600},
    {'key': 'queen_page_load', 'name': '\u5973\u738b\u5e93\u6293\u53d6\u9875\u9762\u52a0\u8f7d', 'default': 120, 'minimum': 5, 'maximum': 600},
    {'key': 'network_probe', 'name': '\u7f51\u7edc\u68c0\u6d4b', 'default': 0.8, 'minimum': 0.1, 'maximum': 30},
    {'key': 'database_wait', 'name': '\u6570\u636e\u5e93\u7b49\u5f85', 'default': 60, 'minimum': 1, 'maximum': 300},
    {'key': 'local_media_read', 'name': '\u672c\u5730\u5a92\u4f53\u4fe1\u606f\u8bfb\u53d6', 'default': 15, 'minimum': 1, 'maximum': 300},
)

OPERATION_TIMEOUT_SPEC_MAP = {
    spec['key']: dict(spec)
    for spec in OPERATION_TIMEOUT_SPECS
}


def ensure_operation_timeout_settings_table(cursor):
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS operation_timeout_settings (
            setting_key TEXT PRIMARY KEY,
            custom_value_seconds REAL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )


def list_operation_timeout_settings(db_path=None):
    overrides = _load_overrides(db_path)
    rows = []
    for spec in OPERATION_TIMEOUT_SPECS:
        key = spec['key']
        custom_value = overrides.get(key)
        effective_value = spec['default'] if custom_value is None else custom_value
        rows.append(
            {
                'setting_key': key,
                'operation_name': spec['name'],
                'default_value_seconds': spec['default'],
                'custom_value_seconds': custom_value,
                'effective_value_seconds': effective_value,
                'uses_default': custom_value is None,
                'minimum_value_seconds': spec['minimum'],
                'maximum_value_seconds': spec['maximum'],
            }
        )
    return rows


def get_operation_timeout_seconds(setting_key, db_path=None):
    normalized_key = str(setting_key or '').strip()
    spec = OPERATION_TIMEOUT_SPEC_MAP.get(normalized_key)
    if spec is None:
        raise ValueError(f'Unknown operation timeout setting: {normalized_key}')
    override = _load_overrides(db_path, keys=[normalized_key]).get(normalized_key)
    return spec['default'] if override is None else override


def get_operation_timeout_milliseconds(setting_key, db_path=None):
    return max(1, int(round(get_operation_timeout_seconds(setting_key, db_path) * 1000)))


def set_operation_timeout_overrides(values, db_path=None):
    normalized_values = {}
    for setting_key, raw_value in dict(values or {}).items():
        normalized_key = str(setting_key or '').strip()
        spec = OPERATION_TIMEOUT_SPEC_MAP.get(normalized_key)
        if spec is None:
            raise ValueError(f'Unknown operation timeout setting: {normalized_key}')
        if raw_value is None or str(raw_value).strip() == '':
            normalized_values[normalized_key] = None
            continue
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid timeout value for {normalized_key}: {raw_value}') from exc
        if not math.isfinite(numeric_value):
            raise ValueError(f'Invalid timeout value for {normalized_key}: {raw_value}')
        if numeric_value < float(spec['minimum']) or numeric_value > float(spec['maximum']):
            raise ValueError(
                f'Timeout value for {normalized_key} must be between '
                f'{spec["minimum"]} and {spec["maximum"]} seconds'
            )
        normalized_values[normalized_key] = numeric_value

    with _connect_settings_database(db_path) as conn:
        ensure_operation_timeout_settings_table(conn.cursor())
        for setting_key, numeric_value in normalized_values.items():
            if numeric_value is None:
                conn.execute(
                    'DELETE FROM operation_timeout_settings WHERE setting_key = ?',
                    (setting_key,),
                )
                continue
            conn.execute(
                '''
                INSERT INTO operation_timeout_settings (setting_key, custom_value_seconds, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key) DO UPDATE SET
                    custom_value_seconds = excluded.custom_value_seconds,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (setting_key, numeric_value),
            )
        conn.commit()
    return list_operation_timeout_settings(db_path)


def reset_operation_timeout_overrides(setting_keys=None, db_path=None):
    normalized_keys = None
    if setting_keys is not None:
        normalized_keys = []
        for setting_key in setting_keys or []:
            normalized_key = str(setting_key or '').strip()
            if normalized_key not in OPERATION_TIMEOUT_SPEC_MAP:
                raise ValueError(f'Unknown operation timeout setting: {normalized_key}')
            if normalized_key not in normalized_keys:
                normalized_keys.append(normalized_key)

    with _connect_settings_database(db_path) as conn:
        ensure_operation_timeout_settings_table(conn.cursor())
        if normalized_keys is None:
            conn.execute('DELETE FROM operation_timeout_settings')
        elif normalized_keys:
            placeholders = ','.join('?' for _ in normalized_keys)
            conn.execute(
                f'DELETE FROM operation_timeout_settings WHERE setting_key IN ({placeholders})',
                normalized_keys,
            )
        conn.commit()
    return list_operation_timeout_settings(db_path)


def _load_overrides(db_path=None, keys=None):
    with _connect_settings_database(db_path) as conn:
        ensure_operation_timeout_settings_table(conn.cursor())
        if keys:
            normalized_keys = [str(key or '').strip() for key in keys if str(key or '').strip()]
            placeholders = ','.join('?' for _ in normalized_keys)
            rows = conn.execute(
                f'''
                SELECT setting_key, custom_value_seconds
                FROM operation_timeout_settings
                WHERE setting_key IN ({placeholders})
                ''',
                normalized_keys,
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT setting_key, custom_value_seconds FROM operation_timeout_settings'
            ).fetchall()
        conn.commit()
    return {
        str(row[0] or '').strip(): float(row[1])
        for row in rows
        if str(row[0] or '').strip() in OPERATION_TIMEOUT_SPEC_MAP and row[1] is not None
    }


@contextmanager
def _connect_settings_database(db_path=None):
    target_path = Path(db_path or DATABASE_FILE)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(target_path),
        timeout=OPERATION_TIMEOUT_SPEC_MAP['database_wait']['default'],
    )
    try:
        yield conn
    finally:
        conn.close()
