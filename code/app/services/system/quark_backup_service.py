"""Five-day Quark Pan backups for persistent local user data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.app_logging import get_logger
from app.core.project_paths import (
    QUARK_BACKUP_ARCHIVE_DIR,
    QUARK_BACKUP_CONFIG_FILE,
    QUARK_BACKUP_LOCK_FILE,
    QUARK_BACKUP_STATE_FILE,
    USER_DATA_DIR,
)
from app.services.system.quark_auth_service import QuarkCredentialStore, is_quark_client_authenticated


LOGGER = get_logger(__name__)
ARCHIVE_PREFIX = 'local_video_renamer_user_data_'
DEFAULT_REMOTE_FOLDER_NAME = 'Local-Video-Renamer-Backup'
DEFAULT_INTERVAL_DAYS = 5
LEGACY_UPLOAD_HOST_SUFFIX = '.oss-cn-shenzhen.aliyuncs.com'
CURRENT_UPLOAD_HOST_SUFFIX = '.pds.quark.cn'


def _rewrite_legacy_upload_url(upload_url):
    raw_url = str(upload_url or '').strip()
    if not raw_url:
        return raw_url
    parsed = urlsplit(raw_url)
    host = str(parsed.hostname or '').lower()
    if not host.endswith(LEGACY_UPLOAD_HOST_SUFFIX):
        return raw_url
    bucket = host[: -len(LEGACY_UPLOAD_HOST_SUFFIX)]
    if not bucket:
        return raw_url
    netloc = f'{bucket}{CURRENT_UPLOAD_HOST_SUFFIX}'
    if parsed.port is not None:
        netloc = f'{netloc}:{parsed.port}'
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _rewrite_upload_auth_result(result):
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    normalized['upload_url'] = _rewrite_legacy_upload_url(normalized.get('upload_url'))
    return normalized


def apply_quark_upload_endpoint_compat(client):
    upload_service = getattr(client, 'upload', None)
    if upload_service is None or getattr(upload_service, '_vidnorm_endpoint_compat', False):
        return client

    patched = False
    for method_name in ('_get_upload_auth', '_get_complete_upload_auth'):
        original = getattr(upload_service, method_name, None)
        if not callable(original):
            continue

        def wrapped(*args, _original=original, **kwargs):
            return _rewrite_upload_auth_result(_original(*args, **kwargs))

        setattr(upload_service, method_name, wrapped)
        patched = True

    if patched:
        setattr(upload_service, '_vidnorm_endpoint_compat', True)
        LOGGER.info('已启用 quarkpan 旧版上传端点兼容')
    return client


class QuarkBackupService:
    def __init__(
        self,
        *,
        config_path=QUARK_BACKUP_CONFIG_FILE,
        state_path=QUARK_BACKUP_STATE_FILE,
        source_dir=USER_DATA_DIR,
        archive_dir=QUARK_BACKUP_ARCHIVE_DIR,
        lock_path=None,
        credential_store=None,
        client_factory=None,
        now_factory=None,
    ):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.source_dir = Path(source_dir)
        self.archive_dir = Path(archive_dir)
        self.lock_path = Path(lock_path) if lock_path is not None else (
            QUARK_BACKUP_LOCK_FILE
            if self.config_path == QUARK_BACKUP_CONFIG_FILE
            else self.config_path.with_suffix('.lock')
        )
        self.credential_store = credential_store or QuarkCredentialStore(
            self.config_path.with_name('quark_credentials.dat')
        )
        self.client_factory = client_factory or self._create_client
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _create_client(cookie):
        from quark_client import QuarkClient

        return QuarkClient(cookies=cookie, auto_login=False)

    def load_config(self):
        if not self.config_path.is_file():
            return {'enabled': False}
        payload = json.loads(self.config_path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise ValueError('夸克备份配置必须是 JSON 对象')
        return {
            'enabled': bool(payload.get('enabled', False)),
            'cookie': str(payload.get('cookie', '') or '').strip(),
            'remote_parent_folder_id': str(payload.get('remote_parent_folder_id', '0') or '0').strip(),
            'remote_folder_name': str(payload.get('remote_folder_name', DEFAULT_REMOTE_FOLDER_NAME) or '').strip(),
            'interval_days': max(1, int(payload.get('interval_days', DEFAULT_INTERVAL_DAYS) or DEFAULT_INTERVAL_DAYS)),
        }

    def run_if_due(self):
        config = self.load_config()
        if not config['enabled']:
            return {'status': 'disabled'}
        now = self.now_factory()
        if not self.is_due(now, config['interval_days']):
            return {'status': 'not_due'}
        cookie = self._resolve_cookie(config)
        if not cookie:
            LOGGER.warning('夸克备份需要登录，计划任务不会启动交互登录')
            return {'status': 'login_required', 'error': '需要先登录夸克网盘'}
        return self._run_with_lock(config, now, cookie)

    def run_now(self):
        config = self.load_config()
        if not config['enabled']:
            return {'status': 'disabled'}
        cookie = self._resolve_cookie(config)
        if not cookie:
            LOGGER.warning('夸克备份需要登录，手动上传应引导用户扫码')
            return {'status': 'login_required', 'error': '需要先登录夸克网盘'}
        return self._run_with_lock(config, self.now_factory(), cookie)

    def _resolve_cookie(self, config):
        return self.credential_store.load_cookie() or str(config.get('cookie', '') or '').strip()

    def _run_with_lock(self, config, now, cookie):
        if not self._acquire_lock():
            return {'status': 'running', 'error': '已有夸克备份正在执行'}
        try:
            return self._run_backup(config, now, cookie)
        finally:
            self._release_lock()

    def _acquire_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_path.open('x', encoding='utf-8') as stream:
                stream.write(self.now_factory().isoformat())
        except FileExistsError:
            return False
        return True

    def _release_lock(self):
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning('无法清理夸克备份锁文件: %s', self.lock_path)

    def is_due(self, now=None, interval_days=DEFAULT_INTERVAL_DAYS):
        last_success_at = str(self._load_state().get('last_success_at', '') or '').strip()
        if not last_success_at:
            return True
        try:
            last_success = datetime.fromisoformat(last_success_at)
        except ValueError:
            return True
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        current = now or self.now_factory()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current >= last_success + timedelta(days=max(1, int(interval_days)))

    def create_archive(self, now=None):
        moment = now or self.now_factory()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.archive_dir / f'{ARCHIVE_PREFIX}{moment.strftime("%Y%m%d_%H%M%S")}.zip'
        excluded_paths = {
            self.config_path.resolve(),
            self.state_path.resolve(),
            Path(self.credential_store.path).resolve(),
        }
        with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED, allowZip64=True, strict_timestamps=False) as archive:
            for path in sorted(self.source_dir.rglob('*')):
                if not path.is_file() or path.resolve() in excluded_paths:
                    continue
                archive.write(path, Path('user_data') / path.relative_to(self.source_dir))
        return archive_path

    def _run_backup(self, config, now, cookie):
        archive_path = None
        client = None
        try:
            client = self.client_factory(cookie)
            apply_quark_upload_endpoint_compat(client)
            if not is_quark_client_authenticated(client):
                LOGGER.warning('夸克登录凭证已失效，需要重新登录')
                return {'status': 'login_required', 'error': '夸克登录已失效，需要重新扫码登录'}
            archive_path = self.create_archive(now)
            remote_folder_id = self._ensure_remote_folder(client, config)
            old_entries = self._list_files(client, remote_folder_id)
            upload_result = client.upload_file(str(archive_path), parent_folder_id=remote_folder_id)
            if str(upload_result.get('status', '')).lower() not in {'success', '200'}:
                raise RuntimeError(f'夸克上传失败: {upload_result.get("message", "未知错误")}')
            self._delete_old_archives(client, old_entries)
            digest = self._sha256(archive_path)
            self._write_state(
                {
                    'last_success_at': now.isoformat(),
                    'archive_name': archive_path.name,
                    'archive_sha256': digest,
                    'remote_folder_id': remote_folder_id,
                }
            )
            LOGGER.info('夸克备份完成 archive=%s sha256=%s', archive_path.name, digest)
            return {'status': 'completed', 'archive_name': archive_path.name, 'sha256': digest}
        except Exception as exc:
            LOGGER.exception('夸克备份失败')
            return {'status': 'failed', 'error': str(exc)}
        finally:
            close = getattr(client, 'close', None)
            if callable(close):
                close()
            if archive_path is not None:
                try:
                    archive_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning('无法清理临时夸克备份文件: %s', archive_path)

    def _ensure_remote_folder(self, client, config):
        parent_id = config['remote_parent_folder_id'] or '0'
        folder_name = config['remote_folder_name'] or DEFAULT_REMOTE_FOLDER_NAME
        for entry in self._list_files(client, parent_id):
            if str(entry.get('file_name', '')) == folder_name and str(entry.get('file_type', '')) == '0':
                return str(entry.get('fid', ''))
        result = client.create_folder(folder_name, parent_id)
        folder_id = str((result.get('data') or {}).get('fid', '') or '')
        if str(result.get('status', '')) not in {'200', 'success'} or not folder_id:
            raise RuntimeError(f'无法创建夸克备份目录: {result.get("message", "未知错误")}')
        return folder_id

    @staticmethod
    def _list_files(client, folder_id):
        result = client.list_files(folder_id, page=1, size=100)
        return list((result.get('data') or {}).get('list') or [])

    @staticmethod
    def _delete_old_archives(client, entries):
        old_ids = [
            str(entry.get('fid', ''))
            for entry in entries
            if str(entry.get('file_name', '')).startswith(ARCHIVE_PREFIX)
            and str(entry.get('file_name', '')).endswith('.zip')
            and str(entry.get('fid', ''))
        ]
        if not old_ids:
            return
        result = client.delete_files(old_ids)
        if str(result.get('status', '')) not in {'200', 'success'}:
            raise RuntimeError(f'无法清理旧夸克备份: {result.get("message", "未知错误")}')

    def _load_state(self):
        if not self.state_path.is_file():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding='utf-8'))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _write_state(self, payload):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix('.tmp')
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary_path.replace(self.state_path)

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
