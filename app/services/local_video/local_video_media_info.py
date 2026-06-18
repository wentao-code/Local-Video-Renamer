import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalVideoMediaInfo:
    duration: str
    size_gb: str


def read_local_video_media_info(file_path):
    path = Path(file_path)
    return LocalVideoMediaInfo(
        duration=format_duration_seconds(probe_video_duration_seconds(path)),
        size_gb=format_size_gb(path.stat().st_size),
    )


def probe_video_duration_seconds(file_path):
    ffprobe_path = shutil.which('ffprobe')
    if not ffprobe_path:
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe_path,
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    try:
        duration = float(str(completed.stdout or '').strip())
    except ValueError:
        return None
    if duration <= 0:
        return None
    return duration


def format_duration_seconds(duration_seconds):
    if duration_seconds is None:
        return ''
    total_seconds = max(0, int(round(float(duration_seconds))))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f'{hours}:{minutes:02d}:{seconds:02d}'


def format_size_gb(size_bytes):
    size_gb = max(0, int(size_bytes or 0)) / (1024 ** 3)
    formatted = f'{size_gb:.3f}'.rstrip('0').rstrip('.')
    return formatted or '0'
