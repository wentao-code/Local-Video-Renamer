import json


def load_sort_settings(settings_file, normalize):
    if not settings_file.exists():
        return normalize({})
    try:
        loaded = json.loads(settings_file.read_text(encoding='utf-8'))
    except Exception:
        loaded = {}
    return normalize(loaded)


def save_sort_settings(settings_file, settings, normalize):
    settings_file.write_text(
        json.dumps(normalize(settings), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
