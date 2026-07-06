import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

from app.data.database_handler import VideoDatabase


class MasterpieceLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
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
