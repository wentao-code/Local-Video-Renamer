import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.backend.service import BackendService
from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET
from app.core.enrichment_targets import CODE_PREFIX_LIBRARY_TARGET
from app.core.enrichment_targets import VIDEO_LIBRARY_TARGET


class _ActorPlanDatabase:
    def list_actors(self):
        return [{'name': 'Already Done'}, {'name': 'Needs Enrichment'}]

    def list_actor_enrichment_records(self):
        return {
            'Already Done': {
                'avfan_enrichment_status': ENRICHED_STATUS,
                'avfan_total_videos': 1,
                'javtxt_enrichment_status': ENRICHED_STATUS,
            },
            'Needs Enrichment': {
                'avfan_enrichment_status': UNENRICHED_STATUS,
                'avfan_total_videos': 0,
                'javtxt_enrichment_status': UNENRICHED_STATUS,
            },
        }

    def list_actor_enrichment_refresh_times(self):
        return []

    def update_actor_enrichment_refresh_statuses(self, _statuses):
        return None

    def list_expired_actor_enrichment_entities(self, _source_key):
        return []

    def list_actor_movies(self, actor_name):
        raise AssertionError('计划候选不应逐演员查询影片')

    def list_all_actor_movies(self):
        rows = []
        for actor_name in ('Already Done', 'Needs Enrichment'):
            rows.extend(self._actor_movies(actor_name))
        return rows

    @staticmethod
    def _actor_movies(actor_name):
        if actor_name == 'Already Done':
            return [{
                'actor_name': actor_name,
                'code': 'DONE-001',
                'author': 'Already Done',
                'author_raw': 'Already Done',
                'javtxt_enrichment_status': ENRICHED_STATUS,
                'javtxt_movie_id': '1',
                'javtxt_url': 'https://javtxt.top/v/1',
                'release_date': '2025-01-01',
            }]
        return [{
            'actor_name': actor_name,
            'code': 'PENDING-001',
            'author': '',
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'release_date': '2025-01-01',
        }]

    def get_javtxt_actor_cache_by_codes(self, _codes):
        return {}


class EnrichmentPlanCandidateTest(unittest.TestCase):
    def setUp(self):
        self.service = object.__new__(BackendService)
        self.service.db = _ActorPlanDatabase()
        self.service.video_filter_service = SimpleNamespace(load_settings=lambda: {})
        # The old implementation incorrectly used this sorted library page.
        self.service.list_actors = lambda limit=None: {'actors': [{'name': 'Already Done'}]}

    def test_avfan_actor_plan_uses_actual_pending_candidates(self):
        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor', ACTOR_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'actor_name': 'Needs Enrichment'}])

    def test_avfan_actor_plan_prefers_sql_candidate_selector(self):
        calls = []
        self.service.db.list_sql_enrichment_candidates = lambda *args: (
            calls.append(args) or [{'actor_name': 'SQL Candidate'}]
        )

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor', ACTOR_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'actor_name': 'SQL Candidate'}])
        self.assertEqual(calls, [('actor', AVFAN_VIDEO_SOURCE, 1)])

    def test_javtxt_actor_plan_uses_actual_ready_candidates(self):
        records = self.service.db.list_actor_enrichment_records()
        records['Needs Enrichment'].update(
            avfan_enrichment_status=ENRICHED_STATUS,
            avfan_total_videos=1,
        )
        self.service.db.list_actor_enrichment_records = lambda: records

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor', ACTOR_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'actor_name': 'Needs Enrichment', 'code': 'PENDING-001'}])

    @patch('app.backend.service.CodePrefixEnrichmentService')
    def test_avfan_prefix_plan_uses_source_candidate_selector(self, service_class):
        service_class.return_value.list_plan_candidate_prefixes.return_value = ['PENDING']

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'code_prefix', CODE_PREFIX_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'prefix': 'PENDING'}])
        service_class.return_value.list_plan_candidate_prefixes.assert_called_once_with(1)

    def test_avfan_prefix_plan_prefers_sql_candidate_selector(self):
        self.service.db.list_sql_code_prefix_candidates = lambda source_key, limit: [
            {'prefix': 'SQL'}
        ]

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'code_prefix', CODE_PREFIX_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'prefix': 'SQL'}])

    @patch('app.backend.service.CodePrefixJavtxtEnrichmentService')
    def test_javtxt_prefix_plan_uses_source_candidate_selector(self, service_class):
        service_class.return_value.list_plan_candidate_items.return_value = [
            {'prefix': 'READY', 'code': 'READY-001'}
        ]

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'code_prefix', CODE_PREFIX_LIBRARY_TARGET, JAVTXT_VIDEO_SOURCE, 1
        )

        self.assertEqual(candidates, [{'prefix': 'READY', 'code': 'READY-001'}])
        service_class.return_value.list_plan_candidate_items.assert_called_once_with(1)

    @patch('app.backend.service.ActorBaomuEnrichmentService')
    def test_baomu_plan_uses_only_incomplete_binghuo_candidates(self, service_class):
        service_class.return_value.list_actor_library_plan_candidate_names.return_value = ['演员甲']

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor_birthday', 'actor_birthday', 'baomu', 1
        )

        self.assertEqual(candidates, [{'actor_name': '演员甲'}])
        service_class.return_value.list_actor_library_plan_candidate_names.assert_called_once_with(1)

    def test_video_avfan_plan_uses_only_javtxt_supplement_candidates(self):
        self.service.db.list_video_supplement_candidates = lambda limit: [
            {'code': 'SDDE-714', 'supplement_mode': 'actors_only'}
        ]
        self.service.db.list_enrichment_candidates = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('AVFan 视频计划不应读取通用视频候选')
        )

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'video', VIDEO_LIBRARY_TARGET, AVFAN_VIDEO_SOURCE, 1
        )

        self.assertEqual(
            candidates,
            [{'code': 'SDDE-714', 'supplement_mode': 'actors_only'}],
        )


if __name__ == '__main__':
    unittest.main()
