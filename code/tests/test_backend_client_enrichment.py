import unittest

from app.backend.client import BackendClient


class BackendClientEnrichmentTest(unittest.TestCase):
    def test_batch_plan_creation_uses_long_running_request_timeout(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=60)
        calls = []
        client._post = lambda path, payload=None, timeout=None: calls.append((path, payload, timeout)) or {}

        client.create_enrichment_batch_plan({
            'target_type': 'video_library',
            'source_key': 'supplement',
            'batch_limit': 25,
            'batch_count_limit': 300,
        })

        self.assertEqual(calls[0][0], '/database/enrich/batch-plan')
        self.assertEqual(calls[0][2], 10 * 60)


if __name__ == '__main__':
    unittest.main()
