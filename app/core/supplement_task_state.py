from app.core.enrichment_status import UNENRICHED_STATUS, is_no_result_status
from app.core.javtxt_entry_state import (
    JAVTXT_ACTOR_STATE_BLANK,
    JAVTXT_ACTOR_STATE_UNPUBLISHED,
    classify_actor_state,
    has_detail_reference,
)
from app.core.video_filter_rules import should_skip_video_before_enrichment
from app.core.video_code import has_supported_video_code, standardize_video_code


SUPPLEMENT_MODE_ACTORS_ONLY = 'actors_only'
SUPPLEMENT_MODE_FULL = 'full'


def _resolve_current_actor_fields(record=None):
    current = dict(record or {})
    author = str(current.get('author', '') or '').strip()
    author_raw = str(current.get('author_raw', '') or '').strip() or author
    return author, author_raw


def _classify_current_actor_state(record=None):
    current = dict(record or {})
    author, author_raw = _resolve_current_actor_fields(current)
    return classify_actor_state(
        {
            **current,
            'author': author,
            'author_raw': author_raw,
        },
        cached_row={
            **current,
            'author': author,
            'author_raw': author_raw,
        },
    )


def _is_retryable_supplement_status(record=None):
    current = dict(record or {})
    status = str(current.get('supplement_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
    return status == UNENRICHED_STATUS

def classify_supplement_mode(record=None):
    current = dict(record or {})
    code = standardize_video_code(current.get('code', ''))
    if not code or not has_supported_video_code(code):
        return ''
    if not _is_retryable_supplement_status(current):
        return ''
    actor_state = _classify_current_actor_state(current)
    if has_detail_reference(current, cached_row=current) and actor_state in (
        JAVTXT_ACTOR_STATE_BLANK,
        JAVTXT_ACTOR_STATE_UNPUBLISHED,
    ):
        return SUPPLEMENT_MODE_ACTORS_ONLY
    status = str(current.get('javtxt_enrichment_status', '') or '').strip()
    if is_no_result_status(status) and (
        actor_state == JAVTXT_ACTOR_STATE_BLANK
        or not str(current.get('title', '') or '').strip()
        or not str(current.get('release_date', '') or '').strip()
    ):
        return SUPPLEMENT_MODE_FULL
    return ''


def build_supplement_candidate(record=None, filter_settings=None):
    current = dict(record or {})
    if filter_settings is not None and should_skip_video_before_enrichment(current, filter_settings):
        return {}
    mode = classify_supplement_mode(current)
    if not mode:
        return {}
    return {
        'code': standardize_video_code(current.get('code', '')),
        'supplement_mode': mode,
        'supplement_priority': 0 if mode == SUPPLEMENT_MODE_ACTORS_ONLY else 1,
    }
