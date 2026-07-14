import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

from app.services.system.quark_backup_service import QuarkBackupService


class FakeQuarkClient:
    def __init__(self):
        self.created_folders = []
        self.uploads = []
        self.deleted_file_ids = []
        self.remote_entries = [
            {'fid': 'old-backup', 'file_name': 'local_video_renamer_user_data_20260101_030000.zip', 'file_type': 1},
            {'fid': 'unrelated', 'file_name': 'do-not-delete.txt', 'file_type': 1},
        ]

    def is_logged_in(self):
        return True

    def list_files(self, folder_id, **_kwargs):
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


def _write_config(path):
    path.write_text(
        json.dumps(
            {
                'enabled': True,
                'cookie': 'local-cookie',
                'remote_folder_name': 'Local-Video-Renamer-Backup',
                'interval_days': 5,
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )


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


def test_backup_archive_excludes_quark_cookie_configuration(tmp_path):
    source_dir = tmp_path / 'user_data'
    config_dir = source_dir / 'config'
    config_dir.mkdir(parents=True)
    (source_dir / 'notes.txt').write_text('keep', encoding='utf-8')
    config_path = config_dir / 'quark_backup.json'
    _write_config(config_path)
    service = QuarkBackupService(
        config_path=config_path,
        state_path=config_dir / 'quark_backup_state.json',
        source_dir=source_dir,
        archive_dir=tmp_path / 'archives',
        now_factory=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    archive_path = service.create_archive()

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert 'user_data/notes.txt' in names
    assert 'user_data/config/quark_backup.json' not in names


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


def test_scheduled_task_runner_loads_from_the_scripts_directory(tmp_path):
    runner_path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_quark_backup.py'

    result = subprocess.run(
        [sys.executable, str(runner_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
