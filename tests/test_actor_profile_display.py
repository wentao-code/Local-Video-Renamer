import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.detail import ActorDetailLibrary


class ActorProfileDisplayTest(unittest.TestCase):
    def test_list_actors_shows_unknown_age_when_birthday_is_missing_placeholder(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    ('演员A', '暂无', '126'),
                )
                conn.commit()

            rows = db.list_actors('演员A')

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['birthday'], '暂无')
            self.assertEqual(rows[0]['age'], '未知')

            del rows
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_detail_shows_unknown_age_when_birthday_is_missing_placeholder(self):
        actor_row = {
            'name': '演员B',
            'birthday': '暂无',
            'age': '126',
            'matched': True,
            'actor_id': '',
        }

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [actor_row] if str(search_text or '').strip() in ('', '演员B') else []

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {'tier': 'S'} if entity_name == '演员B' else {}

            def list_videos(self):
                return []

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('演员B')

        self.assertEqual(detail['birthday'], '暂无')
        self.assertEqual(detail['age'], '未知')
        self.assertEqual(detail['ladder_tier'], 'S')


    def test_list_actors_includes_binghuo_status_in_combined_enrichment_text(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    ('婕斿憳C', '1980-01-01', '46'),
                )
                conn.commit()

            db.save_actor_enrichment('婕斿憳C', ENRICHED_STATUS)
            db.save_actor_enrichment('婕斿憳C', FAILED_STATUS, source_key='javtxt')
            db.save_binghuo_actor_profile('婕斿憳C', ENRICHED_STATUS, person_id='1001', birthday='1980-01-01', age='46')

            rows = db.list_actors('婕斿憳C')

            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0]['enrichment_status'],
                f'天陨阁: {ENRICHED_STATUS} | 辛聚阁: {FAILED_STATUS} | 并火: {ENRICHED_STATUS}',
            )

            del rows
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_detail_exposes_binghuo_profile_fields_and_unique_code_counts(self):
        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [
                    {
                        'name': '演员D',
                        'birthday': '1988-08-08',
                        'age': '37',
                        'matched': True,
                        'actor_id': 'avfan-42',
                    }
                ]

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_local_videos_by_actor_name(self, actor_name):
                return [
                    {'code': 'AAA-001', 'title': 'Local 1', 'author': '演员D', 'release_date': '2024-01-01'},
                    {'code': 'BBB-002', 'title': 'Local 2', 'author': '演员D', 'release_date': '2024-01-02'},
                ]

            def list_actor_movies(self, actor_name):
                return [
                    {
                        'code': 'AAA-001',
                        'title': 'Web 1',
                        'author': '演员D',
                        'release_date': '2024-01-01',
                        'javtxt_release_date': '2024-01-01',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'aaa',
                        'javtxt_url': 'https://example.com/aaa',
                        'video_category': '',
                    },
                    {
                        'code': 'CCC-003',
                        'title': 'Web 2',
                        'author': '演员D',
                        'release_date': '2024-01-03',
                        'javtxt_release_date': '2024-01-03',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'ccc',
                        'javtxt_url': 'https://example.com/ccc',
                        'video_category': '',
                    },
                ]

            def get_actor_enrichment_record(self, actor_name):
                return {
                    'actor_id': 'avfan-42',
                    'binghuo_person_id': 'binghuo-77',
                    'binghuo_height': '168',
                    'binghuo_bust': '86',
                    'binghuo_waist': '59',
                    'binghuo_hip': '88',
                    'binghuo_enrichment_status': ENRICHED_STATUS,
                    'avfan_enrichment_status': ENRICHED_STATUS,
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                }

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def list_code_prefix_enrichment_records(self):
                return {
                    'AAA': {'prefix': 'AAA'},
                    'CCC': {'prefix': 'CCC'},
                }

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('演员D')

        self.assertEqual(detail['actor_id'], 'avfan-42')
        self.assertEqual(detail['binghuo_person_id'], 'binghuo-77')
        self.assertEqual(detail['binghuo_height'], '168')
        self.assertEqual(detail['binghuo_bust'], '86')
        self.assertEqual(detail['binghuo_waist'], '59')
        self.assertEqual(detail['binghuo_hip'], '88')
        self.assertEqual(detail['appearance_code_count'], 3)
        self.assertEqual(detail['code_prefix_library_count'], 2)

    def test_actor_detail_counts_unique_visible_eligible_prefixes(self):
        class FakeVideoFilterService:
            @staticmethod
            def filter_video_rows(rows):
                return [
                    dict(row or {})
                    for row in (rows or [])
                    if str((row or {}).get('code', '') or '').strip() not in {'HIDE-001', 'HIDE-002'}
                ]

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [
                    {
                        'name': '演员E',
                        'birthday': '1989-09-09',
                        'age': '36',
                        'matched': True,
                        'actor_id': 'avfan-99',
                    }
                ]

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_local_videos_by_actor_name(self, actor_name):
                return [
                    {'code': 'ROE-001', 'title': 'Local 1', 'author': '演员E', 'release_date': '2024-01-01'},
                    {'code': 'ROE-002', 'title': 'Local 2', 'author': '演员E', 'release_date': '2024-01-02'},
                    {'code': 'HIDE-001', 'title': 'Hidden local', 'author': '演员E', 'release_date': '2024-01-03'},
                ]

            def list_actor_movies(self, actor_name):
                return [
                    {
                        'code': 'ROE-003',
                        'title': 'Web 1',
                        'author': '演员E',
                        'release_date': '2024-01-03',
                        'javtxt_release_date': '2024-01-03',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'roe003',
                        'javtxt_url': 'https://example.com/roe003',
                        'video_category': '',
                    },
                    {
                        'code': 'MIDV-001',
                        'title': 'Web 2',
                        'author': '演员E',
                        'release_date': '2024-01-04',
                        'javtxt_release_date': '2024-01-04',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'midv001',
                        'javtxt_url': 'https://example.com/midv001',
                        'video_category': '',
                    },
                    {
                        'code': 'SSIS-001',
                        'title': 'Old web',
                        'author': '演员E',
                        'release_date': '2019-01-01',
                        'javtxt_release_date': '2019-01-01',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'ssis001',
                        'javtxt_url': 'https://example.com/ssis001',
                        'video_category': '',
                    },
                    {
                        'code': 'HIDE-002',
                        'title': 'Hidden web',
                        'author': '演员E',
                        'release_date': '2024-01-05',
                        'javtxt_release_date': '2024-01-05',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'hide002',
                        'javtxt_url': 'https://example.com/hide002',
                        'video_category': '',
                    },
                ]

            def get_actor_enrichment_record(self, actor_name):
                return {
                    'actor_id': 'avfan-99',
                    'binghuo_enrichment_status': ENRICHED_STATUS,
                    'avfan_enrichment_status': ENRICHED_STATUS,
                    'javtxt_enrichment_status': ENRICHED_STATUS,
                }

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

            def list_code_prefix_enrichment_records(self):
                return {
                    'ROE': {'prefix': 'ROE'},
                    'SSIS': {'prefix': 'SSIS'},
                }

        detail = ActorDetailLibrary(FakeDatabase(), video_filter_service=FakeVideoFilterService()).get_actor_detail('演员E')

        self.assertEqual(detail['appearance_code_count'], 2)
        self.assertEqual(detail['code_prefix_library_count'], 1)


if __name__ == '__main__':
    unittest.main()
