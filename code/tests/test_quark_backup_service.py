import json
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

from app.services.system import quark_backup_service
from app.services.system.quark_backup_service import QuarkBackupService


class FakeQuarkClient:
    def __init__(self, logged_in=True):
        self.logged_in = logged_in
        self.created_folders = []
        self.uploads = []
        self.deleted_file_ids = []
        self.remote_entries = [
            {'fid': 'old-backup', 'file_name': 'local_video_renamer_user_data_20260101_030000.zip', 'file_type': 1},
            {'fid': 'unrelated', 'file_name': 'do-not-delete.txt', 'file_type': 1},
        ]

    def is_logged_in(self):
        raise AssertionError('validation must use an authenticated API request')

    def list_files(self, folder_id, **_kwargs):
        if not self.logged_in:
            return {'status': 401, 'data': {'list': []}}
        if folder_id == '0':
            return {'status': 200, 'data': {'list': []}}
        return {'status': 200, 'data': {'list': list(self.remote_entries)}}

    def create_folder(self, folder_name, parent_id):
        self.created_folders.append((folder_name, parent_id))
        return {'status': 200, 'data': {'fid': 'backup-folder'}}

    def upload_file(self, file_path, parent_folder_id, progress_callback=None):
        self.uploads.append((Path(file_path), parent_folder_id))
        return {'status': 'success', 'fid': 'new-backup'}

    def delete_files(self, file_ids):
        self.deleted_file_ids.extend(file_ids)
        return {'status': 200}


class FakeCredentialStore:
    def __init__(self, path, cookie=''):
        self.path = Path(path)
        self.cookie = cookie

    def load_cookie(self):
        return self.cookie


def test_upload_endpoint_compat_rewrites_legacy_oss_hosts():
    class FakeUploadService:
        def _get_upload_auth(self):
            return {
                'upload_url': 'https://ul-zb.oss-cn-shenzhen.aliyuncs.com/path/file?partNumber=1',
                'headers': {'authorization': 'signed'},
            }

        def _get_complete_upload_auth(self):
            return {
                'upload_url': 'https://ul-zb.oss-cn-shenzhen.aliyuncs.com/path/file?uploadId=1',
                'headers': {'authorization': 'signed'},
            }

    client = type('Client', (), {'upload': FakeUploadService()})()

    compat = getattr(quark_backup_service, 'apply_quark_upload_endpoint_compat', None)
    assert callable(compat)
    compat(client)

    assert client.upload._get_upload_auth()['upload_url'] == (
        'https://ul-zb.pds.quark.cn/path/file?partNumber=1'
    )
    assert client.upload._get_complete_upload_auth()['upload_url'] == (
        'https://ul-zb.pds.quark.cn/path/file?uploadId=1'
    )


