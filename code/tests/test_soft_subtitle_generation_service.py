import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.translation.soft_subtitle_generation_service import (
    SoftSubtitleGenerationService,
)


class SoftSubtitleGenerationServiceTest(unittest.TestCase):
    def test_candidate_codes_limit_mux_to_one_video_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            first = input_dir / 'AAA-001'
            second = input_dir / 'AAA-002'
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            service = SoftSubtitleGenerationService(input_dir)
            visited = []

            with patch.object(
                service,
                '_mux_numbered_directory',
                side_effect=lambda directory: visited.append(directory.name) or None,
            ):
                service.generate_from_directory(candidate_codes={'AAA-002'})

            self.assertEqual(visited, ['AAA-002'])

    def test_candidate_codes_find_nested_numbered_video_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            numbered = input_dir / 'BBSS' / 'BBSS-085'
            numbered.mkdir(parents=True)
            service = SoftSubtitleGenerationService(input_dir)
            visited = []

            with patch.object(
                service,
                '_mux_numbered_directory',
                side_effect=lambda directory: visited.append(directory.relative_to(input_dir).as_posix()) or None,
            ):
                service.generate_from_directory(candidate_codes={'BBSS-085'})

            self.assertEqual(visited, ['BBSS/BBSS-085'])

    def test_muxes_numbered_vtt_with_titled_video_in_number_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ) as run_process:
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            final = input_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertTrue(final.is_file())
            self.assertFalse(video_dir.exists())
            command = run_process.call_args.args[0]
            self.assertIn(str(video), command)
            self.assertIn(str(subtitle), command)
            self.assertIn('mov_text', command)

    def test_successful_mux_moves_softsub_video_to_parent_and_removes_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )
            (video_dir / 'NSPS-958.srt').write_text(
                '1\n00:00:01,000 --> 00:00:02,000\nhello\n',
                encoding='utf-8',
            )
            (video_dir / 'NSPS-958.lrc').write_text('[00:01.00]hello\n', encoding='utf-8')

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ):
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            final = input_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            self.assertEqual(result['success_count'], 1)
            self.assertTrue(final.is_file())
            self.assertEqual(final.read_bytes(), b'muxed')
            self.assertFalse(video_dir.exists())
            self.assertFalse(video.exists())
            self.assertFalse(subtitle.exists())
            self.assertFalse((video_dir / 'NSPS-958.srt').exists())
            self.assertFalse((video_dir / 'NSPS-958.lrc').exists())

    def test_mux_fails_when_parent_already_has_target_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )
            final = input_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            final.write_bytes(b'existing')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
            ) as run_process:
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            self.assertIn('目标视频文件已存在', result['results'][0]['error'])
            self.assertTrue(video.exists())
            self.assertTrue(video_dir.exists())
            run_process.assert_not_called()

    def test_mux_fails_when_source_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            real_unlink = Path.unlink

            def guarded_unlink(self, *args, **kwargs):
                if self == video:
                    raise PermissionError('locked')
                return real_unlink(self, *args, **kwargs)

            with (
                patch('pathlib.Path.unlink', guarded_unlink),
                patch(
                    'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                    side_effect=run_ffmpeg,
                ),
            ):
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            self.assertIn('原文件清理失败', result['results'][0]['error'])
            self.assertTrue(video.exists())
            self.assertFalse(any(video_dir.glob('*.softsub.mp4')))

    def test_mux_command_disables_stdin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ) as run_process:
                SoftSubtitleGenerationService(input_dir).generate_from_directory()

            command = run_process.call_args.args[0]
            self.assertIn('-nostdin', command)

    def test_mux_captures_output_instead_of_inheriting_backend_pipes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ) as run_process:
                SoftSubtitleGenerationService(input_dir).generate_from_directory()

            kwargs = run_process.call_args.kwargs
            self.assertIs(kwargs.get('capture_output'), True)
            self.assertIs(kwargs.get('stdin'), subprocess.DEVNULL)

    def test_mixed_case_webvtt_header_is_normalized_before_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WebVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )
            captured = {}

            def run_ffmpeg(command, **_kwargs):
                captured['subtitle_input'] = Path(command[6])
                captured['subtitle_text'] = Path(command[6]).read_text(encoding='utf-8')
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ):
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['success_count'], 1)
            self.assertNotEqual(captured['subtitle_input'], subtitle)
            self.assertTrue(captured['subtitle_text'].startswith('WEBVTT'))
            self.assertFalse(captured['subtitle_input'].exists())
            self.assertFalse(subtitle.exists())

    def test_empty_vtt_fails_instead_of_silently_producing_empty_track(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text('WebVTT\n\n', encoding='utf-8')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
            ) as run_process:
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            self.assertIn('没有字幕内容', result['results'][0]['error'])
            run_process.assert_not_called()

    def test_timeout_cleans_temporary_output_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'partial')
                raise subprocess.TimeoutExpired(command, timeout=1)

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ):
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['success_count'], 0)
            self.assertEqual(result['failed_count'], 1)
            self.assertIn('超时', result['results'][0]['error'])
            self.assertFalse(any(video_dir.glob('*.softsub.tmp.mp4')))
            self.assertFalse(any(video_dir.glob('*.softsub.mp4')))

    def test_stale_temporary_output_is_cleaned_before_mux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )
            stale = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.softsub.tmp.mp4'
            stale.write_bytes(b'partial')

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'muxed')
                return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

            with patch(
                'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                side_effect=run_ffmpeg,
            ) as run_process:
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            final = input_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['failed_count'], 0)
            self.assertFalse(stale.exists())
            self.assertTrue(final.is_file())
            self.assertEqual(run_process.call_count, 1)

    def test_locked_temporary_output_is_not_counted_as_second_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            video_dir = input_dir / 'NSPS-958'
            video_dir.mkdir(parents=True)
            video = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.mp4'
            subtitle = video_dir / 'NSPS-958.vtt'
            video.write_bytes(b'video')
            subtitle.write_text(
                'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n',
                encoding='utf-8',
            )
            locked = video_dir / '【NSPS-958】熟女10 ～こんなおばさんでもいい.softsub.tmp.mp4'
            locked.write_bytes(b'partial')

            real_unlink = Path.unlink

            def guarded_unlink(self, *args, **kwargs):
                if str(self).endswith('.softsub.tmp.mp4'):
                    raise PermissionError('locked by another process')
                return real_unlink(self, *args, **kwargs)

            with patch('pathlib.Path.unlink', guarded_unlink):
                result = SoftSubtitleGenerationService(input_dir).generate_from_directory()

            self.assertEqual(result['failed_count'], 1)
            error = result['results'][0]['error']
            self.assertIn('软字幕临时文件已存在', error)
            self.assertNotIn('匹配到 2 个编号', error)

    def test_second_run_while_one_is_active_returns_occupied_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'translation_videos'
            service = SoftSubtitleGenerationService(input_dir)
            self.assertTrue(service._run_lock.acquire(blocking=False))
            try:
                with patch(
                    'app.services.translation.soft_subtitle_generation_service.subprocess.run',
                ) as run_process:
                    result = service.generate_from_directory()
            finally:
                service._run_lock.release()

            self.assertTrue(result['occupied'])
            self.assertEqual(result['failed_count'], 1)
            self.assertIn('正在运行', result['results'][0]['error'])
            run_process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
