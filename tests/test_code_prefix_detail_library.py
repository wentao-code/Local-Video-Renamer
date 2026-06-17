import unittest

from app.services.code_prefix_detail_library import CodePrefixDetailLibrary


class CodePrefixDetailLibraryTest(unittest.TestCase):
    def test_prefix_detail_includes_local_videos_and_local_count(self):
        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def list_videos(self):
                return [
                    {'code': 'NEM-001', 'title': 'Local 1', 'release_date': '2024-01-01', 'author': 'Actor A'},
                    {'code': 'NEM-002', 'title': 'Local 2', 'release_date': '2024-02-01', 'author': 'Actor B'},
                    {'code': 'ABC-001', 'title': 'Other', 'release_date': '2024-03-01', 'author': 'Actor C'},
                ]

            def list_code_prefix_movies(self, prefix):
                return [
                    {
                        'code': 'NEM-001',
                        'title': 'Web 1',
                        'release_date': '2024-01-01',
                        'author': 'Actor A',
                        'javtxt_release_date': '2024-01-01',
                        'javtxt_enrichment_status': '已补全',
                        'javtxt_movie_id': '1',
                        'javtxt_url': 'https://example.com/1',
                    }
                ]

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual(detail['video_count'], 2)
        self.assertEqual([row['code'] for row in detail['local_videos']], ['NEM-001', 'NEM-002'])
        self.assertEqual([row['code'] for row in detail['movies']], ['NEM-001'])


if __name__ == '__main__':
    unittest.main()
