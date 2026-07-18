import unittest

from app.core.enrichment_display_status import (
    DISPLAY_STATUS_ENRICHED,
    DISPLAY_STATUS_FAILED,
    DISPLAY_STATUS_NO_DETAIL,
    DISPLAY_STATUS_NO_RESULT,
    DISPLAY_STATUS_PENDING,
    DISPLAY_STATUS_UNENRICHED,
    display_enrichment_status,
    get_source_display_status,
)
from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
    get_enrichment_status_display_code,
    get_enrichment_status_label,
    normalize_enrichment_status,
)


class EnrichmentDisplayStatusTest(unittest.TestCase):
    def test_status_registry_uses_stable_codes_and_accepts_legacy_values(self):
        self.assertEqual(UNENRICHED_STATUS, 'UNENRICHED')
        self.assertEqual(ENRICHED_STATUS, 'ENRICHED')
        self.assertEqual(normalize_enrichment_status('未补全'), UNENRICHED_STATUS)
        self.assertEqual(normalize_enrichment_status('无搜索结果'), NO_SEARCH_RESULTS_STATUS)
        self.assertEqual(normalize_enrichment_status('x'), UNENRICHED_STATUS)
        self.assertEqual(get_enrichment_status_label(FAILED_STATUS), '补全失败')
        self.assertEqual(get_enrichment_status_display_code(NO_VIDEO_DETAIL_STATUS), 'z')

    def test_raw_statuses_map_to_short_display_states(self):
        self.assertEqual(display_enrichment_status(UNENRICHED_STATUS), DISPLAY_STATUS_UNENRICHED)
        self.assertEqual(display_enrichment_status(NO_SEARCH_RESULTS_STATUS), DISPLAY_STATUS_NO_RESULT)
        self.assertEqual(display_enrichment_status(NO_VIDEO_DETAIL_STATUS), DISPLAY_STATUS_NO_DETAIL)
        self.assertEqual(display_enrichment_status(ENRICHED_STATUS), DISPLAY_STATUS_ENRICHED)
        self.assertEqual(display_enrichment_status(FAILED_STATUS), DISPLAY_STATUS_FAILED)

    def test_selected_or_running_candidate_overrides_raw_status(self):
        self.assertEqual(
            display_enrichment_status(UNENRICHED_STATUS, selected=True),
            DISPLAY_STATUS_PENDING,
        )
        self.assertEqual(
            display_enrichment_status(ENRICHED_STATUS, running=True),
            DISPLAY_STATUS_PENDING,
        )

    def test_actor_profile_sources_keep_completion_status_domain(self):
        record = {
            'binghuo_completion_status': '状态3',
            'baomu_completion_status': '状态13',
            'binghuo_enrichment_status': ENRICHED_STATUS,
            'baomu_enrichment_status': ENRICHED_STATUS,
        }
        self.assertEqual(get_source_display_status(BINGHUO_ACTOR_SOURCE, record), '状态3')
        self.assertEqual(get_source_display_status(BAOMU_ACTOR_SOURCE, record), '状态13')

    def test_library_sources_use_compact_display_domain(self):
        self.assertEqual(
            get_source_display_status('avfan', {'avfan_enrichment_status': ENRICHED_STATUS}),
            'f',
        )

    def test_actor_profile_queue_and_operational_states_use_18_to_20(self):
        self.assertEqual(
            get_source_display_status(
                BINGHUO_ACTOR_SOURCE,
                {'binghuo_enrichment_status': UNENRICHED_STATUS, 'binghuo_completion_status': '状态1'},
            ),
            '状态18',
        )
        self.assertEqual(
            get_source_display_status(
                BINGHUO_ACTOR_SOURCE,
                {'binghuo_enrichment_status': FAILED_STATUS, 'binghuo_completion_status': '状态1'},
            ),
            '状态20',
        )
        self.assertEqual(
            get_source_display_status(
                BINGHUO_ACTOR_SOURCE,
                {'binghuo_enrichment_status': UNENRICHED_STATUS},
                selected=True,
            ),
            '状态19',
        )


if __name__ == '__main__':
    unittest.main()
