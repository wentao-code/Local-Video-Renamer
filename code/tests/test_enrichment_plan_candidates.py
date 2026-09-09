import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.backend.service import BackendService
from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE
from app.core.enrichment_sources import SUPPLEMENT_TASK_SOURCE
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

    def test_new_code_prefix_supplement_plan_is_rejected(self):
        self.service.enrichment_task_state = SimpleNamespace(is_running=False)
        self.service.ensure_database_loaded = lambda: None

        with self.assertRaisesRegex(ValueError, '补充任务仅支持视频库'):
            self.service.create_enrichment_batch_plan({
                'target_type': CODE_PREFIX_LIBRARY_TARGET,
                'task_kind': 'code_prefix',
                'source_key': SUPPLEMENT_TASK_SOURCE,
                'batch_limit': 1,
                'batch_count_limit': 1,
            })

    def test_video_supplement_plan_only_builds_the_first_batch(self):
        self.service.enrichment_task_state = SimpleNamespace(is_running=False)
        self.service.ensure_database_loaded = lambda: None
        requested_limits = []
        created = []

        class _PlanDatabase:
            @staticmethod
            def create_enrichment_batch_plan(*args, **kwargs):
                created.append((args, kwargs))
                return {'plan_id': 'video-plan'}

        self.service.db = _PlanDatabase()
        self.service._build_enrichment_batch_plan_candidates = lambda *_args: (
            requested_limits.append(_args[-1]) or [{'code': 'AAA-001'}]
        )

        self.service.create_enrichment_batch_plan({
            'target_type': VIDEO_LIBRARY_TARGET,
            'task_kind': 'video',
            'source_key': SUPPLEMENT_TASK_SOURCE,
            'batch_limit': 25,
            'batch_count_limit': 300,
        })

        self.assertEqual(requested_limits, [25])
        self.assertEqual(created[0][1]['batch_count_limit'], 300)

    def test_video_supplement_plan_appends_next_batch_on_demand(self):
        appended = []

        class _PlanDatabase:
            @staticmethod
            def get_enrichment_batch_plan_progress(*_args):
                return {
                    'pending_count': 0,
                    'running_count': 0,
                    'retryable_failed_count': 0,
                    'completed_batch_count': 1,
                    'batch_count_limit': 300,
                    'batch_limit': 25,
                }

            @staticmethod
            def append_enrichment_batch_plan_candidates(*args):
                appended.append(args)
                return 25

        self.service.db = _PlanDatabase()
        self.service._build_enrichment_batch_plan_candidates = lambda *_args: [
            {'code': 'AAA-002'}
        ]

        self.service._ensure_enrichment_batch_plan_batch_candidates(
            'video-plan',
            'video',
            VIDEO_LIBRARY_TARGET,
            SUPPLEMENT_TASK_SOURCE,
            batch_mode=True,
        )

        self.assertEqual(appended[0][0:2], ('video-plan', 'video'))
        self.assertEqual(appended[0][2], [{'code': 'AAA-002'}])

    def test_missing_selected_plan_is_created_from_current_candidates(self):
        with self.assertRaisesRegex(ValueError, '补充任务仅支持视频库'):
            self.service._find_or_create_enrichment_plan(
                'actor', ACTOR_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE, 15
            )

    def test_actor_supplement_plan_scans_past_filtered_sql_prefix(self):
        class _SupplementDatabase:
            def __init__(self):
                self.requested_limits = []

            @staticmethod
            def get_data_source_versions(_keys):
                return {'actor_library': 1}

            @staticmethod
            def load_enrichment_candidate_index(*_args):
                return None

            def list_sql_supplement_candidates(self, _target_kind, limit):
                self.requested_limits.append(limit)
                filtered = [
                    {
                        'code': f'AAA-{index:03d}',
                        'supplement_enrichment_status': UNENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'movie-id',
                        'author': '已有演员',
                    }
                    for index in range(20)
                ]
                candidate = {
                    'actor_name': '待补全演员',
                    'code': 'BBB-001',
                    'supplement_enrichment_status': UNENRICHED_STATUS,
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                    'javtxt_movie_id': 'movie-id',
                    'author': '',
                }
                return filtered if limit <= 20 else filtered + [candidate]

            @staticmethod
            def replace_enrichment_candidate_index(*_args, **_kwargs):
                return 1

        database = _SupplementDatabase()
        self.service.db = database
        self.service.video_filter_service = SimpleNamespace(
            load_settings=lambda: {},
            load_ruleset=lambda **_kwargs: None,
        )

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor', ACTOR_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE, 1
        )

        self.assertEqual([candidate['code'] for candidate in candidates], ['BBB-001'])
        self.assertEqual(database.requested_limits, [20, 40])

    def test_actor_supplement_plan_scans_for_requested_unique_video_codes(self):
        class _IndexedSupplementDatabase:
            @staticmethod
            def get_data_source_versions(_keys):
                return {'actor_library': 1}

            @staticmethod
            def load_enrichment_candidate_index(*_args):
                return None

            @staticmethod
            def list_sql_supplement_candidates(_target_kind, _limit):
                return [
                    {
                        'actor_name': '演员甲',
                        'code': 'DUP-001',
                        'supplement_enrichment_status': UNENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'movie-1',
                        'author': '',
                    },
                    {
                        'actor_name': '演员乙',
                        'code': 'DUP-001',
                        'supplement_enrichment_status': UNENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'movie-2',
                        'author': '',
                    },
                    {
                        'actor_name': '演员丙',
                        'code': 'DUP-002',
                        'supplement_enrichment_status': UNENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'movie-3',
                        'author': '',
                    },
                    {
                        'actor_name': '演员丁',
                        'code': 'DUP-003',
                        'supplement_enrichment_status': UNENRICHED_STATUS,
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'movie-4',
                        'author': '',
                    },
                ]

            @staticmethod
            def replace_enrichment_candidate_index(*_args, **_kwargs):
                return 3

        self.service.db = _IndexedSupplementDatabase()

        candidates = self.service._build_enrichment_batch_plan_candidates(
            'actor', ACTOR_LIBRARY_TARGET, SUPPLEMENT_TASK_SOURCE, 3
        )

        self.assertEqual(
            [candidate['code'] for candidate in candidates],
            ['DUP-001', 'DUP-002', 'DUP-003'],
        )


if __name__ == '__main__':
    unittest.main()
