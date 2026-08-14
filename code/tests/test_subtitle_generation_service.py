import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.translation_config import TranslationConfig
from app.core.app_logging import log_context
from app.services.translation.subtitle_generation_service import SubtitleGenerationService


class SubtitleGenerationServiceTest(unittest.TestCase):
    def setUp(self):
        self._probe_patcher = patch(
            'app.services.translation.subtitle_generation_service.probe_subtitle_stream_count',
            return_value=0,
        )
        self._probe_patcher.start()
        self.addCleanup(self._probe_patcher.stop)

    def test_skips_videos_with_complete_subtitles_and_processes_only_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            completed_video = input_dir / 'RCTD-688.mp4'
            candidate_video = input_dir / 'RCTD-689.mp4'
            completed_video.write_bytes(b'video')
            candidate_video.write_bytes(b'video')
            (input_dir / 'RCTD-688.srt').write_text('已有字幕', encoding='utf-8')
            record_file = Path(temp_dir) / 'subtitle_generation_records.json'
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                candidate_video.with_suffix('.srt').write_text('新字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process) as run_process_mock:
                result = SubtitleGenerationService(config, record_file=record_file).generate_from_directory()

            run_process_mock.assert_called_once()
            self.assertEqual(result['video_count'], 1)
            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['results'][0]['video_path'], str(input_dir / 'RCTD-689' / candidate_video.name))

    def test_prepare_candidates_writes_pending_task_without_starting_infer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            embedded_video = input_dir / 'RCTD-688.mp4'
            pending_video = input_dir / 'RCTD-689.mp4'
            embedded_video.write_bytes(b'video')
            pending_video.write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            with patch(
                'app.services.translation.subtitle_generation_service.probe_subtitle_stream_count',
                side_effect=lambda path: 1 if Path(path).name == embedded_video.name else 0,
            ), patch('app.services.translation.subtitle_generation_service.subprocess.run') as run_process:
                result = SubtitleGenerationService(
                    config,
                    record_file=Path(temp_dir) / 'records.json',
                    task_dir=Path(temp_dir) / 'tasks',
                ).prepare_candidates()

            run_process.assert_not_called()
            self.assertEqual(result['candidate_count'], 1)
            self.assertEqual(result['candidates'][0]['video_code'], 'RCTD-689')
            task_file = Path(result['task_file'])
            payload = json.loads(task_file.read_text(encoding='utf-8'))
            self.assertEqual(payload['status'], 'pending_confirmation')
            self.assertEqual(payload['candidates'][0]['status'], 'pending')

    def test_prepare_candidates_persists_current_global_task_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            (input_dir / 'RCTD-688.mp4').write_bytes(b'video')
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            with log_context(task_id='task-subtitle-001'):
                result = SubtitleGenerationService(
                    config,
                    record_file=Path(temp_dir) / 'records.json',
                    task_dir=Path(temp_dir) / 'tasks',
                ).prepare_candidates()

            payload = json.loads(Path(result['task_file']).read_text(encoding='utf-8'))
            self.assertEqual(result['task_id'], 'task-subtitle-001')
            self.assertEqual(payload['task_id'], 'task-subtitle-001')

    def test_prepare_candidates_includes_complete_external_subtitles_for_soft_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            for suffix in ('srt', 'vtt', 'lrc'):
                video.with_suffix(f'.{suffix}').write_text('字幕', encoding='utf-8')
            config = TranslationConfig(root, infer, 'cuda', ('srt', 'vtt', 'lrc'), False, input_dir=input_dir)

            with patch(
                'app.services.translation.subtitle_generation_service.probe_subtitle_stream_count',
                return_value=0,
            ):
                result = SubtitleGenerationService(
                    config,
                    record_file=Path(temp_dir) / 'records.json',
                    task_dir=Path(temp_dir) / 'tasks',
                ).prepare_candidates()

            self.assertEqual(result['candidate_count'], 1)
            self.assertTrue(result['candidates'][0]['has_external_subtitle'])
            self.assertIn('软字幕封装', result['candidates'][0]['reason'])

    def test_skips_video_when_ffprobe_finds_embedded_subtitle_stream(self):
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
                'app.services.translation.subtitle_generation_service.probe_subtitle_stream_count',
                return_value=1,
            ), patch('app.services.translation.subtitle_generation_service.subprocess.run') as run_process:
                result = SubtitleGenerationService(
                    config,
                    record_file=Path(temp_dir) / 'records.json',
                ).generate_from_directory()

            run_process.assert_not_called()
            self.assertEqual(result['video_count'], 0)
            self.assertEqual(result['discovered_video_count'], 1)
            self.assertEqual(result['skipped_count'], 1)

    def test_records_each_completed_video_but_not_failed_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            completed_video = input_dir / 'RCTD-688.mp4'
            failed_video = input_dir / 'RCTD-689.mp4'
            completed_video.write_bytes(b'video')
            failed_video.write_bytes(b'video')
            record_file = Path(temp_dir) / 'subtitle_generation_records.json'
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                if command[-1].endswith('RCTD-688.mp4'):
                    completed_video.with_suffix('.srt').write_text('字幕', encoding='utf-8')
                    return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')
                return subprocess.CompletedProcess(command, 2, stdout='', stderr='failed')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process):
                result = SubtitleGenerationService(config, record_file=record_file).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            payload = json.loads(record_file.read_text(encoding='utf-8'))
            records = payload['directories'][str(input_dir.resolve())]['videos']
            self.assertIn('RCTD-688', records)
            self.assertNotIn('RCTD-689', records)

    def test_reruns_video_when_record_exists_but_subtitle_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            video = input_dir / 'RCTD-688.mp4'
            video.write_bytes(b'video')
            record_file = Path(temp_dir) / 'subtitle_generation_records.json'
            record_file.write_text(
                json.dumps({'version': 1, 'directories': {str(input_dir.resolve()): {'videos': {'RCTD-688': {'status': 'completed'}}}}}),
                encoding='utf-8',
            )
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                video.with_suffix('.srt').write_text('补生成字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process) as run_process_mock:
                result = SubtitleGenerationService(config, record_file=record_file).generate_from_directory()

            run_process_mock.assert_called_once()
            self.assertEqual(result['success_count'], 1)

    def test_uses_recorded_video_code_as_completed_candidate_only_when_actual_subtitle_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'model'
            root.mkdir()
            infer = root / 'infer.exe'
            infer.write_bytes(b'placeholder')
            input_dir = Path(temp_dir) / 'translation_videos'
            input_dir.mkdir()
            recorded_video = input_dir / 'RCTD-688.mp4'
            new_video = input_dir / 'RCTD-689.mp4'
            recorded_video.write_bytes(b'video')
            new_video.write_bytes(b'video')
            recorded_video.with_suffix('.srt').write_text('已有字幕', encoding='utf-8')
            record_file = Path(temp_dir) / 'records.json'
            record_file.write_text(
                json.dumps({
                    'version': 1,
                    'directories': {
                        str(input_dir.resolve()): {
                            'videos': {'RCTD-688': {'status': 'completed'}},
                        },
                    },
                }),
                encoding='utf-8',
            )
            config = TranslationConfig(root, infer, 'cuda', ('srt',), False, input_dir=input_dir)

            def run_process(command, **kwargs):
                new_video.with_suffix('.srt').write_text('新字幕', encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch('app.services.translation.subtitle_generation_service.subprocess.run', side_effect=run_process) as run_process_mock:
                result = SubtitleGenerationService(config, record_file=record_file).generate_from_directory()

            run_process_mock.assert_called_once()
            self.assertEqual(run_process_mock.call_args.args[0][-1], str(new_video))
            self.assertEqual(result['recorded_count'], 1)
            self.assertEqual(result['success_count'], 1)

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

            run_process.assert_not_called()
            self.assertEqual(result['video_count'], 0)
            self.assertEqual(result['discovered_video_count'], 1)
            self.assertEqual(result['skipped_count'], 1)
            self.assertEqual(result['success_count'], 0)

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

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
                result = SubtitleGenerationService(config, record_file=Path(temp_dir) / 'records.json').generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            log_messages = [str(call) for call in logger.method_calls]
            self.assertTrue(any('模型进程结束' in message and 'stderr detail' in message for message in log_messages))


if __name__ == '__main__':
    unittest.main()
