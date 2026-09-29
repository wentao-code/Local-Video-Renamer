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

    def test_standard_reference_client_routes_page_count_progress_and_author(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=60)
        gets = []
        posts = []
        client._get = lambda path, timeout=None: gets.append((path, timeout)) or {'progress': {'is_running': False}}
        client._post = lambda path, payload=None, timeout=None: posts.append((path, payload, timeout)) or {}

        client.list_standard_reference_authors()
        client.get_standard_reference_author_detail('博主 A')
        client.start_standard_reference_crawl(5)
        client.get_standard_reference_crawl_progress()
        client.cancel_standard_reference_crawl()

        self.assertEqual(gets[0][0], '/standard-reference/authors')
        self.assertIn('name=%E5%8D%9A%E4%B8%BB+A', gets[1][0])
        self.assertEqual(gets[2][0], '/standard-reference/crawl/progress')
        self.assertEqual(posts[0][0], '/standard-reference/crawl')
        self.assertEqual(posts[0][1], {'page_count': 5})
        self.assertEqual(posts[1][0], '/standard-reference/crawl/cancel')


if __name__ == '__main__':
    unittest.main()
