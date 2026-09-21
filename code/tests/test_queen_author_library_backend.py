import unittest
import threading
from unittest.mock import Mock

from app.backend.client import BackendClient
from app.backend.service import BackendService


class _QueenAuthorServiceStub:
    def list_queen_authors(self):
        return [{'author_name': '\u9ed1\u55b5'}]

    def get_queen_author_detail(self, author_name):
        return {'author_name': author_name, 'videos': []}

    def add_queen_author(self, author_name, queen_name):
        return {
            'author_name': author_name,
            'source_queens': [queen_name],
            'match_job': {'job_id': 11, 'status': 'pending'},
        }

    def remove_queen_author(self, author_name):
        return {'author_name': author_name, 'deleted_count': 1}


class QueenAuthorBackendServiceTest(unittest.TestCase):
    def _service(self):
        service = BackendService.__new__(BackendService)
        service.queen_library_service = _QueenAuthorServiceStub()
        service._current_snapshot_timestamp = lambda: 'now'
        service._read_page_snapshot = Mock(return_value=None)
        service._write_page_snapshot = Mock()
        service._delete_page_snapshot_prefix = Mock()
        service._queen_author_match_threads = {}
        service._queen_author_match_lock = threading.Lock()
        return service

    def test_author_list_and_detail_use_independent_snapshots(self):
        service = self._service()

        self.assertEqual(
            BackendService.list_queen_author_library_snapshot(service),
            {'authors': [{'author_name': '\u9ed1\u55b5'}], 'refreshed_at': 'now'},
        )
        self.assertEqual(
            BackendService.get_queen_author_detail_snapshot(service, '\u9ed1\u55b5'),
            {'author_name': '\u9ed1\u55b5', 'videos': [], 'refreshed_at': 'now'},
        )
        self.assertEqual(service._write_page_snapshot.call_count, 2)

    def test_author_mutations_delegate_and_invalidate_queen_snapshots(self):
        service = self._service()
        service._start_queen_author_match_job = Mock()

        self.assertEqual(
            BackendService.add_queen_author(service, '\u9ed1\u55b5', '\u9ed1\u55b5')['author_name'],
            '\u9ed1\u55b5',
        )
        self.assertEqual(
            BackendService.remove_queen_author(service, '\u9ed1\u55b5')['deleted_count'],
            1,
        )
        service._start_queen_author_match_job.assert_called_once_with(11)
        self.assertEqual(service._delete_page_snapshot_prefix.call_count, 2)

    def test_author_worker_processes_until_completed(self):
        service = self._service()
        service.queen_library_service.process_queen_author_match_job = Mock(
            side_effect=[
                {'job_id': 11, 'status': 'running'},
                {'job_id': 11, 'status': 'completed'},
            ]
        )

        BackendService._run_queen_author_match_job(service, 11)

        self.assertEqual(
            service.queen_library_service.process_queen_author_match_job.call_count,
            2,
        )


class QueenAuthorBackendClientTest(unittest.TestCase):
    def test_author_methods_use_queen_library_routes(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        get_calls = []
        post_calls = []
        client._get = lambda path, timeout=None: get_calls.append((path, timeout)) or {'authors': []}
        client._post = lambda path, body=None, timeout=None: post_calls.append((path, body, timeout)) or {'deleted_count': 1}

        client.list_queen_author_library_snapshot(force_refresh=True)
        client.get_queen_author_detail_snapshot('\u9ed1\u55b5', force_refresh=True)
        client.add_queen_author('\u9ed1\u55b5', '\u9ed1\u55b5')
        client.remove_queen_author('\u9ed1\u55b5')

        self.assertIn('/queen-library/authors?refresh=1', [path for path, _timeout in get_calls])
        self.assertTrue(any(path.startswith('/queen-library/author/detail?') for path, _timeout in get_calls))
        self.assertEqual(post_calls[0][0], '/queen-library/authors/add')
        self.assertEqual(post_calls[1][0], '/queen-library/authors/remove')


if __name__ == '__main__':
    unittest.main()
