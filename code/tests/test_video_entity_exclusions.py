import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.data.database_handler import VideoDatabase
from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE


class VideoEntityExclusionsTest(unittest.TestCase):
    def test_rebuild_materializes_all_exclusion_sources_and_hides_video_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            for code, title, tags, release_date in (
                ('ABC-001', 'Normal title', '', '2024-01-01'),
                ('XYZ-001', 'Normal title', '', '2024-01-01'),
                ('QWE-001', 'Blocked title', '', '2024-01-01'),
                ('RTY-001', 'Normal title', 'Blocked tag', '2024-01-01'),
                ('OLD-001', 'Normal title', '', '2019-01-01'),
            ):
                db.upsert_video_entity(
                    {
                        'code': code,
                        'title': title,
                        'javtxt_tags': tags,
                        'release_date': release_date,
                    },
                    actor_relations=[{'actor_name': '演员A'}] if code == 'XYZ-001' else None,
                    local_record={'storage_location': f'D:/videos/{code}.mp4'},
                )

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute('INSERT INTO hidden_code_prefixes (prefix) VALUES (?)', ('XYZ',))
                conn.execute('INSERT INTO hidden_actors (name) VALUES (?)', ('演员A',))
                conn.commit()

            settings = {
                'rules': {
                    'code': [],
                    'title': ['Blocked title'],
                    'javtxt_tags': ['Blocked tag'],
                    'co_star_code': [],
                }
            }
            with patch.object(db, '_load_video_category_filter_settings', return_value=settings):
                changed = db.rebuild_video_entity_exclusions()
                rows = db.list_videos()

            self.assertGreater(changed, 0)
            self.assertEqual([row['code'] for row in rows], ['ABC-001'])
            with closing(sqlite3.connect(db_path)) as conn:
                exclusions = conn.execute(
                    '''
                    SELECT code, exclusion_type, scope
                    FROM video_entity_exclusions
                    ORDER BY code, exclusion_type
                    '''
                ).fetchall()

            self.assertEqual(
                exclusions,
                [
                    ('OLD-001', 'release_date', 'all'),
                    ('QWE-001', 'filter_title', 'all'),
                    ('RTY-001', 'filter_tags', 'all'),
                    ('XYZ-001', 'actor_blacklist', 'all'),
                    ('XYZ-001', 'code_prefix_blacklist', 'all'),
                ],
            )

    def test_rebuild_removes_stale_exclusions_after_rules_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Blocked title'},
                local_record={'storage_location': 'D:/videos/ABC-001.mp4'},
            )

            blocked_settings = {
                'rules': {
                    'code': [],
                    'title': ['Blocked'],
                    'javtxt_tags': [],
                    'co_star_code': [],
                }
            }
            clear_settings = {
                'rules': {
                    'code': [],
                    'title': [],
                    'javtxt_tags': [],
                    'co_star_code': [],
                }
            }
            with patch.object(db, '_load_video_category_filter_settings', return_value=blocked_settings):
                db.rebuild_video_entity_exclusions()
                self.assertEqual(db.list_videos(), [])
            with patch.object(db, '_load_video_category_filter_settings', return_value=clear_settings):
                db.rebuild_video_entity_exclusions()
                self.assertEqual([row['code'] for row in db.list_videos()], ['ABC-001'])

    def test_exclusions_gate_actor_and_code_prefix_library_reads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            for code in ('ABC-001', 'XYZ-001'):
                db.upsert_video_entity(
                    {'code': code, 'title': code},
                    actor_relations=[{'actor_name': '演员A'}],
                    prefix_relations=[{'prefix': code.split('-')[0]}],
                )

            with closing(sqlite3.connect(db.db_path)) as conn:
                conn.execute(
                    'INSERT INTO video_entity_exclusions (code, exclusion_type, scope, source) VALUES (?, ?, ?, ?)',
                    ('XYZ-001', 'manual', 'all', 'test'),
                )
                conn.commit()

            self.assertEqual([row['code'] for row in db.list_actor_movies('演员A')], ['ABC-001'])
            self.assertEqual([row['code'] for row in db.list_code_prefix_movies('XYZ')], [])

    def test_active_table_is_one_way_projection_of_canonical_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Original'},
                local_record={'storage_location': 'D:/videos/ABC-001.mp4'},
            )

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute('SELECT title FROM active_video_entities WHERE code = ?', ('ABC-001',)).fetchone()[0],
                    'Original',
                )
                conn.execute(
                    'UPDATE active_video_entities SET title = ? WHERE code = ?',
                    ('Updated from active', 'ABC-001'),
                )
                conn.commit()
                self.assertEqual(
                    conn.execute('SELECT title FROM video_entities WHERE code = ?', ('ABC-001',)).fetchone()[0],
                    'Original',
                )

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    'INSERT INTO hidden_code_prefixes (prefix) VALUES (?)',
                    ('ABC',),
                )
                conn.commit()
            db.rebuild_video_entity_exclusions()

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertIsNotNone(
                    conn.execute('SELECT 1 FROM video_entities WHERE code = ?', ('ABC-001',)).fetchone()
                )
                self.assertIsNone(
                    conn.execute('SELECT 1 FROM active_video_entities WHERE code = ?', ('ABC-001',)).fetchone()
                )

    def test_reopening_materialized_database_skips_full_exclusion_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Existing'},
                local_record={'storage_location': 'D:/videos/ABC-001.mp4'},
            )

            with patch.object(VideoDatabase, 'rebuild_video_entity_exclusions', autospec=True) as rebuild_mock:
                reopened_db = VideoDatabase(db_path)

            rebuild_mock.assert_not_called()
            self.assertEqual([row['code'] for row in reopened_db.list_videos()], ['ABC-001'])

    def test_avfan_reset_keeps_code_prefix_relations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'RCTD-001', 'title': 'RCTD'},
                prefix_relations=[{'prefix': 'RCTD', 'avfan_url': 'https://example.test/rctd'}],
            )
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "INSERT INTO code_prefix_enrichments (prefix, avfan_enrichment_status) VALUES (?, ?)",
                    ('RCTD', '已补全'),
                )
                conn.commit()

            db.reset_code_prefix_enrichments(['RCTD'], source_key=AVFAN_VIDEO_SOURCE)

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute(
                        'SELECT COUNT(*) FROM video_code_prefix_relations WHERE prefix = ?',
                        ('RCTD',),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT COUNT(*) FROM video_prefix_relation_meta WHERE prefix = ?',
                        ('RCTD',),
                    ).fetchone()[0],
                    1,
                )


if __name__ == '__main__':
    unittest.main()
