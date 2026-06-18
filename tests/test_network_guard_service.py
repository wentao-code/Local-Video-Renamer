import unittest
from unittest.mock import patch

from app.services.system import NetworkGuardService


class _FakeConnection:
    def close(self):
        return None


class NetworkGuardServiceTest(unittest.TestCase):
    def test_default_required_failures_is_fifteen(self):
        service = NetworkGuardService(targets=[], required_failures=None)

        self.assertEqual(service.required_failures, 15)

    def test_probe_returns_online_when_any_target_is_reachable(self):
        targets = [
            {'label': 'A', 'host': '10.0.0.1', 'port': 443},
            {'label': 'B', 'host': '10.0.0.2', 'port': 443},
        ]
        service = NetworkGuardService(targets=targets, timeout_seconds=0.1, required_failures=2)

        def fake_create_connection(address, timeout=0):
            if address == ('10.0.0.2', 443):
                return _FakeConnection()
            raise OSError('offline')

        with patch('app.services.system.network_guard_service.socket.create_connection', side_effect=fake_create_connection):
            result = service.probe()

        self.assertTrue(result['is_online'])
        self.assertEqual(result['reachable_target'], 'B')
        self.assertEqual(result['failed_targets'], ['A'])

    def test_probe_returns_offline_when_all_targets_fail(self):
        targets = [
            {'label': 'A', 'host': '10.0.0.1', 'port': 443},
            {'label': 'B', 'host': '10.0.0.2', 'port': 443},
        ]
        service = NetworkGuardService(targets=targets, timeout_seconds=0.1, required_failures=2)

        with patch('app.services.system.network_guard_service.socket.create_connection', side_effect=OSError('offline')):
            result = service.probe()

        self.assertFalse(result['is_online'])
        self.assertEqual(result['failed_targets'], ['A', 'B'])

    def test_target_from_url_uses_default_https_port(self):
        target = NetworkGuardService._target_from_url('AVFan', 'https://example.com/search?q=1')

        self.assertEqual(
            target,
            {'label': 'AVFan', 'host': 'example.com', 'port': 443},
        )


if __name__ == '__main__':
    unittest.main()
