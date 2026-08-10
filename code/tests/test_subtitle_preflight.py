import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.translation.subtitle_preflight import (
    classify_videos,
    find_external_subtitle,
    probe_subtitle_stream_count,
)


class SubtitlePreflightTest(unittest.TestCase):
    def test_probe_counts_subtitle_streams(self):
        payload = json.dumps(
            {
                'streams': [
                    {'codec_type': 'video'},
                    {'codec_type': 'audio'},
                    {'codec_type': 'subtitle'},
                ]
            }
        )
        with patch(
            'app.services.translation.subtitle_preflight.subprocess.run',
            return_value=SimpleNamespace(returncode=0, stdout=payload),
        ) as run_process:
            self.assertEqual(probe_subtitle_stream_count(Path('movie.mp4')), 1)
        run_process.assert_called_once()

    def test_probe_returns_zero_when_ffprobe_fails(self):
        with patch(
            'app.services.translation.subtitle_preflight.subprocess.run',
            side_effect=OSError('missing ffprobe'),
        ):
            self.assertEqual(probe_subtitle_stream_count(Path('movie.mp4')), 0)

    def test_probe_returns_zero_for_bad_output(self):
        with patch(
            'app.services.translation.subtitle_preflight.subprocess.run',
            return_value=SimpleNamespace(returncode=0, stdout='not-json'),
        ):
            self.assertEqual(probe_subtitle_stream_count(Path('movie.mp4')), 0)

    def test_finds_same_stem_external_subtitle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            video = directory / '【NSPS-958】-title.mp4'
            video.write_bytes(b'video')
            subtitle = directory / '【NSPS-958】-title.srt'
            subtitle.write_text('1\n', encoding='utf-8')

            self.assertEqual(find_external_subtitle(video), subtitle)

    def test_finds_code_named_external_subtitle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            video = directory / '【NSPS-958】-title.mp4'
            video.write_bytes(b'video')
            subtitle = directory / 'NSPS-958.vtt'
            subtitle.write_text('WEBVTT\n', encoding='utf-8')

            self.assertEqual(find_external_subtitle(video), subtitle)

    def test_returns_none_without_external_subtitle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            video = directory / '【NSPS-958】-title.mp4'
            video.write_bytes(b'video')
            (directory / 'other.srt').write_text('1\n', encoding='utf-8')

            self.assertIsNone(find_external_subtitle(video))

    def test_classify_videos_splits_three_kinds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir)
            embedded = input_dir / 'embedded.mp4'
            external_video = input_dir / 'external.mp4'
            missing = input_dir / 'missing.mp4'
            embedded.write_bytes(b'video')
            external_video.write_bytes(b'video')
            missing.write_bytes(b'video')
            (input_dir / 'external.srt').write_text('1\n', encoding='utf-8')

            def fake_probe(path):
                return 1 if Path(path).name == 'embedded.mp4' else 0

            with patch(
                'app.services.translation.subtitle_preflight.probe_subtitle_stream_count',
                side_effect=fake_probe,
            ):
                result = classify_videos(input_dir)

            self.assertEqual([p.name for p in result['embedded']], ['embedded.mp4'])
            self.assertEqual([p.name for p in result['none']], ['missing.mp4'])
            self.assertEqual([entry['video'].name for entry in result['external']], ['external.mp4'])
            self.assertEqual(result['external'][0]['subtitle'].name, 'external.srt')


if __name__ == '__main__':
    unittest.main()
