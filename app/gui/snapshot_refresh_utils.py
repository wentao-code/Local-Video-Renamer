def format_refresh_duration_seconds(duration_ms):
    total_seconds = max(0, int(round(int(duration_ms or 0) / 1000.0)))
    return f'{total_seconds}秒'


def resolve_refresh_duration_text(payload):
    current = dict(payload or {})
    duration_ms = int(current.get('refresh_duration_ms', 0) or 0)
    if duration_ms > 0:
        return format_refresh_duration_seconds(duration_ms)
    return str(current.get('refresh_duration_text', '') or '').strip()
