import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS
from app.data.database_handler import VideoDatabase
from app.services.library import CodePrefixVideoCategoryBulkService
from app.services.video import VIDEO_CATEGORY_CO_STAR


class CodePrefixVideoCategoryBulkServiceTest(unittest.TestCase):
    def test_updates_uncategorized_prefix_videos_and_clears_staging(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            self._seed_processed_video(db_path, 'NEM-001', '')
            self._seed_processed_video(db_path, 'NEM-002', '')
            self._seed_processed_video(db_path, 'NEM-003', VIDEO_CATEGORY_CO_STAR)
            self._seed_processed_video(db_path, 'NEM-004', '')

            self._seed_code_prefix_movie(db_path, 'NEM', 'NEM-001', '', '2024-01-01')
            self._seed_code_prefix_movie(db_path, 'NEM', 'NEM-002', '', '2019-01-01')
            self._seed_code_prefix_movie(db_path, 'NEM', 'NEM-003', VIDEO_CATEGORY_CO_STAR, '2024-01-01')
            self._seed_code_prefix_movie(db_path, 'NEM', 'NEM-004', '', '2024-01-01')

            self._seed_actor_movie(db_path, '演员A', 'NEM-001', '', '2024-01-01')
            self._seed_actor_movie(db_path, '演员A', 'NEM-002', '', '2019-01-01')
            self._seed_actor_movie(db_path, '演员A', 'NEM-003', VIDEO_CATEGORY_CO_STAR, '2024-01-01')
            self._seed_actor_movie(db_path, '演员A', 'NEM-004', '', '2024-01-01')

            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO manual_category_staging (code, category, created_at, updated_at) VALUES (?, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    ('NEM-001',),
                )
                conn.execute(
                    "INSERT INTO manual_category_staging (code, category, created_at, updated_at) VALUES (?, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    ('NEM-004',),
                )
                conn.commit()

            result = CodePrefixVideoCategoryBulkService(db).update_uncategorized_videos('NEM', VIDEO_CATEGORY_CO_STAR)

            self.assertEqual(result['matched_count'], 2)
            self.assertEqual(result['code_count'], 2)
            self.assertEqual(result['cleared_staged_count'], 2)

            with sqlite3.connect(str(db_path)) as conn:
                processed_rows = conn.execute(
                    "SELECT code, video_category FROM video_entities WHERE code LIKE 'NEM-%' ORDER BY code"
                ).fetchall()
                prefix_rows = conn.execute(
                    "SELECT entity.code, entity.video_category FROM video_code_prefix_relations relation JOIN video_entities entity ON entity.code = relation.video_code WHERE relation.prefix = 'NEM' ORDER BY entity.code"
                ).fetchall()
                actor_rows = conn.execute(
                    "SELECT entity.code, entity.video_category FROM video_actor_relations relation JOIN video_entities entity ON entity.code = relation.video_code WHERE relation.actor_name = '演员A' ORDER BY entity.code"
                ).fetchall()
                staged_codes = conn.execute(
                    "SELECT code FROM manual_category_staging ORDER BY code"
                ).fetchall()

            self.assertEqual(
                processed_rows,
                [
                    ('NEM-001', VIDEO_CATEGORY_CO_STAR),
                    ('NEM-002', ''),
                    ('NEM-003', VIDEO_CATEGORY_CO_STAR),
                    ('NEM-004', VIDEO_CATEGORY_CO_STAR),
                ],
            )
            self.assertEqual(prefix_rows, processed_rows)
            self.assertEqual(actor_rows, processed_rows)
            self.assertEqual(staged_codes, [])

            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _seed_processed_video(db_path, code, video_category):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, javtxt_release_date,
                    enrichment_status, avfan_enrichment_status, javtxt_enrichment_status,
                    javtxt_movie_id, javtxt_url, javtxt_actors, javtxt_actors_raw, javtxt_tags, video_category
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    code,
                    '演员A',
                    '2024-01-01',
                    '2024-01-01',
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    ENRICHED_STATUS,
                    code,
                    f'https://example.com/{code}',
                    '演员A',
                    '演员A',
                    '',
                    video_category,
                ),
            )
            conn.commit()

    @staticmethod
    def _seed_code_prefix_movie(db_path, prefix, code, video_category, release_date):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, javtxt_release_date,
                    javtxt_enrichment_status, javtxt_movie_id, javtxt_url,
                    javtxt_actors_raw, video_category
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    code,
                    '演员A',
                    release_date,
                    release_date,
                    ENRICHED_STATUS,
                    code,
                    f'https://example.com/{code}',
                    '演员A',
                    video_category,
                ),
            )
            conn.execute(
                'INSERT INTO video_code_prefix_relations (video_code, prefix) VALUES (?, ?)',
                (code, prefix),
            )
            conn.commit()

    @staticmethod
    def _seed_actor_movie(db_path, actor_name, code, video_category, release_date):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, javtxt_release_date,
                    javtxt_enrichment_status, javtxt_movie_id, javtxt_url,
                    javtxt_actors_raw, video_category
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    code,
                    '演员A',
                    release_date,
                    release_date,
                    ENRICHED_STATUS,
                    code,
                    f'https://example.com/{code}',
                    '演员A',
                    video_category,
                ),
            )
            conn.execute(
                'INSERT INTO video_actor_relations (video_code, actor_name) VALUES (?, ?)',
                (code, actor_name),
            )
            conn.commit()


if __name__ == '__main__':
    unittest.main()
