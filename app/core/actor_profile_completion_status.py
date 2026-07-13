from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)


_PROFILE_STATE_BY_FIELDS = {
    (True, True, True, True): 0,
    (False, False, False, False): 2,
    (True, False, False, False): 3,
    (False, True, False, False): 4,
    (False, False, True, False): 5,
    (False, False, False, True): 6,
    (True, True, False, False): 7,
    (True, False, True, False): 8,
    (True, False, False, True): 9,
    (False, True, True, False): 10,
    (False, True, False, True): 11,
    (False, False, True, True): 12,
    (False, True, True, True): 13,
    (True, False, True, True): 14,
    (True, True, False, True): 15,
    (True, True, True, False): 16,
}

_SOURCE_PREFIXES = {
    BINGHUO_ACTOR_SOURCE: 'binghuo',
    BAOMU_ACTOR_SOURCE: 'baomu',
}


def build_actor_profile_completion_status(profile, has_result):
    if not has_result:
        return '状态1'
    profile = dict(profile or {})
    fields = (
        _has_value(profile.get('birthday')),
        all(_has_value(profile.get(field)) for field in ('bust', 'waist', 'hip')),
        _has_value(profile.get('height')),
        _has_value(profile.get('cup')),
    )
    return f'状态{_PROFILE_STATE_BY_FIELDS[fields]}'


def build_actor_source_completion_status(record, source_key):
    record = dict(record or {})
    prefix = _SOURCE_PREFIXES[source_key]
    operational_status = _source_operational_status(record, prefix)
    if operational_status == NO_SEARCH_RESULTS_STATUS:
        return '状态1'
    if not _source_has_result(record, prefix, operational_status):
        return operational_status
    return build_actor_profile_completion_status(_source_profile(record, prefix), has_result=True)


def build_actor_final_completion_status(record):
    record = dict(record or {})
    source_statuses = {
        prefix: _source_operational_status(record, prefix)
        for prefix in _SOURCE_PREFIXES.values()
    }
    if all(status == NO_SEARCH_RESULTS_STATUS for status in source_statuses.values()):
        return '状态1'

    has_result = any(
        _source_has_result(record, prefix, source_statuses[prefix])
        for prefix in source_statuses
    )
    if has_result:
        return build_actor_profile_completion_status(_merged_profile(record), has_result=True)
    if UNENRICHED_STATUS in source_statuses.values():
        return UNENRICHED_STATUS
    if FAILED_STATUS in source_statuses.values():
        return FAILED_STATUS
    return next(iter(source_statuses.values()), UNENRICHED_STATUS)


def _source_operational_status(record, prefix):
    return str(record.get(f'{prefix}_enrichment_status', '') or '').strip() or UNENRICHED_STATUS


def _source_profile(record, prefix):
    return {
        field: record.get(f'{prefix}_{field}', '')
        for field in ('birthday', 'height', 'bust', 'cup', 'waist', 'hip')
    }


def _source_has_result(record, prefix, operational_status):
    if operational_status == NO_SEARCH_RESULTS_STATUS:
        return False
    if operational_status in (ENRICHED_STATUS, NO_VIDEO_DETAIL_STATUS):
        return True
    if prefix == 'binghuo' and _has_value(record.get('binghuo_person_id')):
        return True
    return any(_has_value(value) for value in _source_profile(record, prefix).values())


def _merged_profile(record):
    merged = {}
    for field in ('birthday', 'height', 'bust', 'cup', 'waist', 'hip'):
        merged[field] = next(
            (
                record.get(f'{prefix}_{field}', '')
                for prefix in _SOURCE_PREFIXES.values()
                if _has_value(record.get(f'{prefix}_{field}', ''))
            ),
            '',
        )
    return merged


def _has_value(value):
    return bool(str(value or '').strip())
