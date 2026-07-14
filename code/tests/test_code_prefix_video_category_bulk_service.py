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
                    "SELECT code, video_category FROM processed_videos WHERE code LIKE 'NEM-%' ORDER BY code"
                ).fetchall()
                prefix_rows = conn.execute(
                    "SELECT code, video_category FROM code_prefix_movies WHERE prefix = 'NEM' ORDER BY code"
                ).fetchall()
                actor_rows = conn.execute(
                    "SELECT code, video_category FROM actor_movies WHERE actor_name = '演员A' ORDER BY code"
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
                INSERT INTO processed_videos (
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
                INSERT INTO code_prefix_movies (
                    prefix, code, title, author, release_date, avfan_url, page_number,
                    javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                )
                VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    prefix,
                    code,
                    code,
                    '演员A',
                    release_date,
                    ENRICHED_STATUS,
                    code,
                    f'https://example.com/{code}',
                    release_date,
                    '演员A',
                    video_category,
                ),
            )
            conn.commit()

    @staticmethod
    def _seed_actor_movie(db_path, actor_name, code, video_category, release_date):
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO actor_movies (
                    actor_name, code, title, author, release_date, avfan_url, page_number,
                    javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                )
                VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    actor_name,
                    code,
                    code,
                    '演员A',
                    release_date,
                    ENRICHED_STATUS,
                    code,
                    f'https://example.com/{code}',
                    release_date,
                    '演员A',
                    video_category,
                ),
            )
            conn.commit()


if __name__ == '__main__':
    unittest.main()
