from app.core.project_paths import CODE_PREFIX_LIBRARY_SETTINGS_FILE
from app.gui.code_prefix_library_sorting import normalize_code_prefix_sort_settings
from app.gui.library_sort_settings import load_sort_settings, save_sort_settings


def load_code_prefix_library_settings():
    return load_sort_settings(CODE_PREFIX_LIBRARY_SETTINGS_FILE, normalize_code_prefix_library_settings)


def save_code_prefix_library_settings(settings):
    save_sort_settings(CODE_PREFIX_LIBRARY_SETTINGS_FILE, settings, normalize_code_prefix_library_settings)


def normalize_code_prefix_library_settings(settings):
    settings = dict(settings or {}) if isinstance(settings, dict) else {}
    return normalize_code_prefix_sort_settings(settings)
