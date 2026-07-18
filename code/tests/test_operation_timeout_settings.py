import math
import sqlite3

import pytest


EXPECTED_KEYS = [
    'backend_request',
    'list_detail_load',
    'snapshot_refresh_rebuild',
    'automatic_login',
    'manual_verification',
    'manual_login',
    'browser_launch',
    'avfan_page_load',
    'javtxt_page_load',
    'binghuo_page_load',
    'baomu_page_load',
    'queen_page_load',
    'network_probe',
    'database_wait',
    'local_media_read',
]


def test_timeout_registry_lists_defaults_in_stable_order(tmp_path):
    from app.core.operation_timeout_settings import list_operation_timeout_settings

    rows = list_operation_timeout_settings(tmp_path / 'timeouts.db')

    assert [row['setting_key'] for row in rows] == EXPECTED_KEYS
    assert rows[0]['default_value_seconds'] == 30
    assert rows[0]['custom_value_seconds'] is None
    assert rows[0]['effective_value_seconds'] == 30
    assert rows[0]['uses_default'] is True
    assert rows[12]['default_value_seconds'] == 0.8


def test_timeout_override_supports_decimals_and_selected_reset(tmp_path):
    from app.core.operation_timeout_settings import (
        get_operation_timeout_seconds,
        list_operation_timeout_settings,
        reset_operation_timeout_overrides,
        set_operation_timeout_overrides,
    )

    db_path = tmp_path / 'timeouts.db'
    set_operation_timeout_overrides(
        {
            'network_probe': '1.25',
            'database_wait': 75,
        },
        db_path,
    )

    assert get_operation_timeout_seconds('network_probe', db_path) == 1.25
    assert get_operation_timeout_seconds('database_wait', db_path) == 75
    network_row = next(
        row for row in list_operation_timeout_settings(db_path)
        if row['setting_key'] == 'network_probe'
    )
    assert network_row['custom_value_seconds'] == 1.25
    assert network_row['effective_value_seconds'] == 1.25
    assert network_row['uses_default'] is False

    reset_operation_timeout_overrides(['network_probe'], db_path)

    assert get_operation_timeout_seconds('network_probe', db_path) == 0.8
    assert get_operation_timeout_seconds('database_wait', db_path) == 75


def test_timeout_override_validation_is_atomic(tmp_path):
    from app.core.operation_timeout_settings import (
        get_operation_timeout_seconds,
        set_operation_timeout_overrides,
    )

    db_path = tmp_path / 'timeouts.db'
    set_operation_timeout_overrides({'backend_request': 45}, db_path)

    invalid_values = [0, -1, math.inf, math.nan, 'not-a-number', 99999]
    for invalid_value in invalid_values:
        with pytest.raises(ValueError):
            set_operation_timeout_overrides(
                {
                    'backend_request': 60,
                    'network_probe': invalid_value,
                },
                db_path,
            )
        assert get_operation_timeout_seconds('backend_request', db_path) == 45
        assert get_operation_timeout_seconds('network_probe', db_path) == 0.8

    with pytest.raises(ValueError, match='unknown_timeout'):
        set_operation_timeout_overrides({'unknown_timeout': 10}, db_path)


def test_reset_all_timeout_overrides_deletes_custom_rows(tmp_path):
    from app.core.operation_timeout_settings import (
        reset_operation_timeout_overrides,
        set_operation_timeout_overrides,
    )

    db_path = tmp_path / 'timeouts.db'
    set_operation_timeout_overrides({'backend_request': 45, 'database_wait': 75}, db_path)

    reset_operation_timeout_overrides(None, db_path)

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            'SELECT setting_key, custom_value_seconds FROM operation_timeout_settings'
        ).fetchall()
    assert rows == []


def test_backend_client_timeout_settings_api_paths():
    from app.backend.client import BackendClient

    client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
    calls = []
    client._get = lambda path, timeout=None: calls.append(('get', path, timeout)) or {'settings': []}
    client._post = lambda path, payload=None, timeout=None: calls.append(
        ('post', path, payload, timeout)
    ) or {'settings': []}

    assert client.list_operation_timeouts() == []
    assert client.update_operation_timeouts({'network_probe': 1.5}) == []
    assert client.reset_operation_timeouts(['network_probe']) == []
    assert client.reset_operation_timeouts() == []
    assert calls == [
        ('get', '/settings/timeouts', None),
        ('post', '/settings/timeouts', {'values': {'network_probe': 1.5}}, None),
        ('post', '/settings/timeouts/reset', {'setting_keys': ['network_probe']}, None),
        ('post', '/settings/timeouts/reset', {'setting_keys': None}, None),
    ]


