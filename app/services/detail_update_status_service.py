import re
from datetime import date

from app.services.video_category_service import VIDEO_CATEGORY_CO_STAR, VIDEO_CATEGORY_SINGLE


UPDATE_STATUS_ACTIVE = 'active'
UPDATE_STATUS_SUSPECT = 'suspect'
UPDATE_STATUS_INACTIVE = 'inactive'

ACTIVE_UPDATE_DAY_WINDOW = 256
SUSPECT_UPDATE_DAY_WINDOW = 512

_DATE_RE = re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})')
_TRACKED_CATEGORIES = {
    VIDEO_CATEGORY_SINGLE,
    VIDEO_CATEGORY_CO_STAR,
}


def resolve_update_status(rows, today=None):
    latest_release_date = find_latest_tracked_release_date(rows)
    if latest_release_date is None:
        return UPDATE_STATUS_INACTIVE

    reference_day = today or date.today()
    elapsed_days = max((reference_day - latest_release_date).days, 0)
    if elapsed_days <= ACTIVE_UPDATE_DAY_WINDOW:
        return UPDATE_STATUS_ACTIVE
    if elapsed_days <= SUSPECT_UPDATE_DAY_WINDOW:
        return UPDATE_STATUS_SUSPECT
    return UPDATE_STATUS_INACTIVE


def find_latest_tracked_release_date(rows):
    latest_release_date = None
    for row in rows or []:
        if str((row or {}).get('video_category', '') or '').strip() not in _TRACKED_CATEGORIES:
            continue
        release_date = _parse_release_date((row or {}).get('release_date', ''))
        if release_date is None:
            continue
        if latest_release_date is None or release_date > latest_release_date:
            latest_release_date = release_date
    return latest_release_date


def _parse_release_date(value):
    text = str(value or '').strip()
    if not text:
        return None
    match = _DATE_RE.search(text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
