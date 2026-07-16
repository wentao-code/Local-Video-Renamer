import sqlite3
import tempfile
import unittest
import gc
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase


class ExcludedWebMovieCacheTest(unittest.TestCase):
    def test_database_creates_excluded_web_movie_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                table_names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }

            self.assertIn('excluded_code_prefix_movies', table_names)
            self.assertIn('excluded_actor_movies', table_names)
            del db
            gc.collect()

    def test_excluded_movie_keys_are_unique_and_batch_queryable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')

            db.store_excluded_code_prefix_movies(
                'ABC',
                [
                    {'code': 'ABC-001', 'title': 'one'},
                    {'code': 'ABC-001', 'title': 'one again'},
                ],
                reason='code_blacklist',
            )
            db.store_excluded_actor_movies(
                '演员甲',
                [
                    {'code': 'ABC-001', 'title': 'one'},
                    {'code': 'ABC-002', 'title': 'two'},
                ],
                reason='actor_blacklist',
            )

            self.assertEqual(
                db.list_excluded_code_prefix_movie_keys(['ABC'], ['ABC-001', 'ABC-002']),
                {('ABC', 'ABC-001')},
            )
            self.assertEqual(
                db.list_excluded_actor_movie_keys(['演员甲'], ['ABC-001', 'ABC-002']),
                {('演员甲', 'ABC-001'), ('演员甲', 'ABC-002')},
            )

            with closing(sqlite3.connect(db.db_path)) as conn:
                code_count = conn.execute(
                    'SELECT COUNT(*) FROM excluded_code_prefix_movies'
                ).fetchone()[0]
                actor_count = conn.execute(
                    'SELECT COUNT(*) FROM excluded_actor_movies'
                ).fetchone()[0]

            self.assertEqual(code_count, 1)
            self.assertEqual(actor_count, 2)
            del db
            gc.collect()

    def test_blacklisting_code_prefix_moves_web_movies_to_excluded_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_code_prefix_movies(
                'ABC',
                [{'code': 'ABC-001', 'title': 'blacklisted movie'}],
            )

            result = db.blacklist_code_prefixes(['ABC'])

            self.assertEqual(result['blacklisted_count'], 1)
            self.assertEqual(db.list_code_prefix_movies('ABC'), [])
            with closing(sqlite3.connect(db.db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT prefix, code, title, exclude_reason
                    FROM excluded_code_prefix_movies
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('ABC', 'ABC-001'),
                ).fetchone()
            self.assertEqual(row, ('ABC', 'ABC-001', 'blacklisted movie', 'code_blacklist'))
            del db
            gc.collect()

    def test_deleting_actor_moves_web_movies_to_excluded_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_actor_movies(
                '演员甲',
                [{'code': 'ABC-001', 'title': 'actor movie'}],
            )

            db.delete_actor('演员甲')

            self.assertEqual(db.list_actor_movies('演员甲'), [])
            with closing(sqlite3.connect(db.db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT actor_name, code, title, exclude_reason
                    FROM excluded_actor_movies
                    WHERE actor_name = ? AND code = ?
                    ''',
                    ('演员甲', 'ABC-001'),
                ).fetchone()
            self.assertEqual(row, ('演员甲', 'ABC-001', 'actor movie', 'actor_blacklist'))
            del db
            gc.collect()

    def test_replace_does_not_delete_existing_excluded_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.store_excluded_code_prefix_movies(
                'ABC',
                [{'code': 'ABC-001', 'title': 'archived'}],
                reason='filter',
            )
            db.store_excluded_actor_movies(
                '演员甲',
                [{'code': 'ABC-001', 'title': 'archived'}],
                reason='filter',
            )

            db.replace_code_prefix_movies('ABC', [{'code': 'ABC-001', 'title': 'fetched again'}])
            db.replace_actor_movies('演员甲', [{'code': 'ABC-001', 'title': 'fetched again'}])

            self.assertEqual(db.list_code_prefix_movies('ABC'), [])
            self.assertEqual(db.list_actor_movies('演员甲'), [])

            with closing(sqlite3.connect(db.db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT COUNT(*) FROM excluded_code_prefix_movies WHERE prefix = ?',
                        ('ABC',),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT COUNT(*) FROM excluded_actor_movies WHERE actor_name = ?',
                        ('演员甲',),
                    ).fetchone()[0],
                    1,
                )
            del db
            gc.collect()

    def test_post_enrichment_filter_routes_movie_to_excluded_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db._load_video_category_filter_settings = lambda: {
                'rules': {
                    'code': ['ABC'],
                    'title': [],
                    'javtxt_tags': [],
                    'co_star_code': [],
                }
            }

            db.replace_code_prefix_movies(
                'ABC',
                [{
                    'code': 'ABC-001',
                    'title': 'filtered movie',
                    'release_date': '2024-01-01',
                    'javtxt_enrichment_status': 'enriched',
                    'javtxt_movie_id': 'javtxt-1',
                }],
            )

            self.assertEqual(db.list_code_prefix_movies('ABC'), [])
            with closing(sqlite3.connect(db.db_path)) as conn:
                reason = conn.execute(
                    'SELECT exclude_reason FROM excluded_code_prefix_movies WHERE prefix = ? AND code = ?',
                    ('ABC', 'ABC-001'),
                ).fetchone()[0]
            self.assertEqual(reason, 'filter')
            del db
            gc.collect()

    def test_migrate_excluded_web_movies_is_batched_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_code_prefix_movies(
                'ABC',
                [
                    {'code': 'ABC-001', 'title': 'filtered movie', 'release_date': '2024-01-01'},
                    {'code': 'ABC-002', 'title': 'kept movie'},
                ],
            )
            with closing(sqlite3.connect(db.db_path)) as conn:
                conn.execute(
                    '''
                    UPDATE code_prefix_movies
                    SET javtxt_enrichment_status = '已完成',
                        javtxt_movie_id = 'javtxt-1',
                        javtxt_release_date = '2024-01-01'
                    WHERE prefix = ? AND code = ?
                    ''',
                    ('ABC', 'ABC-001'),
                )
                conn.commit()
            db._load_video_category_filter_settings = lambda: {
                'rules': {
                    'code': [],
                    'title': ['filtered'],
                    'javtxt_tags': [],
                    'co_star_code': [],
                }
            }

            first = db.migrate_excluded_web_movies(batch_size=1)
            second = db.migrate_excluded_web_movies(batch_size=1)

            self.assertEqual(first['code_prefix_movies'], 1)
            self.assertEqual(first['actor_movies'], 0)
            self.assertEqual(first['total'], 1)
            self.assertEqual(second['total'], 0)
            self.assertEqual([row['code'] for row in db.list_code_prefix_movies('ABC')], ['ABC-002'])
            with closing(sqlite3.connect(db.db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT COUNT(*) FROM excluded_code_prefix_movies WHERE prefix = ?',
                        ('ABC',),
                    ).fetchone()[0],
                    1,
                )
            del db
            gc.collect()


if __name__ == '__main__':
    unittest.main()
