import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.translation_config import TranslationConfig
from app.services.local_video.subtitle_generation_service import SubtitleGenerationService


class SubtitleGenerationServiceTest(unittest.TestCase):
    def test_generates_expected_subtitles_from_video_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            video = Path(temp_dir) / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(
                model_root=root,
                infer_exe=infer,
                device='cuda',
                sub_formats=('srt', 'vtt', 'lrc'),
                overwrite=False,
            )

            def run_process(command, **kwargs):
                self.assertEqual(kwargs['cwd'], str(root))
                self.assertEqual(command[0], str(infer))
                self.assertIn('--audio_suffixes=mp4,mkv,avi,mov,webm,flv,wmv', command)
                self.assertIn('--sub_formats=srt,vtt,lrc', command)
                self.assertIn('--device=cuda', command)
                self.assertEqual(command[-1], str(video))
                for suffix in config.sub_formats:
                    video.with_suffix(f'.{suffix}').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.local_video.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate([video])

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertEqual(result['results'][0]['status'], 'completed')
            self.assertEqual(
                result['results'][0]['subtitle_paths'],
                [str(video.with_suffix('.srt')), str(video.with_suffix('.vtt')), str(video.with_suffix('.lrc'))],
            )

    def test_reports_nonzero_infer_exit_as_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            video = Path(temp_dir) / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False)

            with patch(
                'app.services.local_video.subtitle_generation_service.subprocess.run',
                return_value=subprocess.CompletedProcess([], 2, stdout='', stderr='model failed'),
            ):
                result = SubtitleGenerationService(config).generate([video])

            self.assertEqual(result['success_count'], 0)
            self.assertEqual(result['failed_count'], 1)
            self.assertEqual(result['results'][0]['status'], 'failed')
            self.assertIn('model failed', result['results'][0]['error'])


if __name__ == '__main__':
    unittest.main()
