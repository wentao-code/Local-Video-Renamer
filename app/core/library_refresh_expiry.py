from datetime import datetime, timedelta

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
)


EXPIRED_STATUS = '已过期'
LIBRARY_REFRESH_EXPIRY_DAYS = 90
EXPIRABLE_UPDATE_STATUSES = {'active', 'suspect'}
EXPIRABLE_ENRICHMENT_STATUSES = {
    ENRICHED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
}


def is_library_refresh_expired(last_completed_at, update_status, now=None):
    if str(update_status or '').strip() not in EXPIRABLE_UPDATE_STATUSES:
        return False
    completed_at = _parse_datetime(last_completed_at)
    if completed_at is None:
        return False
    reference_time = now or datetime.now()
    return completed_at < reference_time - timedelta(days=LIBRARY_REFRESH_EXPIRY_DAYS)


def effective_library_refresh_status(status, last_completed_at, update_status, now=None):
    normalized_status = str(status or '').strip()
    if normalized_status not in EXPIRABLE_ENRICHMENT_STATUSES:
        return normalized_status
    if is_library_refresh_expired(last_completed_at, update_status, now=now):
        return EXPIRED_STATUS
    return normalized_status


def _parse_datetime(value):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None
