"""Compact enrichment states used by library list views."""

from app.core.actor_profile_completion_status import (
    ACTOR_STATUS_FAILED,
    ACTOR_STATUS_PENDING,
    ACTOR_STATUS_UNENRICHED,
    build_actor_source_completion_status,
)
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
    STATUS_REGISTRY,
    normalize_enrichment_status,
)


DISPLAY_STATUS_UNENRICHED = STATUS_REGISTRY[UNENRICHED_STATUS]['display_code']
DISPLAY_STATUS_NO_RESULT = STATUS_REGISTRY[NO_SEARCH_RESULTS_STATUS]['display_code']
DISPLAY_STATUS_NO_DETAIL = STATUS_REGISTRY[NO_VIDEO_DETAIL_STATUS]['display_code']
DISPLAY_STATUS_ENRICHED = STATUS_REGISTRY[ENRICHED_STATUS]['display_code']
DISPLAY_STATUS_FAILED = STATUS_REGISTRY[FAILED_STATUS]['display_code']
DISPLAY_STATUS_PENDING = STATUS_REGISTRY['PENDING']['display_code']


_RAW_STATUS_MAP = {
    UNENRICHED_STATUS: DISPLAY_STATUS_UNENRICHED,
    NO_SEARCH_RESULTS_STATUS: DISPLAY_STATUS_NO_RESULT,
    NO_VIDEO_DETAIL_STATUS: DISPLAY_STATUS_NO_DETAIL,
    ENRICHED_STATUS: DISPLAY_STATUS_ENRICHED,
    FAILED_STATUS: DISPLAY_STATUS_FAILED,
}


# Sources intentionally use two status domains. Keep this registry as the
# single place that decides which record field and display mapper apply.
SOURCE_STATUS_RULES = {
    AVFAN_VIDEO_SOURCE: {'field': 'avfan_enrichment_status', 'domain': 'library'},
    JAVTXT_VIDEO_SOURCE: {'field': 'javtxt_enrichment_status', 'domain': 'library'},
    SUPPLEMENT_TASK_SOURCE: {'field': 'supplement_enrichment_status', 'domain': 'library'},
    BINGHUO_ACTOR_SOURCE: {'field': 'binghuo_completion_status', 'domain': 'actor_profile'},
    BAOMU_ACTOR_SOURCE: {'field': 'baomu_completion_status', 'domain': 'actor_profile'},
}


def display_enrichment_status(raw_status='', *, selected=False, running=False):
    """Map a detailed status to the compact UI state.

    Queue membership wins over the persisted result so selected and running
    work cannot appear as unselected while it is waiting for execution.
    """
    if selected or running:
        return DISPLAY_STATUS_PENDING
    return _RAW_STATUS_MAP.get(normalize_enrichment_status(raw_status), DISPLAY_STATUS_UNENRICHED)


def get_source_display_status(source_key, record=None, *, selected=False, running=False, status_override=None):
    """Return the display value using the status domain registered for a source."""
    rule = SOURCE_STATUS_RULES.get(str(source_key or '').strip())
    if rule is None:
        raise ValueError(f'未知补全状态来源: {source_key}')

    current = dict(record or {})
    if status_override is not None:
        raw_status = status_override
    else:
        raw_status = current.get(rule['field'], '')

    if rule['domain'] == 'actor_profile':
        prefix = str(source_key or '').strip()
        operational_status = normalize_enrichment_status(
            current.get(f'{prefix}_enrichment_status', '')
        )
        if selected or running:
            return ACTOR_STATUS_PENDING
        if str(operational_status or '').strip() == UNENRICHED_STATUS:
            return ACTOR_STATUS_UNENRICHED
        if str(operational_status or '').strip() == FAILED_STATUS:
            return ACTOR_STATUS_FAILED
        if not str(raw_status or '').strip():
            raw_status = build_actor_source_completion_status(current, source_key)
        return str(raw_status or '').strip() or '状态1'

    return display_enrichment_status(raw_status, selected=selected, running=running)
