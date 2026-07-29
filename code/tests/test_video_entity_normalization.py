import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase


class VideoEntityNormalizationTest(unittest.TestCase):
    def test_new_database_exposes_only_canonical_video_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')

            self.assertFalse(hasattr(db, 'convert_legacy_tables_to_compatibility_views'))
            self.assertFalse(hasattr(db, 'finalize_legacy_schema'))
            self.assertFalse(hasattr(db, 'list_legacy_actor_movies'))
            self.assertFalse(hasattr(db, 'list_legacy_code_prefix_movies'))

            with db._connect() as conn:
                legacy_rows = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE name IN ('processed_videos', 'actor_movies', 'code_prefix_movies')
                    """
                ).fetchall()

            self.assertEqual(legacy_rows, [])

    def test_canonical_entity_preserves_relation_specific_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Canonical title'},
                actor_relations=[{
                    'actor_name': 'Actor A',
                    'avfan_url': 'https://example.test/actor',
                    'avfan_movie_id': 'actor-001',
                    'page_number': 2,
                }],
                prefix_relations=[{
                    'prefix': 'ABC',
                    'avfan_url': 'https://example.test/prefix',
                    'avfan_movie_id': 'prefix-001',
                    'page_number': 3,
                }],
            )

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute('SELECT code, title FROM video_entities').fetchall(),
                    [('ABC-001', 'Canonical title')],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT video_code, actor_name, avfan_url, avfan_movie_id, page_number '
                        'FROM video_actor_relation_meta'
                    ).fetchall(),
                    [('ABC-001', 'Actor A', 'https://example.test/actor', 'actor-001', 2)],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT video_code, prefix, avfan_url, avfan_movie_id, page_number '
                        'FROM video_prefix_relation_meta'
                    ).fetchall(),
                    [('ABC-001', 'ABC', 'https://example.test/prefix', 'prefix-001', 3)],
                )

    def test_video_library_reads_only_local_canonical_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.upsert_video_entity({'code': 'WEB-001', 'title': 'Web only'})
            db.upsert_video_entity(
                {'code': 'LOC-001', 'title': 'Local'},
                local_record={'storage_location': 'D:/videos/LOC-001.mp4'},
            )

            self.assertEqual([row['code'] for row in db.list_videos()], ['LOC-001'])
            self.assertEqual(db.count_videos(), 1)


if __name__ == '__main__':
    unittest.main()
