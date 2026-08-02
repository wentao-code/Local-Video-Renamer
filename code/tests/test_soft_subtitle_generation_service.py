import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.translation.soft_subtitle_generation_service import SoftSubtitleGenerationService


class SoftSubtitleGenerationServiceTest(unittest.TestCase):
    def test_muxes_numbered_vtt_with_titled_video_in_number_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text('WEBVTT\n', encoding='utf-8')

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ) as run_process:
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            output = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.softsub.mp4'
            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertTrue(output.is_file())
            self.assertTrue(video.is_file())
            self.assertTrue(subtitle.is_file())
            command = run_process.call_args.args[0]
            self.assertIn(str(video), command)
            self.assertIn(str(subtitle), command)
            self.assertIn('mov_text', command)


if __name__ == '__main__':
    unittest.main()
