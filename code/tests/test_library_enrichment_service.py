import unittest
from unittest.mock import patch

from app.core.enrichment_sources import DEFAULT_VIDEO_ENRICHMENT_SOURCE
from app.core.enrichment_targets import VIDEO_LIBRARY_TARGET
from app.services.enrichment.library_enrichment_service import LibraryEnrichmentService


class LibraryEnrichmentServicePlanTests(unittest.TestCase):
    def test_planned_video_items_are_combined_with_existing_filter(self):
        captured = {}

        class FakeVideoSourceService:
            def __init__(self, *args, candidate_filter=None, **kwargs):
                captured['candidate_filter'] = candidate_filter

            def enrich_next_videos(self, limit):
                candidate_filter = captured['candidate_filter']
                rows = [
                    {'code': 'AAA-001', 'allowed': True},
                    {'code': 'BBB-002', 'allowed': False},
                    {'code': 'CCC-003', 'allowed': True},
                ]
                selected = [row['code'] for row in rows if candidate_filter(row)]
                return {'processed_count': len(selected), 'results': [{'code': code, 'status': 'ok'} for code in selected]}

        with patch(
            'app.services.enrichment.library_enrichment_service.VideoSourceEnrichmentService',
            FakeVideoSourceService,
        ):
            service = LibraryEnrichmentService(
                database=object(),
                video_candidate_filter=lambda row: bool(row.get('allowed')),
                planned_items=[{'code': 'AAA-001'}, {'code': 'BBB-002'}],
            )
            result = service.run(
                VIDEO_LIBRARY_TARGET,
                5,
                source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
            )

        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['results'], [{'code': 'AAA-001', 'status': 'ok'}])


if __name__ == '__main__':
    unittest.main()
