from app.core.project_paths import VIDEO_LIBRARY_SETTINGS_FILE
from app.gui.library_sort_settings import load_sort_settings, save_sort_settings
from app.gui.video_library_sorting import normalize_video_sort_settings


def load_video_library_settings():
    return load_sort_settings(VIDEO_LIBRARY_SETTINGS_FILE, normalize_video_library_settings)


def save_video_library_settings(settings):
    save_sort_settings(VIDEO_LIBRARY_SETTINGS_FILE, settings, normalize_video_library_settings)


def normalize_video_library_settings(settings):
    settings = dict(settings or {}) if isinstance(settings, dict) else {}
    return normalize_video_sort_settings(settings)
