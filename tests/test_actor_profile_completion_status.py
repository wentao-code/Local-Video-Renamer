import importlib

import pytest

from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)


@pytest.mark.parametrize(
    ('birthday', 'measurements', 'height', 'cup', 'expected'),
    [
        (True, True, True, True, '状态0'),
        (False, False, False, False, '状态2'),
        (True, False, False, False, '状态3'),
        (False, True, False, False, '状态4'),
        (False, False, True, False, '状态5'),
        (False, False, False, True, '状态6'),
        (True, True, False, False, '状态7'),
        (True, False, True, False, '状态8'),
        (True, False, False, True, '状态9'),
        (False, True, True, False, '状态10'),
        (False, True, False, True, '状态11'),
        (False, False, True, True, '状态12'),
        (False, True, True, True, '状态13'),
        (True, False, True, True, '状态14'),
        (True, True, False, True, '状态15'),
        (True, True, True, False, '状态16'),
    ],
)
def test_actor_profile_field_combinations_map_to_requested_states(
    birthday,
    measurements,
    height,
    cup,
    expected,
):
    module = importlib.import_module('app.core.actor_profile_completion_status')
    profile = {
        'birthday': '2000-01-01' if birthday else '',
        'bust': '88' if measurements else '',
        'waist': '60' if measurements else '',
        'hip': '89' if measurements else '',
        'height': '168' if height else '',
        'cup': 'F' if cup else '',
    }

    assert module.build_actor_profile_completion_status(profile, has_result=True) == expected


def test_actor_profile_no_search_result_is_state_one():
    module = importlib.import_module('app.core.actor_profile_completion_status')

    assert module.build_actor_profile_completion_status({}, has_result=False) == '状态1'


def test_source_state_uses_profile_fields_for_partial_binghuo_result():
    module = importlib.import_module('app.core.actor_profile_completion_status')
    record = {
        'binghuo_enrichment_status': NO_VIDEO_DETAIL_STATUS,
        'binghuo_person_id': '1001',
        'binghuo_height': '168',
        'binghuo_cup': 'F',
    }

    assert module.build_actor_source_completion_status(record, BINGHUO_ACTOR_SOURCE) == '状态12'


def test_source_state_preserves_pending_and_failed_operational_statuses():
    module = importlib.import_module('app.core.actor_profile_completion_status')

    assert module.build_actor_source_completion_status(
        {'baomu_enrichment_status': UNENRICHED_STATUS},
        BAOMU_ACTOR_SOURCE,
    ) == UNENRICHED_STATUS
    assert module.build_actor_source_completion_status(
        {'baomu_enrichment_status': FAILED_STATUS},
        BAOMU_ACTOR_SOURCE,
    ) == FAILED_STATUS


def test_final_state_merges_binghuo_and_baomu_fields():
    module = importlib.import_module('app.core.actor_profile_completion_status')
    record = {
        'binghuo_enrichment_status': ENRICHED_STATUS,
        'binghuo_birthday': '2000-01-01',
        'baomu_enrichment_status': ENRICHED_STATUS,
        'baomu_bust': '88',
        'baomu_waist': '60',
        'baomu_hip': '89',
    }

    assert module.build_actor_final_completion_status(record) == '状态7'


def test_final_state_is_state_one_only_when_both_sources_have_no_result():
    module = importlib.import_module('app.core.actor_profile_completion_status')
    no_results = {
        'binghuo_enrichment_status': NO_SEARCH_RESULTS_STATUS,
        'baomu_enrichment_status': NO_SEARCH_RESULTS_STATUS,
    }
    one_pending = {
        'binghuo_enrichment_status': NO_SEARCH_RESULTS_STATUS,
        'baomu_enrichment_status': UNENRICHED_STATUS,
    }

    assert module.build_actor_final_completion_status(no_results) == '状态1'
    assert module.build_actor_final_completion_status(one_pending) == UNENRICHED_STATUS
