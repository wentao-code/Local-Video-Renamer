import unittest

from app.services.detail import (
    ActorDetailLibrary,
    CodePrefixDetailLibrary,
    UNCATEGORIZED_VIDEO_LABEL,
    build_video_category_distribution,
)
from app.services.video import (
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_SINGLE,
)


class VideoCategorySummaryTest(unittest.TestCase):
    def test_build_video_category_distribution_groups_uncategorized_items(self):
        rows = [
            {'video_category': VIDEO_CATEGORY_SINGLE},
            {'video_category': VIDEO_CATEGORY_SINGLE},
            {'video_category': VIDEO_CATEGORY_CO_STAR},
            {'video_category': ''},
            {'video_category': 'unknown'},
            {'video_category': VIDEO_CATEGORY_COLLECTION},
        ]

        distribution = build_video_category_distribution(rows)

        self.assertEqual(
            distribution,
            [
                {'name': VIDEO_CATEGORY_SINGLE, 'video_count': 2},
                {'name': VIDEO_CATEGORY_CO_STAR, 'video_count': 1},
                {'name': VIDEO_CATEGORY_COLLECTION, 'video_count': 1},
                {'name': UNCATEGORIZED_VIDEO_LABEL, 'video_count': 2},
            ],
        )


class ActorDetailVideoCategorySummaryTest(unittest.TestCase):
    def test_actor_detail_returns_video_category_distribution_for_eligible_web_movies(self):
        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [{'name': '演员A', 'birthday': '', 'age': '', 'matched': True, 'actor_id': ''}]

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_videos(self):
                return []

            def list_actor_movies(self, actor_name):
                return [
                    self._build_movie('AAA-001', VIDEO_CATEGORY_SINGLE),
                    self._build_movie('AAA-002', VIDEO_CATEGORY_CO_STAR),
                    self._build_movie('AAA-003', ''),
                ]

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            @staticmethod
            def _build_movie(code, video_category):
                return {
                    'code': code,
                    'title': code,
                    'author': '演员A',
                    'release_date': '2024-01-01',
                    'javtxt_release_date': '2024-01-01',
                    'javtxt_enrichment_status': '已补全',
                    'javtxt_movie_id': code,
                    'javtxt_url': f'https://example.com/{code}',
                    'video_category': video_category,
                }

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('演员A')

        self.assertEqual(
            detail['web_video_category_distribution'],
            [
                {'name': VIDEO_CATEGORY_SINGLE, 'video_count': 1},
                {'name': VIDEO_CATEGORY_CO_STAR, 'video_count': 1},
                {'name': UNCATEGORIZED_VIDEO_LABEL, 'video_count': 1},
            ],
        )


class CodePrefixDetailVideoCategorySummaryTest(unittest.TestCase):
    def test_prefix_detail_returns_video_category_distribution_for_eligible_movies(self):
        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_videos(self):
                return []

            def list_code_prefix_movies(self, prefix):
                return [
                    self._build_movie('NEM-001', VIDEO_CATEGORY_SINGLE),
                    self._build_movie('NEM-002', VIDEO_CATEGORY_COLLECTION),
                    self._build_movie('NEM-003', ''),
                ]

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            @staticmethod
            def _build_movie(code, video_category):
                return {
                    'code': code,
                    'title': code,
                    'author': '演员A',
                    'release_date': '2024-01-01',
                    'javtxt_release_date': '2024-01-01',
                    'javtxt_enrichment_status': '已补全',
                    'javtxt_movie_id': code,
                    'javtxt_url': f'https://example.com/{code}',
                    'video_category': video_category,
                }

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual(
            detail['video_category_distribution'],
            [
                {'name': VIDEO_CATEGORY_SINGLE, 'video_count': 1},
                {'name': VIDEO_CATEGORY_COLLECTION, 'video_count': 1},
                {'name': UNCATEGORIZED_VIDEO_LABEL, 'video_count': 1},
            ],
        )


if __name__ == '__main__':
    unittest.main()
