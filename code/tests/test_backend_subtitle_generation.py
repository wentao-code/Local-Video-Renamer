import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.backend.client import BackendClient
from app.backend.server import make_handler
from app.backend.service import BackendService


class BackendSubtitleGenerationTest(unittest.TestCase):
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

if __name__ == '__main__':
    unittest.main()
