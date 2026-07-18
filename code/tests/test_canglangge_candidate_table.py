import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.backend.service import BackendService
from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS


class CanglanggeCandidateTableTest(unittest.TestCase):
    def test_refresh_replaces_candidates_and_preserves_enrichment_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')

            db.replace_canglangge_actor_candidates([
                {
                    'actor_name': '演员甲',
                    'prefixes': ['IPX', 'ROE'],
                    'binghuo_enrichment_status': '状态5',
                    'baomu_enrichment_status': '未补全',
                    'binghuo_birthday': '2000-01-01',
                },
            ])

            rows = db.list_canglangge_actor_candidates()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['actor_name'], '演员甲')
            self.assertEqual(rows[0]['prefixes'], ['IPX', 'ROE'])
            self.assertEqual(rows[0]['binghuo_enrichment_status'], '状态5')
            self.assertEqual(rows[0]['binghuo_birthday'], '2000-01-01')
            del db

    def test_refresh_removes_stale_candidates_but_keeps_queued_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_canglangge_actor_candidates([
                {'actor_name': '旧演员', 'prefixes': ['OLD']},
                {'actor_name': '保留演员', 'prefixes': ['KEEP']},
            ])
            plan = db.create_enrichment_batch_plan(
                'actor_birthday',
                'actor_birthday',
                'binghuo',
                batch_limit=1,
                batch_count_limit=1,
                candidates=[{'actor_name': '保留演员'}],
            )

            db.replace_canglangge_actor_candidates([{'actor_name': '新演员', 'prefixes': ['NEW']}])
            names = {row['actor_name'] for row in db.list_canglangge_actor_candidates()}

            self.assertEqual(names, {'新演员', '保留演员'})
            self.assertTrue(plan['plan_id'])
            del db

    def test_candidate_table_is_created_separately_from_actor_library(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            del db
            with closing(sqlite3.connect(db_path)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
            del conn

        self.assertIn('canglangge_actor_candidates', tables)
        self.assertIn('actors', tables)
        self.assertNotEqual('canglangge_actor_candidates', 'actors')

    def test_adding_candidate_creates_only_binghuo_pending_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_canglangge_actor_candidates([
                {'actor_name': '演员甲', 'prefixes': ['IPX']},
            ])
            service = BackendService.__new__(BackendService)
            service.db = db
            service.ensure_database_loaded = lambda: None

            result = service.add_canglangge_candidates_to_tasks(['演员甲'])

            self.assertEqual(result['queued_count'], 1)
            with closing(sqlite3.connect(db.db_path)) as conn:
                binghuo_count = conn.execute(
                    'SELECT COUNT(*) FROM pending_actor_binghuo WHERE plan_id = ?',
                    (result['plan']['plan_id'],),
                ).fetchone()[0]
                baomu_count = conn.execute(
                    'SELECT COUNT(*) FROM pending_actor_baomu WHERE plan_id = ?',
                    (result['plan']['plan_id'],),
                ).fetchone()[0]
            self.assertEqual(binghuo_count, 1)
            self.assertEqual(baomu_count, 0)
            del db

    def test_adding_all_candidates_creates_missing_binghuo_and_baomu_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_canglangge_actor_candidates([
                {'actor_name': '冰火未补全', 'prefixes': ['IPX']},
                {
                    'actor_name': '冰火已执行',
                    'prefixes': ['ROE'],
                    'binghuo_enrichment_status': ENRICHED_STATUS,
                    'binghuo_birthday': '2000-01-01',
                    'binghuo_height': '168',
                },
            ])
            service = BackendService.__new__(BackendService)
            service.db = db
            service.ensure_database_loaded = lambda: None

            result = service.add_canglangge_candidates_to_tasks()

            self.assertEqual(result['queued_count'], 2)
            sources = {plan['source_key'] for plan in result['plans']}
            self.assertEqual(sources, {'binghuo', 'baomu'})
            del db

    def test_enrichment_write_updates_candidate_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_canglangge_actor_candidates([
                {'actor_name': '演员甲', 'prefixes': ['IPX']},
            ])

            db.save_binghuo_actor_profile(
                '演员甲', ENRICHED_STATUS, birthday='2000-01-01', height='168'
            )
            row = db.list_canglangge_actor_candidates(['演员甲'])[0]

            self.assertEqual(row['binghuo_birthday'], '2000-01-01')
            self.assertEqual(row['binghuo_height'], '168')
            self.assertEqual(row['binghuo_enrichment_status'], ENRICHED_STATUS)
            del db

    def test_binghuo_completion_queues_baomu_when_status_is_not_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.replace_canglangge_actor_candidates([
                {'actor_name': '演员甲', 'prefixes': ['IPX']},
            ])
            db.save_binghuo_actor_profile(
                '演员甲', ENRICHED_STATUS, birthday='2000-01-01', height='168'
            )
            service = BackendService.__new__(BackendService)
            service.db = db

            plan = service._queue_baomu_candidates_after_binghuo(['演员甲'])

            self.assertTrue(plan['plan_id'])
            with closing(sqlite3.connect(db.db_path)) as conn:
                count = conn.execute(
                    'SELECT COUNT(*) FROM pending_actor_baomu WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchone()[0]
            self.assertEqual(count, 1)
            del db


if __name__ == '__main__':
    unittest.main()
