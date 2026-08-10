from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.video_code import standardize_video_code
from app.services.parsers.code_prefix_entry_parser import extract_code

EXTERNAL_SUBTITLE_SUFFIXES = frozenset(('.srt', '.vtt', '.ass'))
VIDEO_SUFFIXES = frozenset(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv'))


def probe_subtitle_stream_count(file_path):
    """Return how many subtitle streams the video contains via ffprobe (0 on failure)."""
    ffprobe_path = shutil.which('ffprobe')
    if not ffprobe_path:
        return 0
    try:
        completed = subprocess.run(
            [
                ffprobe_path,
                '-v',
                'error',
                '-show_entries',
                'stream=codec_type',
                '-of',
                'json',
                str(file_path),
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=get_operation_timeout_seconds('local_media_read'),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if completed.returncode != 0:
        return 0
    try:
        payload = json.loads(str(completed.stdout or '{}'))
    except (TypeError, ValueError):
        return 0
    streams = payload.get('streams') if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return 0
    return sum(1 for stream in streams if str(stream.get('codec_type') or '') == 'subtitle')


def find_external_subtitle(video_path):
    """Return the sibling subtitle file (same stem or same code) or None."""
    video = Path(video_path)
    directory = video.parent
    stem_candidates = [video.stem]
    code = standardize_video_code(extract_code(video.stem) or '')
    if code:
        stem_candidates.append(code)
    for candidate in stem_candidates:
        for suffix in EXTERNAL_SUBTITLE_SUFFIXES:
            path = directory / f'{candidate}{suffix}'
            if path.is_file():
                return path
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in EXTERNAL_SUBTITLE_SUFFIXES:
            continue
        if path.stem.casefold() == video.stem.casefold():
            return path
        if code and path.stem.casefold() == code.casefold():
            return path
    return None


def classify_videos(input_dir):
    """Split videos under input_dir into embedded / external / none subtitle states."""
    directory = Path(input_dir)
    embedded = []
    external = []
    none = []
    for path in sorted(
        candidate for candidate in directory.rglob('*')
        if candidate.is_file() and candidate.suffix.lower() in VIDEO_SUFFIXES
    ):
        if probe_subtitle_stream_count(path) > 0:
            embedded.append(path)
            continue
        external_subtitle = find_external_subtitle(path)
        if external_subtitle is not None:
            external.append({'video': path, 'subtitle': external_subtitle})
            continue
        none.append(path)
    return {
        'embedded': embedded,
        'external': external,
        'none': none,
    }
