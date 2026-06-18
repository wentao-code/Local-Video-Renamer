import unittest
from datetime import date, timedelta

from app.services.detail import ActorDetailLibrary, CodePrefixDetailLibrary
from app.services.video import (
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_SINGLE,
)


class ActorDetailUpdateStatusTest(unittest.TestCase):
    def test_actor_detail_marks_active_when_recent_single_or_co_star_exists(self):
        recent_date = (date.today() - timedelta(days=120)).isoformat()

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [{'name': 'Actor A', 'birthday': '', 'age': '', 'matched': True, 'actor_id': ''}]

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_local_videos_by_actor_name(self, actor_name):
                return [
                    {
                        'code': 'AAA-001',
                        'title': 'Recent Single',
                        'author': 'Actor A',
                        'release_date': recent_date,
                        'video_category': VIDEO_CATEGORY_SINGLE,
                    }
                ]

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('Actor A')

        self.assertEqual(detail['update_status'], 'active')

    def test_actor_detail_marks_suspect_when_latest_tracked_video_is_within_512_days(self):
        stale_date = (date.today() - timedelta(days=400)).isoformat()

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [{'name': 'Actor B', 'birthday': '', 'age': '', 'matched': True, 'actor_id': ''}]

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_local_videos_by_actor_name(self, actor_name):
                return []

            def list_actor_movies(self, actor_name):
                return [
                    {
                        'code': 'BBB-001',
                        'title': 'Web Co-Star',
                        'author': 'Actor B',
                        'release_date': stale_date,
                        'javtxt_release_date': stale_date,
                        'javtxt_enrichment_status': '已补全',
                        'javtxt_movie_id': '1',
                        'javtxt_url': 'https://example.com/1',
                        'video_category': VIDEO_CATEGORY_CO_STAR,
                    }
                ]

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('Actor B')

        self.assertEqual(detail['update_status'], 'suspect')


class CodePrefixDetailUpdateStatusTest(unittest.TestCase):
    def test_prefix_detail_marks_inactive_when_recent_collection_is_only_recent_video(self):
        old_single_date = (date.today() - timedelta(days=700)).isoformat()
        recent_collection_date = (date.today() - timedelta(days=30)).isoformat()

        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_local_videos_by_prefix(self, prefix):
                return [
                    {
                        'code': 'NEM-001',
                        'title': 'Old Single',
                        'author': 'Actor A',
                        'release_date': old_single_date,
                        'video_category': VIDEO_CATEGORY_SINGLE,
                    },
                    {
                        'code': 'NEM-777',
                        'title': 'Recent Collection',
                        'author': 'Actor A',
                        'release_date': recent_collection_date,
                        'video_category': VIDEO_CATEGORY_COLLECTION,
                    },
                ]

            def list_code_prefix_movies(self, prefix):
                return []

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual(detail['update_status'], 'inactive')


if __name__ == '__main__':
    unittest.main()
