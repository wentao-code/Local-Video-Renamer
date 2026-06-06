from app.core.project_paths import ACTOR_LIBRARY_SETTINGS_FILE
from app.gui.actor_library_sorting import normalize_actor_sort_settings
from app.gui.library_sort_settings import load_sort_settings, save_sort_settings


def load_actor_library_settings():
    return load_sort_settings(ACTOR_LIBRARY_SETTINGS_FILE, normalize_actor_library_settings)


def save_actor_library_settings(settings):
    save_sort_settings(ACTOR_LIBRARY_SETTINGS_FILE, settings, normalize_actor_library_settings)


def normalize_actor_library_settings(settings):
    settings = dict(settings or {}) if isinstance(settings, dict) else {}
    return normalize_actor_sort_settings(settings)
