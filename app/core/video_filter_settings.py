import json

from app.core.project_paths import VIDEO_FILTER_SETTINGS_FILE
from app.core.video_filter_rules import DEFAULT_VIDEO_FILTER_SETTINGS, normalize_video_filter_settings


def load_video_filter_settings(settings_file=None):
    target_file = settings_file or VIDEO_FILTER_SETTINGS_FILE
    if not target_file.exists():
        return normalize_video_filter_settings(DEFAULT_VIDEO_FILTER_SETTINGS)
    try:
        loaded = json.loads(target_file.read_text(encoding='utf-8'))
    except Exception:
        loaded = {}
    return normalize_video_filter_settings(loaded)


def save_video_filter_settings(settings, settings_file=None):
    target_file = settings_file or VIDEO_FILTER_SETTINGS_FILE
    normalized = normalize_video_filter_settings(settings)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return normalized