def _write_config(path, cookie='local-cookie'):
    path.write_text(
        json.dumps(
            {
                'enabled': True,
                'cookie': cookie,
                'remote_folder_name': 'Local-Video-Renamer-Backup',
                'interval_days': 5,
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )


def _load_scheduled_runner():
    runner_path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_quark_backup.py'
    spec = importlib.util.spec_from_file_location('run_quark_backup_test', runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def test_backup_uploads_new_archive_before_deleting_only_old_app_archives(tmp_path):
    source_dir = tmp_path / 'user_data'
    config_dir = source_dir / 'config'
    config_dir.mkdir(parents=True)
    (source_dir / 'databases').mkdir()
    (source_dir / 'databases' / 'video_database.db').write_text('database', encoding='utf-8')
    config_path = config_dir / 'quark_backup.json'
    _write_config(config_path)
    client = FakeQuarkClient()
    service = QuarkBackupService(
        config_path=config_path,
        state_path=config_dir / 'quark_backup_state.json',
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        client_factory=lambda _cookie: client,
        now_factory=lambda: datetime(2026, 7, 14, 3, tzinfo=timezone.utc),
    )

    result = service.run_if_due()

    assert result['status'] == 'completed'
    assert client.uploads[0][1] == 'backup-folder'
    assert client.deleted_file_ids == ['old-backup']
    assert not list((tmp_path / 'archives').glob('*.zip'))
    state = json.loads((config_dir / 'quark_backup_state.json').read_text(encoding='utf-8'))
    assert state['last_success_at'] == '2026-07-14T03:00:00+00:00'


def test_backup_archive_excludes_all_quark_authentication_files(tmp_path):
    source_dir = tmp_path / 'user_data'
    config_dir = source_dir / 'config'
    config_dir.mkdir(parents=True)
    (source_dir / 'notes.txt').write_text('keep', encoding='utf-8')
    config_path = config_dir / 'quark_backup.json'
    _write_config(config_path)
    state_path = config_dir / 'quark_backup_state.json'
    state_path.write_text('{}', encoding='utf-8')
    credential_path = config_dir / 'quark_credentials.dat'
    credential_path.write_bytes(b'encrypted-secret')
    service = QuarkBackupService(
        config_path=config_path,
        state_path=state_path,
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        credential_store=FakeCredentialStore(credential_path, 'encrypted-cookie'),
        now_factory=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    archive_path = service.create_archive()

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert 'user_data/notes.txt' in names
    assert 'user_data/config/quark_backup.json' not in names
    assert 'user_data/config/quark_backup_state.json' not in names
    assert 'user_data/config/quark_credentials.dat' not in names


def test_encrypted_credential_takes_precedence_over_legacy_cookie(tmp_path):
    source_dir = tmp_path / 'user_data'
    source_dir.mkdir()
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path, cookie='legacy-cookie')
    used_cookies = []
    client = FakeQuarkClient()
    service = QuarkBackupService(
        config_path=config_path,
        state_path=tmp_path / 'state.json',
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        credential_store=FakeCredentialStore(tmp_path / 'credential.dat', 'encrypted-cookie'),
        client_factory=lambda cookie: used_cookies.append(cookie) or client,
    )

    result = service.run_now()

    assert result['status'] == 'completed'
    assert used_cookies == ['encrypted-cookie']


def test_legacy_cookie_is_used_when_encrypted_credential_is_missing(tmp_path):
    source_dir = tmp_path / 'user_data'
    source_dir.mkdir()
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path, cookie='legacy-cookie')
    used_cookies = []
    service = QuarkBackupService(
        config_path=config_path,
        state_path=tmp_path / 'state.json',
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        credential_store=FakeCredentialStore(tmp_path / 'credential.dat'),
        client_factory=lambda cookie: used_cookies.append(cookie) or FakeQuarkClient(),
    )

    result = service.run_now()

    assert result['status'] == 'completed'
    assert used_cookies == ['legacy-cookie']


def test_missing_or_invalid_credential_returns_login_required_before_archiving(tmp_path):
    source_dir = tmp_path / 'user_data'
    source_dir.mkdir()
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path, cookie='')
    archive_dir = tmp_path / 'archives'
    service = QuarkBackupService(
        config_path=config_path,
        state_path=tmp_path / 'state.json',
        source_dir=source_dir,
        archive_dir=archive_dir,
        credential_store=FakeCredentialStore(tmp_path / 'credential.dat'),
    )

    missing_result = service.run_now()

    assert missing_result['status'] == 'login_required'
    assert not list(archive_dir.glob('*.zip'))

    service.credential_store.cookie = 'expired-cookie'
    service.client_factory = lambda _cookie: FakeQuarkClient(logged_in=False)
    invalid_result = service.run_now()

    assert invalid_result['status'] == 'login_required'
    assert not list(archive_dir.glob('*.zip'))


def test_backup_is_not_due_until_five_days_after_last_success(tmp_path):
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path)
    state_path = tmp_path / 'quark_backup_state.json'
    state_path.write_text(
        json.dumps({'last_success_at': '2026-07-10T03:00:00+00:00'}),
        encoding='utf-8',
    )
    service = QuarkBackupService(
        config_path=config_path,
        state_path=state_path,
        source_dir=tmp_path,
        archive_dir=tmp_path / 'archives',
        now_factory=lambda: datetime(2026, 7, 14, 2, 59, tzinfo=timezone.utc),
    )

    assert service.run_if_due() == {'status': 'not_due'}
    assert service.is_due(datetime(2026, 7, 15, 3, tzinfo=timezone.utc))


def test_manual_backup_runs_even_when_the_scheduled_backup_is_not_due(tmp_path):
    source_dir = tmp_path / 'user_data'
    source_dir.mkdir()
    (source_dir / 'notes.txt').write_text('keep', encoding='utf-8')
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path)
    state_path = tmp_path / 'quark_backup_state.json'
    state_path.write_text(
        json.dumps({'last_success_at': '2026-07-14T03:00:00+00:00'}),
        encoding='utf-8',
    )
    client = FakeQuarkClient()
    service = QuarkBackupService(
        config_path=config_path,
        state_path=state_path,
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        client_factory=lambda _cookie: client,
        now_factory=lambda: datetime(2026, 7, 14, 4, tzinfo=timezone.utc),
    )

    result = service.run_now()

    assert result['status'] == 'completed'
    assert len(client.uploads) == 1


def test_manual_backup_skips_when_another_backup_holds_the_lock(tmp_path):
    source_dir = tmp_path / 'user_data'
    source_dir.mkdir()
    config_path = tmp_path / 'quark_backup.json'
    _write_config(config_path)
    lock_path = tmp_path / 'locks' / 'quark_backup.lock'
    lock_path.parent.mkdir()
    lock_path.write_text('running', encoding='utf-8')
    client = FakeQuarkClient()
    service = QuarkBackupService(
        config_path=config_path,
        state_path=tmp_path / 'quark_backup_state.json',
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        lock_path=lock_path,
        client_factory=lambda _cookie: client,
    )

    result = service.run_now()

    assert result['status'] == 'running'
    assert client.uploads == []


def test_scheduled_task_runner_loads_from_the_scripts_directory(monkeypatch):
    runner = _load_scheduled_runner()

    class DisabledService:
        def run_if_due(self):
            return {'status': 'disabled'}

    monkeypatch.setattr(runner, 'QuarkBackupService', DisabledService)
    monkeypatch.setattr(runner, 'ensure_storage_layout', lambda: None)
    monkeypatch.setattr(runner, 'configure_logging', lambda: None)

    assert runner.main() == 0


def test_scheduled_task_reports_login_required_without_starting_interactive_login(monkeypatch):
    runner = _load_scheduled_runner()

    class LoginRequiredService:
        def run_if_due(self):
            return {'status': 'login_required'}

    monkeypatch.setattr(runner, 'QuarkBackupService', LoginRequiredService)
    monkeypatch.setattr(runner, 'ensure_storage_layout', lambda: None)
    monkeypatch.setattr(runner, 'configure_logging', lambda: None)

    assert runner.main() == 2
