import socket
from urllib.parse import urlparse

from app.core.runtime_config import get_avfan_base_url, get_javtxt_base_url


DEFAULT_NETWORK_GUARD_TIMEOUT_SECONDS = 0.8
DEFAULT_NETWORK_GUARD_REQUIRED_FAILURES = 15
_DEFAULT_FALLBACK_TARGETS = (
    {'label': 'Cloudflare DNS', 'host': '1.1.1.1', 'port': 53},
    {'label': 'AliDNS', 'host': '223.5.5.5', 'port': 53},
)


class NetworkGuardService:
    def __init__(self, targets=None, timeout_seconds=None, required_failures=None):
        self.targets = list(targets) if targets is not None else self._build_default_targets()
        self.timeout_seconds = float(timeout_seconds or DEFAULT_NETWORK_GUARD_TIMEOUT_SECONDS)
        self.required_failures = max(1, int(required_failures or DEFAULT_NETWORK_GUARD_REQUIRED_FAILURES))

    def probe(self):
        failed_targets = []
        for target in self.targets:
            if self._can_connect(target):
                return {
                    'is_online': True,
                    'reachable_target': str((target or {}).get('label', '') or ''),
                    'failed_targets': failed_targets,
                }
            failed_targets.append(str((target or {}).get('label', '') or '').strip())
        return {
            'is_online': False,
            'reachable_target': '',
            'failed_targets': [label for label in failed_targets if label],
        }

    def _can_connect(self, target):
        host = str((target or {}).get('host', '') or '').strip()
        port = int((target or {}).get('port', 0) or 0)
        if not host or port <= 0:
            return False
        try:
            connection = socket.create_connection((host, port), timeout=self.timeout_seconds)
        except OSError:
            return False
        try:
            return True
        finally:
            try:
                connection.close()
            except Exception:
                pass

    @classmethod
    def _build_default_targets(cls):
        targets = []
        seen = set()
        for label, url in (
            ('AVFan', cls._safe_runtime_url(get_avfan_base_url)),
            ('JAVTXT', cls._safe_runtime_url(get_javtxt_base_url)),
        ):
            target = cls._target_from_url(label, url)
            if not target:
                continue
            key = (target['host'], target['port'])
            if key in seen:
                continue
            seen.add(key)
            targets.append(target)

        for target in _DEFAULT_FALLBACK_TARGETS:
            key = (target['host'], target['port'])
            if key in seen:
                continue
            seen.add(key)
            targets.append(dict(target))
        return targets

    @staticmethod
    def _safe_runtime_url(getter):
        try:
            return str(getter() or '').strip()
        except Exception:
            return ''

    @staticmethod
    def _target_from_url(label, url):
        parsed = urlparse(str(url or '').strip())
        host = str(parsed.hostname or '').strip()
        if not host:
            return {}
        if parsed.port:
            port = int(parsed.port)
        elif parsed.scheme.lower() == 'http':
            port = 80
        else:
            port = 443
        return {
            'label': str(label or '').strip() or host,
            'host': host,
            'port': port,
        }
