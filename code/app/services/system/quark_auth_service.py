"""Interactive Quark QR authentication and local encrypted credentials."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from io import BytesIO
from pathlib import Path

from app.core.app_logging import get_logger
from app.core.project_paths import QUARK_CREDENTIAL_FILE


LOGGER = get_logger(__name__)
_CREDENTIAL_MAGIC = b'LVRQ1'
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_ulong), ('pbData', ctypes.c_void_p)]


def _dpapi_transform(data, function_name, *, description=None):
    if os.name != 'nt':
        raise OSError('Windows DPAPI is unavailable on this platform')
    payload = bytes(data)
    buffer = ctypes.create_string_buffer(payload, len(payload))
    input_blob = _DataBlob(len(payload), ctypes.cast(buffer, ctypes.c_void_p))
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    function = getattr(crypt32, function_name)
    function.restype = ctypes.c_bool
    if function_name == 'CryptProtectData':
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_wchar_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_DataBlob),
        ]
        succeeded = function(
            ctypes.byref(input_blob),
            description,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    else:
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(ctypes.c_wchar_p),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_DataBlob),
        ]
        succeeded = function(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(output_blob.pbData)


def _protect_for_current_user(data):
    return _dpapi_transform(data, 'CryptProtectData', description='Local Video Renamer Quark credential')


def _unprotect_for_current_user(data):
    return _dpapi_transform(data, 'CryptUnprotectData')


class QuarkCredentialStore:
    def __init__(self, path=QUARK_CREDENTIAL_FILE, *, protect=None, unprotect=None):
        self.path = Path(path)
        self._protect = protect or _protect_for_current_user
        self._unprotect = unprotect or _unprotect_for_current_user

    def save_cookie(self, cookie):
        normalized = str(cookie or '').strip()
        if not normalized:
            raise ValueError('夸克登录凭证不能为空')
        encrypted = bytes(self._protect(normalized.encode('utf-8')))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix('.tmp')
        temporary_path.write_bytes(_CREDENTIAL_MAGIC + encrypted)
        temporary_path.replace(self.path)

    def load_cookie(self):
        if not self.path.is_file():
            return ''
        try:
            payload = self.path.read_bytes()
            if not payload.startswith(_CREDENTIAL_MAGIC):
                return ''
            return bytes(self._unprotect(payload[len(_CREDENTIAL_MAGIC):])).decode('utf-8').strip()
        except (OSError, UnicodeError, ValueError):
            LOGGER.warning('无法读取夸克加密凭证，需要重新扫码登录')
            return ''

    def clear(self):
        self.path.unlink(missing_ok=True)


class _QuarkPanQrAdapter:
    def __init__(self, timeout=300):
        from quark_client.auth.api_login import APILogin

        self._login = APILogin(timeout=timeout)
        self._login.logger.setLevel(logging.WARNING)
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)

    def start_session(self):
        return self._login.get_qr_code()

    def poll(self, token):
        result = self._login.check_login_status(token)
        if not result or not self._login._is_login_success(result):
            return {'status': 'pending'}
        service_ticket = str(
            ((result.get('data') or {}).get('members') or {}).get('service_ticket') or ''
        ).strip()
        if not service_ticket:
            return {'status': 'failed'}
        response = self._login.client.get(
            'https://pan.quark.cn/account/info',
            params={'st': service_ticket, 'lw': 'scan'},
        )
        response.raise_for_status()
        cookies = [
            f'{cookie.name}={cookie.value}'
            for cookie in self._login.client.cookies.jar
            if cookie.domain and 'quark.cn' in cookie.domain
        ]
        cookie = '; '.join(cookies)
        return {'status': 'connected', 'cookie': cookie} if cookie else {'status': 'failed'}

    def close(self):
        self._login.client.close()


def _render_qr_png(url):
    import qrcode

    image = qrcode.make(str(url))
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def is_quark_client_authenticated(client):
    try:
        result = dict(client.list_files('0', page=1, size=1) or {})
    except Exception:
        return False
    return str(result.get('status', '') or '').strip().lower() in {'200', 'success'}


class QuarkAuthService:
    def __init__(
        self,
        *,
        credential_store=None,
        adapter_factory=None,
        client_factory=None,
        qr_renderer=None,
        sleep=None,
        monotonic=None,
        poll_interval=2,
        timeout=300,
    ):
        self.credential_store = credential_store or QuarkCredentialStore()
        self.adapter_factory = adapter_factory or (lambda: _QuarkPanQrAdapter(timeout=timeout))
        self.client_factory = client_factory or self._create_client
        self.qr_renderer = qr_renderer or _render_qr_png
        self.sleep = sleep or time.sleep
        self.monotonic = monotonic or time.monotonic
        self.poll_interval = max(0, float(poll_interval))
        self.timeout = max(1, float(timeout))

    @staticmethod
    def _create_client(cookie):
        from quark_client import QuarkClient

        return QuarkClient(cookies=cookie, auto_login=False)

    def has_saved_credential(self):
        return bool(self.credential_store.load_cookie())

    def validate_saved_credential(self):
        cookie = self.credential_store.load_cookie()
        return bool(cookie and self._validate_cookie(cookie))

    def _validate_cookie(self, cookie):
        client = self.client_factory(cookie)
        try:
            return is_quark_client_authenticated(client)
        finally:
            close = getattr(client, 'close', None)
            if callable(close):
                close()

    def login(self, cancel_event=None, qr_callback=None, status_callback=None):
        cancellation = cancel_event or threading.Event()
        emit_qr = qr_callback or (lambda _payload: None)
        emit_status = status_callback or (lambda _status: None)
        adapter = self.adapter_factory()
        started_at = self.monotonic()
        try:
            token, qr_url = adapter.start_session()
            emit_qr(self.qr_renderer(qr_url))
            emit_status('waiting_scan')
            while self.monotonic() - started_at < self.timeout:
                if cancellation.is_set():
                    emit_status('cancelled')
                    return {'status': 'cancelled'}
                result = dict(adapter.poll(token) or {})
                state = str(result.get('status', 'pending') or 'pending').strip().lower()
                if state == 'connected':
                    cookie = str(result.get('cookie', '') or '').strip()
                    if cookie and self._validate_cookie(cookie):
                        self.credential_store.save_cookie(cookie)
                        emit_status('connected')
                        return {'status': 'connected'}
                    emit_status('failed')
                    return {'status': 'failed', 'error': '夸克登录凭证验证失败'}
                if state in {'failed', 'expired'}:
                    emit_status(state)
                    return {'status': state, 'error': '夸克扫码登录失败或二维码已过期'}
                self.sleep(self.poll_interval)
            emit_status('expired')
            return {'status': 'expired', 'error': '夸克登录二维码已过期'}
        except Exception as exc:
            LOGGER.warning('夸克扫码登录失败 error_type=%s', type(exc).__name__)
            emit_status('failed')
            return {'status': 'failed', 'error': '夸克扫码登录失败，请检查网络后重试'}
        finally:
            adapter.close()
