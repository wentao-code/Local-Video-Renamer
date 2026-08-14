import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.translation.subtitle_pipeline_service import SubtitlePipelineService


def _generation_result(success=1, failed=0, video_count=None, input_dir='D:/subs', run_id='gen-1'):
    return {
        'run_id': run_id,
        'input_dir': input_dir,
        'video_count': success + failed if video_count is None else video_count,
        'success_count': success,
        'failed_count': failed,
        'results': [],
    }


def _mux_result(success=1, failed=0, input_dir='D:/subs', run_id='mux-1'):
    return {
        'run_id': run_id,
        'input_dir': input_dir,
        'directory_count': success + failed,
        'success_count': success,
        'failed_count': failed,
        'results': [],
    }


class SubtitlePipelineServiceTest(unittest.TestCase):
    def test_per_video_pipeline_only_writes_its_own_candidate_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            video = input_dir / 'AAA-001.mp4'
            video.write_bytes(b'video')
            generation = Mock()
            mux = Mock()
            generation.generate_from_directory.return_value = {
                **_generation_result(input_dir=str(input_dir)),
                'results': [{'video_path': str(video), 'status': 'completed'}],
            }
            mux.generate_from_directory.return_value = _mux_result(input_dir=str(input_dir))

            with patch(
                'app.services.translation.subtitle_pipeline_service.classify_videos',
                return_value={'embedded': [], 'external': [], 'none': [video]},
            ):
                SubtitlePipelineService(generation, mux).run(
                    input_dir=str(input_dir),
                    candidate_codes=['AAA-001'],
                    candidate_run_id='subtitle-candidates-1',
                    manage_candidate_task=False,
                )

            self.assertEqual(
                generation.update_candidate_task.call_args_list,
                [
                    unittest.mock.call(
                        'subtitle-candidates-1',
                        result_statuses={'AAA-001': 'completed'},
                    ),
                ],
            )

    def test_per_video_pipeline_marks_candidate_failed_when_mux_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            video = input_dir / 'AAA-001.mp4'
            video.write_bytes(b'video')
            generation = Mock()
            mux = Mock()
            generation.generate_from_directory.return_value = {
                **_generation_result(input_dir=str(input_dir)),
                'results': [{'video_path': str(video), 'status': 'completed'}],
            }
            mux.generate_from_directory.return_value = _mux_result(
                success=0,
                failed=1,
                input_dir=str(input_dir),
            )

            with patch(
                'app.services.translation.subtitle_pipeline_service.classify_videos',
                return_value={'embedded': [], 'external': [], 'none': [video]},
            ):
                SubtitlePipelineService(generation, mux).run(
                    input_dir=str(input_dir),
                    candidate_codes=['AAA-001'],
                    candidate_run_id='subtitle-candidates-1',
                    manage_candidate_task=False,
                )

            self.assertEqual(
                generation.update_candidate_task.call_args_list[-1],
                unittest.mock.call(
                    'subtitle-candidates-1',
                    result_statuses={'AAA-001': 'failed'},
                ),
            )

    def test_processes_each_video_before_starting_the_next_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            first = input_dir / 'AAA-001.mp4'
            second = input_dir / 'AAA-002.mp4'
            first.write_bytes(b'video')
            second.write_bytes(b'video')
            events = []

            generation = Mock()
            mux = Mock()

            def generate(**kwargs):
                code = sorted(kwargs['candidate_codes'])[0]
                events.append(('generate', code))
                return {
                    'run_id': f'gen-{code}',
                    'input_dir': str(input_dir),
                    'video_count': 1,
                    'success_count': 1,
                    'failed_count': 0,
                    'results': [
                        {
                            'video_path': str(input_dir / f'{code}.mp4'),
                            'status': 'completed',
                        },
                    ],
                }

            def mux_one(**kwargs):
                code = sorted(kwargs['candidate_codes'])[0]
                events.append(('mux', code))
                return {
                    'run_id': f'mux-{code}',
                    'input_dir': str(input_dir),
                    'directory_count': 1,
                    'success_count': 1,
                    'failed_count': 0,
                    'results': [],
                }

            generation.generate_from_directory.side_effect = generate
            mux.generate_from_directory.side_effect = mux_one

            with patch(
                'app.services.translation.subtitle_pipeline_service.classify_videos',
                return_value={'embedded': [], 'external': [], 'none': [first, second]},
            ):
                SubtitlePipelineService(generation, mux).run(input_dir=str(input_dir))

            self.assertEqual(
                events,
                [
                    ('generate', 'AAA-001'),
                    ('mux', 'AAA-001'),
                    ('generate', 'AAA-002'),
                    ('mux', 'AAA-002'),
                ],
            )

    def test_runs_generation_then_mux_in_order(self):
        generation = Mock()
        mux = Mock()
        generation.generate_from_directory.return_value = _generation_result()
        mux.generate_from_directory.return_value = _mux_result()

        result = SubtitlePipelineService(generation, mux).run()

        generation.generate_from_directory.assert_not_called()
        mux.generate_from_directory.assert_not_called()
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['skipped_count'], 0)
        self.assertIn('subtitle_pipeline', result['run_id'])
        self.assertIn('没有视频', result['message'])

    def test_skips_mux_when_generation_found_no_videos(self):
        generation = Mock()
        mux = Mock()
        generation.generate_from_directory.return_value = _generation_result(
            success=0,
            failed=0,
            video_count=0,
        )

        result = SubtitlePipelineService(generation, mux).run()

        mux.generate_from_directory.assert_not_called()
        self.assertIsNone(result['mux'])
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failed_count'], 0)
        self.assertIn('没有视频', result['message'])

    def test_continues_mux_when_generation_has_failures_and_reports_skipped(self):
        generation = Mock()
        mux = Mock()
        generation.generate_from_directory.return_value = _generation_result(
            success=1,
            failed=2,
            video_count=3,
        )
        mux.generate_from_directory.return_value = _mux_result(success=1, failed=0)

        result = SubtitlePipelineService(generation, mux).run()

        mux.generate_from_directory.assert_not_called()
        self.assertEqual(result['skipped_count'], 0)
        self.assertEqual(result['success_count'], 0)
        self.assertIn('没有视频', result['message'])

    def test_keeps_both_stage_results_in_response(self):
        generation = Mock()
        mux = Mock()
        generation_result = _generation_result()
        mux_result = _mux_result()
        generation.generate_from_directory.return_value = generation_result
        mux.generate_from_directory.return_value = mux_result

        result = SubtitlePipelineService(generation, mux).run()

        self.assertIsNone(result['generation'])
        self.assertIsNone(result['mux'])
        self.assertEqual(result['input_dir'], '')

    def test_pipeline_preflights_moves_and_restores_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            embedded = input_dir / 'embedded.mp4'
            external_video = input_dir / '【NSPS-958】-title.mp4'
            missing = input_dir / 'missing.mp4'
            embedded.write_bytes(b'video')
            external_video.write_bytes(b'video')
            missing.write_bytes(b'video')
            external_srt = input_dir / 'NSPS-958.srt'
            external_srt.write_text(
                '1\n00:00:01,000 --> 00:00:02,000\nhi\n',
                encoding='utf-8',
            )

            preflight_result = {
                'embedded': [embedded],
                'external': [{'video': external_video, 'subtitle': external_srt}],
                'none': [missing],
            }
            generation = Mock()
            mux = Mock()
            generation.generate_from_directory.return_value = {
                'run_id': 'gen-1',
                'input_dir': str(input_dir),
                'video_count': 1,
                'success_count': 1,
                'failed_count': 0,
                'results': [
                    {'video_path': str(missing), 'status': 'completed'},
                ],
            }
            mux.generate_from_directory.return_value = {
                'run_id': 'mux-1',
                'input_dir': str(input_dir),
                'directory_count': 1,
                'success_count': 1,
                'failed_count': 0,
                'results': [],
            }

            def fake_convert(subtitle, target_vtt):
                target_vtt.write_text('WEBVTT\n', encoding='utf-8')
                subtitle.unlink(missing_ok=True)
                return target_vtt

            with (
                patch(
                    'app.services.translation.subtitle_pipeline_service.classify_videos',
                    return_value=preflight_result,
                ),
                patch.object(
                    SubtitlePipelineService,
                    '_convert_subtitle_to_vtt',
                    side_effect=fake_convert,
                ),
            ):
                result = SubtitlePipelineService(generation, mux).run(input_dir=str(input_dir))

            self.assertTrue(embedded.exists())
            self.assertTrue(missing.exists())
            organized_video = input_dir / 'NSPS-958' / '【NSPS-958】-title.mp4'
            self.assertTrue(organized_video.exists())
            self.assertTrue((input_dir / 'NSPS-958' / 'NSPS-958.vtt').exists())
            self.assertFalse(external_srt.exists())
            generation.generate_from_directory.assert_called_once_with(
                input_dir=str(input_dir),
                candidate_codes={'MISSING'},
            )
            self.assertEqual(mux.generate_from_directory.call_count, 2)
            self.assertEqual(
                [call.kwargs['candidate_codes'] for call in mux.generate_from_directory.call_args_list],
                [{'MISSING'}, {'NSPS-958'}],
            )
            self.assertEqual(result['embedded_count'], 1)
            self.assertEqual(result['external_count'], 1)
            self.assertEqual(result['missing_count'], 1)
            self.assertEqual(result['external_organized_count'], 1)
            self.assertEqual(result['external_failed_count'], 0)

    def test_pipeline_restores_hold_when_generation_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / 'input'
            input_dir.mkdir()
            embedded = input_dir / 'embedded.mp4'
            embedded.write_bytes(b'video')
            missing = input_dir / 'missing.mp4'
            missing.write_bytes(b'video')

            preflight_result = {
                'embedded': [embedded],
                'external': [],
                'none': [missing],
            }
            generation = Mock()
            generation.generate_from_directory.side_effect = RuntimeError('boom')
            mux = Mock()

            with (
                patch(
                    'app.services.translation.subtitle_pipeline_service.classify_videos',
                    return_value=preflight_result,
                ),
                self.assertRaises(RuntimeError),
            ):
                SubtitlePipelineService(generation, mux).run(input_dir=str(input_dir))

            self.assertTrue(embedded.exists())
            self.assertTrue(missing.exists())
            mux.generate_from_directory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
