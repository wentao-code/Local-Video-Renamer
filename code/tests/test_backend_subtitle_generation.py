import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.backend.client import BackendClient
from app.backend.server import make_handler
from app.backend.service import BackendService
from app.core.app_logging import log_context


class BackendSubtitleGenerationTest(unittest.TestCase):
    def test_server_routes_subtitle_candidate_preparation(self):
        service = Mock()
        service.prepare_subtitle_candidates.return_value = {'candidate_count': 1, 'candidates': []}
        handler = make_handler(service)
        result = handler._route(
            object(),
            'POST',
            SimpleNamespace(path='/translation/subtitles/candidates', query=''),
            {},
        )

        self.assertEqual(result['candidate_count'], 1)
        service.prepare_subtitle_candidates.assert_called_once_with()

    def test_backend_service_delegates_to_candidate_preparation(self):
        service = BackendService.__new__(BackendService)
        service.subtitle_generation_service = Mock()
        service.subtitle_generation_service.prepare_candidates.return_value = {'candidate_count': 2}

        self.assertEqual(service.prepare_subtitle_candidates(), {'candidate_count': 2})
        service.subtitle_generation_service.prepare_candidates.assert_called_once_with()

    def test_server_confirms_subtitle_candidate_selection(self):
        service = Mock()
        service.confirm_subtitle_candidates.return_value = {'status': 'running'}
        handler = make_handler(service)

        result = handler._route(
            object(),
            'POST',
            SimpleNamespace(path='/translation/subtitles/candidates/confirm', query=''),
            {'candidate_run_id': 'subtitle-candidates-1', 'candidate_codes': ['RCTD-688']},
        )

        self.assertEqual(result, {'status': 'running'})
        service.confirm_subtitle_candidates.assert_called_once_with(
            'subtitle-candidates-1',
            ['RCTD-688'],
        )

    def test_client_confirms_subtitle_candidate_selection(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'status': 'running'}) as post:
            result = client.confirm_subtitle_candidates('subtitle-candidates-1', ['RCTD-688'])

        self.assertEqual(result, {'status': 'running'})
        post.assert_called_once_with(
            '/translation/subtitles/candidates/confirm',
            {'candidate_run_id': 'subtitle-candidates-1', 'candidate_codes': ['RCTD-688']},
        )

    def test_server_routes_subtitle_generation_directory(self):
        service = Mock()
        service.generate_subtitles.return_value = {'success_count': 1, 'failed_count': 0, 'results': []}
        handler = make_handler(service)

        result = handler._route(
            object(),
            'POST',
            SimpleNamespace(path='/translation/subtitles', query=''),
            {},
        )

        self.assertEqual(result['success_count'], 1)
        service.generate_subtitles.assert_called_once_with()

    def test_backend_service_delegates_to_subtitle_generator(self):
        service = BackendService.__new__(BackendService)
        service.subtitle_generation_service = Mock()
        service.subtitle_generation_service.generate_from_directory.return_value = {'success_count': 1}

        result = service.generate_subtitles()

        self.assertEqual(result, {'success_count': 1})
        service.subtitle_generation_service.generate_from_directory.assert_called_once_with()

    def test_client_uses_long_timeout_for_subtitle_generation(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            result = client.generate_subtitles()

        self.assertEqual(result, {'success_count': 1})
        post.assert_called_once_with(
            '/translation/subtitles',
            {},
            timeout=20 * 60,
        )


    def test_server_routes_soft_subtitle_generation(self):
        service = Mock()
        service.generate_soft_subtitles.return_value = {'success_count': 1}
        handler = make_handler(service)
        result = handler._route(object(), 'POST', SimpleNamespace(path='/translation/soft-subtitles', query=''), {})
        self.assertEqual(result['success_count'], 1)
        service.generate_soft_subtitles.assert_called_once_with()

    def test_backend_service_delegates_to_soft_subtitle_generator(self):
        service = BackendService.__new__(BackendService)
        service.soft_subtitle_generation_service = Mock()
        service.soft_subtitle_generation_service.generate_from_directory.return_value = {'success_count': 1}
        self.assertEqual(service.generate_soft_subtitles(), {'success_count': 1})

    def test_client_uses_long_timeout_for_soft_subtitle_generation(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            self.assertEqual(client.generate_soft_subtitles(), {'success_count': 1})
        post.assert_called_once_with('/translation/soft-subtitles', {}, timeout=20 * 60)

    def test_server_routes_subtitle_pipeline(self):
        service = Mock()
        service.generate_subtitles_pipeline.return_value = {'success_count': 1, 'failed_count': 0}
        handler = make_handler(service)
        result = handler._route(
            object(),
            'POST',
            SimpleNamespace(path='/translation/subtitles/pipeline', query=''),
            {},
        )
        self.assertEqual(result['success_count'], 1)
        service.generate_subtitles_pipeline.assert_called_once_with()

    def test_backend_service_delegates_to_subtitle_pipeline(self):
        service = BackendService.__new__(BackendService)
        service.subtitle_pipeline_service = Mock()
        service.subtitle_pipeline_service.run.return_value = {'success_count': 1}

        result = service.generate_subtitles_pipeline()

        self.assertEqual(result, {'success_count': 1})
        service.subtitle_pipeline_service.run.assert_called_once_with()

    def test_backend_service_passes_candidate_task_management_to_subtitle_pipeline(self):
        service = BackendService.__new__(BackendService)
        service.subtitle_pipeline_service = Mock()
        service.subtitle_pipeline_service.run.return_value = {'success_count': 1}

        service.generate_subtitles_pipeline(
            candidate_codes=['RCTD-688'],
            candidate_run_id='subtitle-candidates-1',
            manage_candidate_task=False,
        )

        service.subtitle_pipeline_service.run.assert_called_once_with(
            candidate_codes=['RCTD-688'],
            candidate_run_id='subtitle-candidates-1',
            manage_candidate_task=False,
        )

    def test_client_uses_extended_timeout_for_subtitle_pipeline(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            result = client.generate_subtitles_pipeline()

        self.assertEqual(result, {'success_count': 1})
        post.assert_called_once_with(
            '/translation/subtitles/pipeline',
            {},
            timeout=7 * 24 * 3600,
        )

    def test_client_sends_confirmed_subtitle_candidate_codes(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            result = client.generate_subtitles_pipeline(['RCTD-688'], 'subtitle_candidates-1')

        self.assertEqual(result, {'success_count': 1})
        post.assert_called_once_with(
            '/translation/subtitles/pipeline',
            {
                'candidate_codes': ['RCTD-688'],
                'candidate_run_id': 'subtitle_candidates-1',
            },
            timeout=7 * 24 * 3600,
        )

    def test_client_can_disable_batch_candidate_task_management_for_one_video(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            client.generate_subtitles_pipeline(
                ['RCTD-688'],
                'subtitle_candidates-1',
                manage_candidate_task=False,
            )

        post.assert_called_once_with(
            '/translation/subtitles/pipeline',
            {
                'candidate_codes': ['RCTD-688'],
                'candidate_run_id': 'subtitle_candidates-1',
                'manage_candidate_task': False,
            },
            timeout=7 * 24 * 3600,
        )

    def test_client_adds_current_task_id_to_http_request_headers(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        response = Mock(status_code=200)
        response.json.return_value = {'ok': True}
        with log_context(task_id='task-client-001'), patch('app.backend.client.requests.post', return_value=response) as post:
            self.assertEqual(client.prepare_subtitle_candidates(), {'ok': True})

        self.assertEqual(post.call_args.kwargs['headers'], {'X-Task-ID': 'task-client-001'})

    def test_server_routes_enrichment_plan_run_history_lookup(self):
        service = Mock()
        service.list_enrichment_plan_run_history.return_value = {'history': [{'task_id': 'task-001'}]}
        handler = make_handler(service)

        result = handler._route(
            object(),
            'GET',
            SimpleNamespace(path='/database/enrich/batch-plan/history', query='plan_id=plan-001&task_id=task-001'),
            {},
        )

        self.assertEqual(result['history'][0]['task_id'], 'task-001')
        service.list_enrichment_plan_run_history.assert_called_once_with('plan-001', 'task-001', 100)

if __name__ == '__main__':
    unittest.main()
