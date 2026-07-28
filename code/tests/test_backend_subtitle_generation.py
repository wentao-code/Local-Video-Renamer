import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.backend.client import BackendClient
from app.backend.server import make_handler
from app.backend.service import BackendService


class BackendSubtitleGenerationTest(unittest.TestCase):
    def test_server_routes_subtitle_generation_paths(self):
        service = Mock()
        service.generate_subtitles.return_value = {'success_count': 1, 'failed_count': 0, 'results': []}
        handler = make_handler(service)

        result = handler._route(
            object(),
            'POST',
            SimpleNamespace(path='/translation/subtitles', query=''),
            {'video_paths': ['D:/videos/RCTD-688.mp4']},
        )

        self.assertEqual(result['success_count'], 1)
        service.generate_subtitles.assert_called_once_with(['D:/videos/RCTD-688.mp4'])

    def test_backend_service_delegates_to_subtitle_generator(self):
        service = BackendService.__new__(BackendService)
        service.subtitle_generation_service = Mock()
        service.subtitle_generation_service.generate.return_value = {'success_count': 1}

        result = service.generate_subtitles(['D:/videos/RCTD-688.mp4'])

        self.assertEqual(result, {'success_count': 1})
        service.subtitle_generation_service.generate.assert_called_once_with(
            ['D:/videos/RCTD-688.mp4']
        )

    def test_client_uses_long_timeout_for_subtitle_generation(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        with patch.object(client, '_post', return_value={'success_count': 1}) as post:
            result = client.generate_subtitles(['D:/videos/RCTD-688.mp4'])

        self.assertEqual(result, {'success_count': 1})
        post.assert_called_once_with(
            '/translation/subtitles',
            {'video_paths': ['D:/videos/RCTD-688.mp4']},
            timeout=20 * 60,
        )


if __name__ == '__main__':
    unittest.main()