def test_backend_client_default_request_reads_runtime_timeout(monkeypatch):
    import app.backend.client as client_module
    from app.backend.client import BackendClient

    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {'ok': True}

    monkeypatch.setattr(
        client_module,
        'get_operation_timeout_seconds',
        lambda setting_key: 47.5 if setting_key == 'backend_request' else 120,
        raising=False,
    )
    monkeypatch.setattr(
        client_module.requests,
        'get',
        lambda url, timeout=None: calls.append((url, timeout)) or Response(),
    )

    result = BackendClient(base_url='http://127.0.0.1:8766')._get('/health')

    assert result == {'ok': True}
    assert calls == [('http://127.0.0.1:8766/health', 47.5)]


def test_network_guard_reads_runtime_timeout_for_each_probe(monkeypatch):
    import app.services.system.network_guard_service as guard_module
    from app.services.system.network_guard_service import NetworkGuardService

    observed_timeouts = []

    class Connection:
        @staticmethod
        def close():
            return None

    monkeypatch.setattr(
        guard_module,
        'get_operation_timeout_seconds',
        lambda setting_key: 1.25,
        raising=False,
    )
    monkeypatch.setattr(
        guard_module.socket,
        'create_connection',
        lambda address, timeout=None: observed_timeouts.append(timeout) or Connection(),
    )
    service = NetworkGuardService(
        targets=[{'label': 'example', 'host': 'example.com', 'port': 443}],
        timeout_seconds=None,
    )

    assert service.probe()['is_online'] is True
    assert observed_timeouts == [1.25]


def test_timeout_validation_rejects_non_finite_and_c_timeval_overflow():
    from app.core.timeout_policy import (
        MAX_SOCKET_TIMEOUT_SECONDS,
        validate_timeout_milliseconds,
        validate_timeout_seconds,
    )

    assert validate_timeout_seconds(30, name='http') == 30.0
    assert validate_timeout_milliseconds(120000, name='browser') == 120000
    with pytest.raises(ValueError, match='http'):
        validate_timeout_seconds(float('inf'), name='http')
    with pytest.raises(ValueError, match='socket'):
        validate_timeout_seconds(MAX_SOCKET_TIMEOUT_SECONDS + 1, name='socket')


def test_backend_client_sends_validated_http_timeout(monkeypatch):
    import app.backend.client as client_module
    from app.backend.client import BackendClient

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {'ok': True}

        @staticmethod
        def raise_for_status():
            return None

    calls = []
    monkeypatch.setattr(client_module.requests, 'get', lambda url, timeout=None: calls.append(timeout) or Response())
    assert BackendClient(base_url='http://127.0.0.1:8766', timeout=60)._get('/health') == {'ok': True}
    assert calls == [60.0]


def test_backend_client_normalizes_legacy_millisecond_timeout():
    from app.backend.client import BackendClient

    client = BackendClient(base_url='http://127.0.0.1:8766', timeout=3_000_000)

    assert client.timeout == 3000.0


def test_task_trace_logger_records_exception_traceback_and_timeout_snapshot(tmp_path):
    from app.services.enrichment.task_trace_logger import TaskTraceLogger

    logger = TaskTraceLogger('test', 'timeout', 'timeout test', log_dir=tmp_path)
    try:
        raise OverflowError("timeout doesn't fit into C timeval")
    except Exception as exc:
        logger.log_exception(
            'ERROR',
            '请求异常',
            exc,
            phase='http',
            timeout_seconds=60.0,
            timeout_milliseconds=120000,
        )

    contents = logger.log_path.read_text(encoding='utf-8')
    assert 'OverflowError' in contents
    assert "timeout doesn't fit into C timeval" in contents
    assert 'phase=http' in contents
    assert 'timeout_seconds=60.0' in contents
