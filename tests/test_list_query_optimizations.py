import unittest

from app.backend.service import BackendService
from app.services.actor_detail_library import ActorDetailLibrary
from app.services.code_prefix_detail_library import CodePrefixDetailLibrary


class BackendVideoListOptimizationTest(unittest.TestCase):
    def _build_service(self, database, filter_service=None, ladder_service=None):
        service = BackendService.__new__(BackendService)
        service.db = database
        service.video_filter_service = filter_service or _PassThroughFilterService()
        service.video_ladder_tag_service = ladder_service or _PassThroughLadderTagService()
        service.ensure_database_loaded = lambda: None
        return service

    def test_list_videos_without_search_skips_ladder_enrich(self):
        class FakeDatabase:
            def list_videos(self, search_text=''):
                if search_text:
                    raise AssertionError('unexpected searched query')
                return [{'code': 'AAA-001', 'title': 'Video A', 'author': 'Actor A'}]

        class FakeLadderService(_PassThroughLadderTagService):
            def enrich_video_rows(self, rows, medal_maps=None):
                raise AssertionError('no-search listing should not enrich all rows')

        service = self._build_service(FakeDatabase(), ladder_service=FakeLadderService())

        result = BackendService.list_videos(service)

        self.assertEqual([row['code'] for row in result['videos']], ['AAA-001'])

    def test_list_videos_search_expands_only_ladder_matched_candidates(self):
        class FakeDatabase:
            def __init__(self):
                self.actor_queries = []
                self.prefix_queries = []

            def list_videos(self, search_text=''):
                if search_text != 'Top Medal':
                    raise AssertionError(f'unexpected search text: {search_text}')
                return []

            def list_local_videos_by_actor_names(self, actor_names):
                self.actor_queries.append(list(actor_names))
                return [{'code': 'ACT-001', 'title': 'Actor Medal Video', 'author': 'Actor Medal'}]

            def list_local_videos_by_prefixes(self, prefixes):
                self.prefix_queries.append(list(prefixes))
                return [{'code': 'LAD-001', 'title': 'Prefix Medal Video', 'author': 'Other Actor'}]

        class FakeLadderService(_PassThroughLadderTagService):
            def load_medal_maps(self):
                return {
                    'actor_medal_map': {'Actor Medal': ['Top Medal']},
                    'prefix_medal_map': {'LAD': ['Top Medal']},
                }

            def enrich_video_rows(self, rows, medal_maps=None):
                enriched_rows = []
                for row in rows:
                    current = dict(row)
                    current['ladder_tag_text'] = 'Top Medal' if current['code'] in {'ACT-001', 'LAD-001'} else ''
                    enriched_rows.append(current)
                return enriched_rows

            def filter_video_rows(self, rows, search_text=''):
                normalized_search = str(search_text or '').strip().lower()
                if not normalized_search:
                    return list(rows or [])
                return [
                    dict(row or {})
                    for row in (rows or [])
                    if normalized_search in ' '.join(
                        [
                            str((row or {}).get('code', '') or ''),
                            str((row or {}).get('title', '') or ''),
                            str((row or {}).get('author', '') or ''),
                            str((row or {}).get('ladder_tag_text', '') or ''),
                        ]
                    ).lower()
                ]

        database = FakeDatabase()
        service = self._build_service(database, ladder_service=FakeLadderService())

        result = BackendService.list_videos(service, 'Top Medal')

        self.assertEqual([row['code'] for row in result['videos']], ['ACT-001', 'LAD-001'])
        self.assertEqual(database.actor_queries, [['Actor Medal']])
        self.assertEqual(database.prefix_queries, [['LAD']])


class TargetedDetailQueryTest(unittest.TestCase):
    def test_actor_detail_prefers_targeted_local_query(self):
        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [{'name': 'Actor A', 'birthday': '', 'age': '', 'matched': True, 'actor_id': ''}]

            def list_local_videos_by_actor_name(self, actor_name):
                self.actor_name = actor_name
                return [{'code': 'AAA-001', 'title': 'Local', 'author': 'Actor A'}]

            def list_videos(self):
                raise AssertionError('actor detail should not scan the full video library')

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('Actor A')

        self.assertEqual([row['code'] for row in detail['local_videos']], ['AAA-001'])

    def test_code_prefix_detail_prefers_targeted_local_query(self):
        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def list_local_videos_by_prefix(self, prefix):
                self.prefix = prefix
                return [{'code': 'NEM-001', 'title': 'Local', 'author': 'Actor A'}]

            def list_videos(self):
                raise AssertionError('prefix detail should not scan the full video library')

            def list_code_prefix_movies(self, prefix):
                return []

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual([row['code'] for row in detail['local_videos']], ['NEM-001'])


class _PassThroughFilterService:
    @staticmethod
    def filter_video_rows(rows, settings=None):
        return list(rows or [])


class _PassThroughLadderTagService:
    @staticmethod
    def load_medal_maps():
        return {
            'actor_medal_map': {},
            'prefix_medal_map': {},
        }

    @staticmethod
    def enrich_video_rows(rows, medal_maps=None):
        return list(rows or [])

    @staticmethod
    def filter_video_rows(rows, search_text=''):
        return list(rows or [])


if __name__ == '__main__':
    unittest.main()
