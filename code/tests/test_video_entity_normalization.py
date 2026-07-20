import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase


class VideoEntityNormalizationTest(unittest.TestCase):
    def test_legacy_views_route_insert_update_delete_to_canonical_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, author, avfan_url, page_number,
                        javtxt_enrichment_status, video_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    ('演员A', 'ABC-001', 'View title', '演员A', 'https://avfan/a', 2, 'ENRICHED', '单体作品'),
                )
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, avfan_url, page_number
                    ) VALUES (?, ?, ?, ?, ?)
                    ''',
                    ('ABC', 'ABC-001', 'View title', 'https://avfan/prefix', 3),
                )
                conn.execute(
                    'UPDATE actor_movies SET title = ? WHERE actor_name = ? AND code = ?',
                    ('Updated title', '演员A', 'ABC-001'),
                )
                conn.execute(
                    'DELETE FROM actor_movies WHERE actor_name = ? AND code = ?',
                    ('演员A', 'ABC-001'),
                )
                conn.commit()

                self.assertEqual(
                    conn.execute('SELECT code, title FROM video_entities').fetchall(),
                    [('ABC-001', 'Updated title')],
                )
                self.assertEqual(
                    conn.execute('SELECT * FROM video_actor_relations').fetchall(),
                    [],
                )
                self.assertEqual(
                    conn.execute('SELECT video_code, prefix FROM video_code_prefix_relations').fetchall(),
                    [('ABC-001', 'ABC')],
                )

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT type FROM sqlite_master WHERE name = 'processed_videos'"
                    ).fetchone(),
                    ('view',),
                )

    def test_library_refresh_methods_work_after_view_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()

            db.replace_actor_movies(
                '演员A',
                [{
                    'code': 'XYZ-001',
                    'title': 'Actor movie',
                    'author': '演员A',
                    'release_date': '2024-01-01',
                    'avfan_url': 'https://avfan/actor',
                    'javtxt_enrichment_status': 'ENRICHED',
                    'javtxt_movie_id': 'xyz-001',
                }],
            )
            db.replace_code_prefix_movies(
                'XYZ',
                [{
                    'code': 'XYZ-001',
                    'title': 'Prefix movie',
                    'author': '演员A',
                    'release_date': '2024-01-01',
                    'avfan_url': 'https://avfan/prefix',
                    'javtxt_enrichment_status': 'ENRICHED',
                    'javtxt_movie_id': 'xyz-001',
                }],
            )

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT code FROM video_entities WHERE code = ?', ('XYZ-001',)
                    ).fetchone(),
                    ('XYZ-001',),
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT actor_name FROM video_actor_relations WHERE video_code = ?',
                        ('XYZ-001',),
                    ).fetchall(),
                    [('演员A',)],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT prefix FROM video_code_prefix_relations WHERE video_code = ?',
                        ('XYZ-001',),
                    ).fetchall(),
                    [('XYZ',)],
                )

    def test_canonical_upsert_preserves_relation_specific_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.upsert_video_entity(
                {
                    'code': 'ABC-001',
                    'title': 'Canonical title',
                    'release_date': '2024-01-01',
                    'video_category': '单体作品',
                },
                actor_relations=[
                    {
                        'actor_name': '演员A',
                        'avfan_url': 'https://avfan.example/a',
                        'avfan_movie_id': 'a-001',
                        'page_number': 2,
                    },
                    {
                        'actor_name': '演员B',
                        'avfan_url': 'https://avfan.example/b',
                        'avfan_movie_id': 'b-001',
                        'page_number': 3,
                    },
                ],
                prefix_relations=[
                    {
                        'prefix': 'ABC',
                        'avfan_url': 'https://avfan.example/prefix',
                        'avfan_movie_id': 'p-001',
                        'page_number': 4,
                    },
                ],
            )

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT code, title FROM video_entities WHERE code = ?',
                        ('ABC-001',),
                    ).fetchone(),
                    ('ABC-001', 'Canonical title'),
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT actor_name, avfan_url, avfan_movie_id, page_number '
                        'FROM video_actor_relation_meta ORDER BY actor_name'
                    ).fetchall(),
                    [
                        ('演员A', 'https://avfan.example/a', 'a-001', 2),
                        ('演员B', 'https://avfan.example/b', 'b-001', 3),
                    ],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT prefix, avfan_url, avfan_movie_id, page_number '
                        'FROM video_prefix_relation_meta'
                    ).fetchall(),
                    [('ABC', 'https://avfan.example/prefix', 'p-001', 4)],
                )

    def test_migration_merges_video_rows_and_preserves_relationships(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO processed_videos (code, title, release_date, avfan_movie_id)
                    VALUES (?, ?, ?, ?)
                    ''',
                    ('ABC-001', 'Canonical title', '2024-01-01', 'av-001'),
                )
                conn.executemany(
                    '''
                    INSERT INTO actor_movies (actor_name, code, title, avfan_url)
                    VALUES (?, ?, ?, ?)
                    ''',
                    [
                        ('演员A', 'ABC-001', '', 'https://avfan.example/abc-001'),
                        ('演员B', 'ABC-001', 'Actor title', ''),
                    ],
                )
                conn.execute(
                    '''
                    INSERT INTO code_prefix_movies (prefix, code, title, avfan_url)
                    VALUES (?, ?, ?, ?)
                    ''',
                    ('ABC', 'ABC-001', '', 'https://avfan.example/abc-001'),
                )
                conn.commit()

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                entity_rows = conn.execute(
                    'SELECT code, title, avfan_movie_id, avfan_url FROM video_entities'
                ).fetchall()
                actor_relations = conn.execute(
                    'SELECT video_code, actor_name FROM video_actor_relations ORDER BY actor_name'
                ).fetchall()
                prefix_relations = conn.execute(
                    'SELECT video_code, prefix FROM video_code_prefix_relations'
                ).fetchall()

        self.assertEqual(entity_rows, [('ABC-001', 'Canonical title', 'av-001', 'https://avfan.example/abc-001')])
        self.assertEqual(actor_relations, [('ABC-001', '演员A'), ('ABC-001', '演员B')])
        self.assertEqual(prefix_relations, [('ABC-001', 'ABC')])

    def test_normalized_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actor_movies (actor_name, code, avfan_url) VALUES (?, ?, ?)",
                    ('演员A', 'XYZ-001', 'https://avfan.example/xyz-001'),
                )
                conn.commit()

            VideoDatabase(db_path)
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                counts = conn.execute(
                    '''
                    SELECT
                        (SELECT COUNT(*) FROM video_entities WHERE code = 'XYZ-001'),
                        (SELECT COUNT(*) FROM video_actor_relations WHERE video_code = 'XYZ-001'),
                        (SELECT COUNT(*) FROM video_code_prefix_relations WHERE video_code = 'XYZ-001')
                    ''',
                ).fetchone()

        self.assertEqual(counts, (1, 1, 0))


if __name__ == '__main__':
    unittest.main()
