import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.translation_config import TranslationConfig
from app.services.translation.subtitle_generation_service import SubtitleGenerationService


class SubtitleGenerationServiceTest(unittest.TestCase):
    def test_processes_each_video_serially_with_a_file_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            videos = [input_dir / 'RCTD-688.mp4', input_dir / 'RCTD-689.mp4']
            for video in videos:
                video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)
            commands = []

            def run_process(command, **kwargs):
                commands.append(command)
                Path(command[-1]).with_suffix('.srt').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 2)
            self.assertEqual(result['failed_count'], 0)
            self.assertEqual([command[-1] for command in commands], [str(video) for video in videos])

    def test_video_timeout_is_recorded_and_next_video_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            videos = [input_dir / 'RCTD-688.mp4', input_dir / 'RCTD-689.mp4']
            for video in videos:
                video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)
            calls = []

            def run_process(command, **kwargs):
                calls.append(command)
                if len(calls) == 1:
                    raise subprocess.TimeoutExpired(command, 120)
                Path(command[-1]).with_suffix('.srt').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 1)
            self.assertEqual(result['results'][0]['status'], 'failed')
            self.assertIn('超时', result['results'][0]['error'])
            self.assertEqual(result['results'][1]['status'], 'completed')
            self.assertEqual(len(calls), 2)

    def test_generates_expected_subtitles_from_fixed_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            (input_dir / 'ignore.txt').write_text('ignore', encoding='utf-8')
            config = TranslationConfig(
                model_root=root,
                infer_exe=infer,
                device='cuda',
                sub_formats=('srt', 'vtt', 'lrc'),
                overwrite=False,
                input_dir=input_dir,
            )

            def run_process(command, **kwargs):
                self.assertEqual(kwargs['cwd'], str(root))
                self.assertEqual(kwargs['env']['PYTHONIOENCODING'], 'utf-8')
                self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
                self.assertEqual(kwargs['creationflags'], getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10))
                self.assertEqual(kwargs['timeout'], config.video_timeout_seconds)
                self.assertNotIn('capture_output', kwargs)
                self.assertEqual(command[0], str(infer))
                self.assertIn('--audio_suffixes=mp4,mkv,avi,mov,webm,flv,wmv', command)
                self.assertIn('--sub_formats=srt,vtt,lrc', command)
                self.assertIn('--device=cuda', command)
                self.assertEqual(command[-1], str(video))
                for suffix in config.sub_formats:
                    video.with_suffix(f'.{suffix}').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertEqual(result['results'][0]['status'], 'completed')
            organized_dir = input_dir / 'RCTD-688'
            self.assertEqual(
                result['results'][0]['video_path'],
                str(organized_dir / video.name),
            )
            self.assertEqual(
                result['results'][0]['subtitle_paths'],
                [str(organized_dir / f'RCTD-688.{suffix}') for suffix in config.sub_formats],
            )
            self.assertTrue((organized_dir / video.name).is_file())
            self.assertFalse(video.exists())
            self.assertTrue(all((organized_dir / f'RCTD-688.{suffix}').is_file() for suffix in config.sub_formats))

    def test_reports_existing_number_folder_as_already_organized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            organized_dir = input_dir / 'RCTD-688'
            organized_dir.mkdir(parents=True)
            video = organized_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            subtitle = organized_dir / 'RCTD-688.srt'
            subtitle.write_text('字幕', encoding='utf-8')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            with patch(
                'app.services.translation.subtitle_generation_service.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, stdout='ok', stderr=''),
            ) as run_process:
                result = SubtitleGenerationService(config).generate_from_directory()

            run_process.assert_called_once()
            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['results'][0]['video_path'], str(video))

    def test_uses_full_video_code_instead_of_code_prefix_for_folder_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-116 sample title.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                (input_dir / 'RCTD-116.mp4').with_suffix('.srt').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['results'][0]['video_path'], str(input_dir / 'RCTD-116' / video.name))
            self.assertEqual(result['results'][0]['subtitle_paths'], [str(input_dir / 'RCTD-116' / 'RCTD-116.srt')])
            self.assertFalse((input_dir / 'RCTD-116.mp4').exists())
            self.assertTrue((input_dir / 'RCTD-116' / video.name).exists())

    def test_reports_nonzero_infer_exit_as_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            with patch(
                'app.services.translation.subtitle_generation_service.subprocess.run',
                return_value=subprocess.CompletedProcess([], 2, stdout='', stderr='model failed'),
            ):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 0)
            self.assertEqual(result['failed_count'], 1)
            self.assertEqual(result['results'][0]['status'], 'failed')
            self.assertIn('model failed', result['results'][0]['error'])

    def test_accepts_nonzero_infer_exit_when_all_subtitles_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt', 'vtt', 'lrc'), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                for suffix in config.sub_formats:
                    video.with_suffix(f'.{suffix}').write_text('字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 3221226505, stdout='completed', stderr='native shutdown error')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertEqual(result['results'][0]['status'], 'completed')
            self.assertIn('3221226505', result['results'][0].get('warning', ''))

    def test_logs_model_exit_details_for_diagnosis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)
            logger = Mock()

            with patch(
                'app.services.translation.subtitle_generation_service.subprocess.run',
                return_value=subprocess.CompletedProcess([], 2, stdout='stdout detail', stderr='stderr detail'),
            ), patch('app.services.translation.subtitle_generation_service.LOGGER', logger):
                result = SubtitleGenerationService(config).generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            log_messages = [str(call) for call in logger.method_calls]
            self.assertTrue(any('模型进程结束' in message and 'stderr detail' in message for message in log_messages))


if __name__ == '__main__':
    unittest.main()
