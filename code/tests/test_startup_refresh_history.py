from app.data.database_handler import VideoDatabase
from app.backend.service import BackendService
from app.backend.client import BackendClient
from app.backend.server import make_handler
from types import SimpleNamespace
from unittest.mock import Mock


def test_startup_refresh_history_records_and_replaces_completion(tmp_path):
    database = VideoDatabase(tmp_path / 'video_database.db')

    database.record_startup_refresh_completion(
        'actor_library',
        '启动刷新 演员库',
        completed_at='2026-07-29 10:00:00',
    )
    database.record_startup_refresh_completion(
        'actor_library',
        '启动刷新 演员库（重试）',
        completed_at='2026-07-29 11:00:00',
    )

    assert database.list_startup_refresh_history() == {
        'actor_library': {
            'task_key': 'actor_library',
            'task_title': '启动刷新 演员库（重试）',
            'last_completed_at': '2026-07-29 11:00:00',
        }
    }


def test_backend_service_exposes_startup_refresh_history(tmp_path):
    service = BackendService.__new__(BackendService)
    service.db = VideoDatabase(tmp_path / 'video_database.db')
    service.ensure_database_loaded = lambda: None

    recorded = service.record_startup_refresh_completion(
        'code_prefix_library',
        '启动刷新 番号库',
        completed_at='2026-07-29 12:00:00',
    )

    assert recorded['history']['code_prefix_library']['last_completed_at'] == '2026-07-29 12:00:00'
    assert service.list_startup_refresh_history()['history'] == recorded['history']


def test_backend_client_uses_startup_refresh_history_routes():
    client = BackendClient(base_url='http://127.0.0.1:8766')
    calls = []
    client._get = lambda path: calls.append(('get', path)) or {'history': {}}
    client._post = lambda path, payload=None: calls.append(('post', path, payload)) or {'history': {}}

    assert client.list_startup_refresh_history() == {}
    assert client.record_startup_refresh_completion(
        'actor_library',
        '启动刷新 演员库',
        completed_at='2026-07-29 12:00:00',
    ) == {}
    assert calls == [
        ('get', '/startup-refresh-history'),
        ('post', '/startup-refresh-history', {
            'task_key': 'actor_library',
            'task_title': '启动刷新 演员库',
            'completed_at': '2026-07-29 12:00:00',
        }),
    ]


def test_server_routes_startup_refresh_history_requests():
    service = Mock()
    service.list_startup_refresh_history.return_value = {'history': {}}
    service.record_startup_refresh_completion.return_value = {'history': {}}
    handler = make_handler(service)

    assert handler._route(object(), 'GET', SimpleNamespace(path='/startup-refresh-history', query=''), {}) == {
        'history': {}
    }
    assert handler._route(
        object(),
        'POST',
        SimpleNamespace(path='/startup-refresh-history', query=''),
        {'task_key': 'actor_library', 'task_title': '启动刷新 演员库', 'completed_at': '2026-07-29 12:00:00'},
    ) == {'history': {}}
    service.record_startup_refresh_completion.assert_called_once_with(
        'actor_library',
        '启动刷新 演员库',
        '2026-07-29 12:00:00',
    )
