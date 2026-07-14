import threading

from app.services.system.quark_auth_service import QuarkAuthService, QuarkCredentialStore


class ReversibleProtector:
    @staticmethod
    def protect(value):
        return b'encrypted:' + bytes(value)[::-1]

    @staticmethod
    def unprotect(value):
        payload = bytes(value)
        if not payload.startswith(b'encrypted:'):
            raise ValueError('invalid payload')
        return payload[len(b'encrypted:'):][::-1]


class FakeClient:
    def __init__(self, cookie, valid=True):
        self.cookie = cookie
        self.valid = valid
        self.closed = False

    def is_logged_in(self):
        raise AssertionError('validation must use an authenticated API request')

    def list_files(self, _folder_id, **_kwargs):
        return {'status': 200 if self.valid else 401, 'data': {'list': []}}

    def close(self):
        self.closed = True


class FakeQrAdapter:
    def __init__(self, states):
        self.states = list(states)
        self.closed = False

    def start_session(self):
        return 'private-token', 'https://example.invalid/qr'

    def poll(self, _token):
        if self.states:
            return self.states.pop(0)
        return {'status': 'pending'}

    def close(self):
        self.closed = True


def _store(path):
    protector = ReversibleProtector()
    return QuarkCredentialStore(path, protect=protector.protect, unprotect=protector.unprotect)


def test_credential_store_encrypts_and_atomically_reloads_cookie(tmp_path):
    path = tmp_path / 'quark_credentials.dat'
    store = _store(path)

    store.save_cookie('__kps=secret; __uid=user')

    persisted = path.read_bytes()
    assert b'__kps' not in persisted
    assert store.load_cookie() == '__kps=secret; __uid=user'
    assert not path.with_suffix('.tmp').exists()


def test_credential_store_returns_empty_for_corrupt_payload_and_can_clear(tmp_path):
    path = tmp_path / 'quark_credentials.dat'
    path.write_bytes(b'not-a-credential')
    store = _store(path)

    assert store.load_cookie() == ''

    store.save_cookie('valid-cookie')
    store.clear()
    assert store.load_cookie() == ''
    assert not path.exists()


def test_qr_login_saves_only_after_validated_success(tmp_path):
    store = _store(tmp_path / 'credential.dat')
    adapter = FakeQrAdapter([
        {'status': 'pending'},
        {'status': 'connected', 'cookie': 'qr-cookie'},
    ])
    qr_payloads = []
    statuses = []
    service = QuarkAuthService(
        credential_store=store,
        adapter_factory=lambda: adapter,
        client_factory=lambda cookie: FakeClient(cookie, valid=True),
        qr_renderer=lambda url: f'png:{url}'.encode('utf-8'),
        sleep=lambda _seconds: None,
        poll_interval=0,
        timeout=30,
    )

    result = service.login(threading.Event(), qr_payloads.append, statuses.append)

    assert result['status'] == 'connected'
    assert store.load_cookie() == 'qr-cookie'
    assert qr_payloads == [b'png:https://example.invalid/qr']
    assert statuses == ['waiting_scan', 'connected']
    assert adapter.closed


def test_qr_login_does_not_replace_saved_cookie_when_validation_fails(tmp_path):
    store = _store(tmp_path / 'credential.dat')
    store.save_cookie('previous-cookie')
    adapter = FakeQrAdapter([{'status': 'connected', 'cookie': 'invalid-cookie'}])
    service = QuarkAuthService(
        credential_store=store,
        adapter_factory=lambda: adapter,
        client_factory=lambda cookie: FakeClient(cookie, valid=False),
        qr_renderer=lambda _url: b'png',
        sleep=lambda _seconds: None,
        poll_interval=0,
        timeout=30,
    )

    result = service.login(threading.Event(), lambda _png: None, lambda _status: None)

    assert result['status'] == 'failed'
    assert store.load_cookie() == 'previous-cookie'


def test_qr_login_stops_when_cancelled(tmp_path):
    cancel_event = threading.Event()
    cancel_event.set()
    adapter = FakeQrAdapter([])
    service = QuarkAuthService(
        credential_store=_store(tmp_path / 'credential.dat'),
        adapter_factory=lambda: adapter,
        client_factory=lambda cookie: FakeClient(cookie),
        qr_renderer=lambda _url: b'png',
        sleep=lambda _seconds: None,
        poll_interval=0,
        timeout=30,
    )

    result = service.login(cancel_event, lambda _png: None, lambda _status: None)

    assert result['status'] == 'cancelled'
    assert adapter.closed


def test_qr_login_expires_without_saving_cookie(tmp_path):
    moments = iter([0.0, 31.0])
    store = _store(tmp_path / 'credential.dat')
    service = QuarkAuthService(
        credential_store=store,
        adapter_factory=lambda: FakeQrAdapter([]),
        client_factory=lambda cookie: FakeClient(cookie),
        qr_renderer=lambda _url: b'png',
        sleep=lambda _seconds: None,
        monotonic=lambda: next(moments),
        poll_interval=0,
        timeout=30,
    )

    result = service.login(threading.Event(), lambda _png: None, lambda _status: None)

    assert result['status'] == 'expired'
    assert store.load_cookie() == ''
