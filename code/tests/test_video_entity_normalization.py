import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase


class VideoEntityNormalizationTest(unittest.TestCase):
    def test_actor_movies_compatibility_view_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.replace_code_prefix_movies(
                'ABC',
                [{
                    'code': 'ABC-001',
                    'title': 'View title',
                    'avfan_url': 'https://avfan/prefix',
                    'page_number': 3,
                }],
            )

            with closing(sqlite3.connect(db_path)) as conn:
                for statement in (
                    "INSERT INTO actor_movies (actor_name, code) VALUES ('演员A', 'ABC-001')",
                    "UPDATE actor_movies SET title = 'Updated title' WHERE actor_name = '演员A' AND code = 'ABC-001'",
                    "DELETE FROM actor_movies WHERE actor_name = '演员A' AND code = 'ABC-001'",
                ):
                    with self.assertRaises(sqlite3.OperationalError):
                        conn.execute(statement)
                self.assertEqual(
                    conn.execute('SELECT video_code, prefix FROM video_code_prefix_relations').fetchall(),
                    [('ABC-001', 'ABC')],
                )

    def test_code_prefix_movies_compatibility_view_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()

            with closing(sqlite3.connect(db_path)) as conn:
                for statement in (
                    "INSERT INTO code_prefix_movies (prefix, code) VALUES ('ABC', 'ABC-001')",
                    "UPDATE code_prefix_movies SET title = 'Updated title' WHERE prefix = 'ABC' AND code = 'ABC-001'",
                    "DELETE FROM code_prefix_movies WHERE prefix = 'ABC' AND code = 'ABC-001'",
                ):
                    with self.assertRaises(sqlite3.OperationalError):
                        conn.execute(statement)

            db.replace_code_prefix_movies(
                'ABC',
                [{
                    'code': 'ABC-001',
                    'title': 'Prefix title',
                    'release_date': '2024-01-01',
                    'avfan_url': 'https://avfan/prefix',
                    'javtxt_url': 'https://javtxt/prefix',
                    'page_number': 3,
                    'javtxt_enrichment_status': 'ENRICHED',
                    'javtxt_movie_id': 'abc-001',
                }],
            )
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute('SELECT code, title FROM video_entities').fetchall(),
                    [('ABC-001', 'Prefix title')],
                )
                self.assertEqual(
                    conn.execute('SELECT video_code, prefix FROM video_code_prefix_relations').fetchall(),
                    [('ABC-001', 'ABC')],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT avfan_url, avfan_movie_id, page_number FROM video_prefix_relation_meta '
                        'WHERE video_code = ? AND prefix = ?',
                        ('ABC-001', 'ABC'),
                    ).fetchone(),
                    ('https://avfan/prefix', 'abc-001', 3),
                )

    def test_processed_videos_compatibility_view_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()

            with closing(sqlite3.connect(db_path)) as conn:
                for statement in (
                    "INSERT INTO processed_videos (code, title) VALUES ('ABC-001', 'Title')",
                    "UPDATE processed_videos SET title = 'Updated' WHERE code = 'ABC-001'",
                    "DELETE FROM processed_videos WHERE code = 'ABC-001'",
                ):
                    with self.assertRaises(sqlite3.OperationalError):
                        conn.execute(statement)

            db.import_local_videos([{
                'code': 'ABC-001',
                'title': 'Local title',
                'storage_location': 'D:/videos/ABC-001.mp4',
            }])
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT code, title FROM video_entities WHERE code = ?',
                        ('ABC-001',),
                    ).fetchone(),
                    ('ABC-001', ''),
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT code, storage_location FROM local_video_records WHERE code = ?',
                        ('ABC-001',),
                    ).fetchone(),
                    ('ABC-001', 'D:/videos/ABC-001.mp4'),
                )

            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT type FROM sqlite_master WHERE name = 'processed_videos'"
                    ).fetchone(),
                    ('view',),
                )

    def test_finalize_legacy_schema_removes_compatibility_objects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.upsert_video_entity({'code': 'ABC-001', 'title': 'Canonical'})

            db.finalize_legacy_schema()

            with closing(sqlite3.connect(db_path)) as conn:
                for name in ('processed_videos', 'actor_movies', 'code_prefix_movies'):
                    self.assertIsNone(
                        conn.execute(
                            'SELECT 1 FROM sqlite_master WHERE name = ?',
                            (name,),
                        ).fetchone()
                    )
                self.assertEqual(
                    conn.execute(
                        'SELECT title FROM video_entities WHERE code = ?',
                        ('ABC-001',),
                    ).fetchone(),
                    ('Canonical',),
                )

    def test_video_library_core_reads_use_canonical_tables_without_view(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Canonical local video', 'author': 'Actor'},
                local_record={
                    'duration': '01:00:00',
                    'size': '1.2',
                    'storage_location': 'Local folder',
                },
            )

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute('DROP VIEW processed_videos')
                conn.commit()

            rows = db.list_videos(search_text='Canonical', sort_field='title')
            self.assertEqual([row['code'] for row in rows], ['ABC-001'])
            self.assertEqual(db.count_videos(search_text='Canonical'), 1)

    def test_video_enrichment_reads_use_canonical_tables_without_view(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.upsert_video_entity({
                'code': 'ABC-001',
                'title': 'Canonical video',
                'javtxt_title': 'Canonical video',
                'release_date': '2024-01-01',
                'javtxt_release_date': '2024-01-01',
                'javtxt_actors': '演员A',
                'javtxt_actors_raw': '演员A',
                'javtxt_enrichment_status': 'ENRICHED',
                'javtxt_movie_id': 'abc-001',
                'javtxt_url': 'https://javtxt/abc-001',
            })

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute('DROP VIEW processed_videos')
                conn.commit()

            summary = db.get_video_enrichment_summary('javtxt')
            self.assertEqual(summary['total_count'], 1)
            self.assertEqual(summary['success_count'], 1)
            self.assertEqual(db.get_javtxt_actor_cache_by_codes(['ABC-001'])['ABC-001']['javtxt_actors'], '演员A')
            with db._connect() as conn:
                self.assertTrue(db._is_processed_video_javtxt_eligible(conn.cursor(), 'ABC-001'))

    def test_actor_and_prefix_reads_use_canonical_relations_without_views(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.replace_actor_movies('演员A', [{
                'code': 'ABC-001',
                'title': 'Actor title',
                'author': '演员A',
                'release_date': '2024-01-01',
                'avfan_url': 'https://avfan/actor',
                'page_number': 4,
            }])
            db.replace_code_prefix_movies('ABC', [{
                'code': 'ABC-001',
                'title': 'Prefix title',
                'author': '演员A',
                'release_date': '2024-01-01',
                'avfan_url': 'https://avfan/prefix',
                'page_number': 7,
            }])

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute('DROP VIEW actor_movies')
                conn.execute('DROP VIEW code_prefix_movies')
                conn.commit()

            actor_rows = db.list_actor_movies('演员A')
            prefix_rows = db.list_code_prefix_movies('ABC')
            self.assertEqual(actor_rows[0]['avfan_url'], 'https://avfan/actor')
            self.assertEqual(actor_rows[0]['page_number'], 4)
            self.assertEqual(prefix_rows[0]['avfan_url'], 'https://avfan/prefix')
            self.assertEqual(prefix_rows[0]['page_number'], 7)

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
                        'SELECT avfan_url, avfan_movie_id FROM video_actor_relation_meta WHERE video_code = ? AND actor_name = ?',
                        ('XYZ-001', '演员A'),
                    ).fetchone(),
                    ('https://avfan/actor', 'xyz-001'),
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT prefix FROM video_code_prefix_relations WHERE video_code = ?',
                        ('XYZ-001',),
                    ).fetchall(),
                    [('XYZ',)],
                )

    def test_manual_category_listing_works_after_view_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.convert_legacy_tables_to_compatibility_views()
            db.replace_code_prefix_movies(
                'XYZ',
                [{
                    'code': 'XYZ-001',
                    'title': 'Prefix movie',
                    'author': '演员A',
                    'release_date': '2024-01-01',
                    'javtxt_enrichment_status': 'ENRICHED',
                    'javtxt_movie_id': 'xyz-001',
                }],
            )

            result = db.list_videos_requiring_manual_category()

            self.assertIsInstance(result, dict)
            self.assertIn('videos', result)

    def test_javtxt_cleanup_after_view_conversion_updates_canonical_entity(self):
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
                    'javtxt_enrichment_status': 'ENRICHED',
                    'javtxt_movie_id': '',
                    'javtxt_url': '',
                }],
            )

            with db._connect() as conn:
                db._clear_web_movie_javtxt_state_without_detail_reference(
                    conn.cursor(), 'actor_movies'
                )
                conn.commit()
                row = conn.execute(
                    '''
                    SELECT author, javtxt_actors_raw, javtxt_enrichment_status,
                           javtxt_movie_id, javtxt_url
                    FROM video_entities
                    WHERE code = ?
                    ''',
                    ('XYZ-001',),
                ).fetchone()

            self.assertEqual(row, ('', '', 'UNENRICHED', '', ''))

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
