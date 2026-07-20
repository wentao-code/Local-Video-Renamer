import time
import unittest

from app.backend.service import BackendService


class EnrichmentSelectionJobTest(unittest.TestCase):
    def test_selection_request_is_idempotent_and_appends_pages_in_background(self):
        class FakeDatabase:
            def __init__(self):
                self.create_calls = []
                self.append_calls = []

            def create_enrichment_batch_plan(self, *args, **kwargs):
                self.create_calls.append((args, kwargs))
                return {
                    'plan_id': 'plan-1',
                    'task_kind': 'actor',
                    'target_type': 'actor_library',
                    'source_key': 'avfan',
                    'item_count': len(kwargs.get('candidates', [])),
                }

            def append_enrichment_batch_plan_candidates(self, plan_id, task_kind, candidates):
                self.append_calls.append((plan_id, task_kind, list(candidates)))
                return len(candidates)

        service = BackendService.__new__(BackendService)
        service.db = FakeDatabase()
        service._enrichment_selection_jobs = {}
        service._enrichment_selection_jobs_lock = __import__('threading').Lock()
        pages = [
            [{'actor_name': f'演员-{index}'} for index in range(100)],
            [{'actor_name': f'演员-{index}'} for index in range(100, 200)],
            [],
        ]
        service._selection_page_candidates = lambda *_args: pages.pop(0)
        service._exclude_enrichment_queue_candidates = lambda _task, _source, rows: rows

        first = service.select_enrichment_candidates({
            'selection_job_id': 'select-test-1',
            'task_kind': 'actor',
            'target_type': 'actor_library',
            'source_key': 'avfan',
            'all_candidates': True,
            'selection_page_size': 100,
        })
        second = service.select_enrichment_candidates({
            'selection_job_id': 'select-test-1',
            'task_kind': 'actor',
            'target_type': 'actor_library',
            'source_key': 'avfan',
            'all_candidates': True,
            'selection_page_size': 100,
        })

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = service.get_enrichment_selection_job('select-test-1')['job']
            if state['status'] in {'completed', 'failed'}:
                break
            time.sleep(0.01)

        state = service.get_enrichment_selection_job('select-test-1')['job']
        self.assertEqual(first['job']['job_id'], 'select-test-1')
        self.assertEqual(second['job']['job_id'], 'select-test-1')
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['candidate_count'], 200)
        self.assertEqual(state['plan']['item_count'], 200)
        self.assertEqual(len(service.db.create_calls), 1)
        self.assertEqual(len(service.db.append_calls), 1)
        self.assertEqual(len(service.db.append_calls[0][2]), 100)


if __name__ == '__main__':
    unittest.main()
