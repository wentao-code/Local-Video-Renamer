import sqlite3
import shutil
import tempfile
import unittest
import os
from pathlib import Path

from app.data.database_handler import VideoDatabase


class MasterpieceLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
        self.original_avfan_base_url = os.environ.get('AVFAN_BASE_URL')
        os.environ['AVFAN_BASE_URL'] = 'https://avfan.example'
        self.db = VideoDatabase(self.db_path)
        self._insert_video(
            code='PFSA-001',
            title='Perfect First Scene',
            author='Alice',
            javtxt_url='https://example.com/pfsa-001',
            javtxt_tags='剧情,新人',
            supplement_status='pending',
        )

    def tearDown(self):
        self.db = None
        if self.original_avfan_base_url is None:
            os.environ.pop('AVFAN_BASE_URL', None)
        else:
            os.environ['AVFAN_BASE_URL'] = self.original_avfan_base_url
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_video(
        self,
        code,
        title,
        author,
        javtxt_url='',
        javtxt_tags='',
        supplement_status='',
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    duration,
                    size,
                    storage_location,
                    avfan_movie_id,
                    release_date,
                    maker,
                    publisher,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_tags,
                    javtxt_release_date,
                    video_category,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    supplement_enrichment_status,
                    supplement_enrichment_error,
                    supplement_enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    code,
                    title,
                    author,
                    '01:30:00',
                    '3.20',
                    r'D:\videos',
                    'avfan-001',
                    '2024-05-01',
                    'Maker A',
                    'Publisher A',
                    'javtxt-001',
                    javtxt_url,
                    title,
                    author,
                    javtxt_tags,
                    '2024-05-02',
                    '单体',
                    '已补全',
                    '已补全',
                    supplement_status,
                    '',
                    '2026-07-06 00:00:00',
                ),
            )
            conn.commit()

    def _replace_code_prefix_movies(self, prefix, movies):
        self.db.replace_code_prefix_movies(prefix, movies)

    def _replace_actor_movies(self, actor_name, movies):
        self.db.replace_actor_movies(actor_name, movies)

    def test_add_masterpiece_entry_lists_video_and_normalizes_medals(self):
        entry = self.db.add_masterpiece_entry('pfsa-001')
        self.assertEqual(entry['code'], 'PFSA-001')
        self.assertEqual(entry['title'], 'Perfect First Scene')
        self.assertEqual(entry['author'], 'Alice')
        self.assertEqual(entry['medal'], '')
        self.assertEqual(entry['medals'], [])

        updated = self.db.update_masterpiece_entry_medal('PFSA-001', '年度新人, 白金常青\n年度新人')
        self.assertEqual(updated['medal'], '年度新人\n白金常青')
        self.assertEqual(updated['medals'], ['年度新人', '白金常青'])

        rows = self.db.list_masterpiece_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], 'PFSA-001')
        self.assertEqual(rows[0]['medal'], '年度新人\n白金常青')
        self.assertEqual(rows[0]['medals'], ['年度新人', '白金常青'])

    def test_add_masterpiece_entry_requires_existing_video(self):
        with self.assertRaises(ValueError):
            self.db.add_masterpiece_entry('MISS-001')

    def test_add_masterpiece_entry_accepts_actor_library_only_match(self):
        self._replace_actor_movies(
            'Actor Only',
            [
                {
                    'code': 'act-002',
                    'title': 'Actor Library Story',
                    'author': 'Actor Only',
                    'release_date': '2024-04-02',
                    'javtxt_url': 'https://javtxt.example/act-002',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('act002')
        detail = self.db.get_masterpiece_detail_record('ACT-002')

        self.assertEqual(entry['code'], 'ACT-002')
        self.assertEqual(entry['title'], 'Actor Library Story')
        self.assertEqual(entry['author'], 'Actor Only')
        self.assertEqual(entry['primary_source'], 'actor_library')
        self.assertEqual(detail['primary_source'], 'actor_library')
        self.assertEqual(len(detail['references']), 1)
        self.assertEqual(detail['references'][0]['reference_source'], 'actor_library')
        self.assertEqual(detail['references'][0]['reference_key'], 'Actor Only')

    def test_add_masterpiece_entry_accepts_code_prefix_library_only_match(self):
        self._replace_code_prefix_movies(
            'IPX',
            [
                {
                    'code': 'ipx001',
                    'title': 'Prefix Library Story',
                    'author': 'Prefix Actor',
                    'release_date': '2024-03-01',
                    'avfan_url': 'https://avfan.example/movies/prefix-001',
                    'javtxt_url': 'https://javtxt.example/ipx-001',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('IPX-001')
        detail = self.db.get_masterpiece_detail_record('IPX-001')

        self.assertEqual(entry['code'], 'IPX-001')
        self.assertEqual(entry['title'], 'Prefix Library Story')
        self.assertEqual(entry['author'], 'Prefix Actor')
        self.assertEqual(entry['primary_source'], 'code_prefix_library')
        self.assertEqual(detail['primary_detail_url'], 'https://avfan.example/movies/prefix-001')
        self.assertEqual(len(detail['references']), 1)
        self.assertEqual(detail['references'][0]['reference_source'], 'code_prefix_library')
        self.assertEqual(detail['references'][0]['reference_key'], 'IPX')

    def test_add_masterpiece_entry_persists_all_library_references_and_primary_priority(self):
        self._replace_code_prefix_movies(
            'PFSA',
            [
                {
                    'code': 'PFSA001',
                    'title': 'Prefix Copy',
                    'author': 'Prefix Actor',
                    'release_date': '2024-04-01',
                    'avfan_url': 'https://avfan.example/movies/prefix-copy',
                }
            ],
        )
        self._replace_actor_movies(
            'Actor A',
            [
                {
                    'code': 'PFSA-001',
                    'title': 'Actor Copy',
                    'author': 'Actor Copy',
                    'release_date': '2024-04-03',
                    'javtxt_url': 'https://javtxt.example/pfsa-001',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('PFSA001')
        rows = self.db.list_masterpiece_entries()
        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual(entry['primary_source'], 'video_library')
        self.assertEqual(entry['primary_detail_url'], 'https://avfan.example/movies/avfan-001')
        self.assertEqual(rows[0]['title'], 'Perfect First Scene')
        self.assertEqual(rows[0]['author'], 'Alice')
        self.assertEqual(rows[0]['primary_source'], 'video_library')
        self.assertEqual(detail['display_title'], 'Perfect First Scene')
        self.assertEqual(detail['display_author'], 'Alice')
        self.assertEqual(detail['primary_source'], 'video_library')
        self.assertEqual(detail['primary_detail_url'], 'https://avfan.example/movies/avfan-001')
        self.assertEqual(
            [row['reference_source'] for row in detail['references']],
            ['video_library', 'code_prefix_library', 'actor_library'],
        )

    def test_get_video_detail_record_returns_full_video_fields(self):
        detail = self.db.get_video_detail_record('pfsa-001')
        self.assertEqual(detail['code'], 'PFSA-001')
        self.assertEqual(detail['title'], 'Perfect First Scene')
        self.assertEqual(detail['author'], 'Alice')
        self.assertEqual(detail['javtxt_url'], 'https://example.com/pfsa-001')
        self.assertEqual(detail['javtxt_tags'], '剧情,新人')
        self.assertEqual(detail['supplement_enrichment_status'], 'pending')
        self.assertEqual(detail['maker'], 'Maker A')
        self.assertEqual(detail['publisher'], 'Publisher A')


if __name__ == '__main__':
    unittest.main()
