import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.backend.service import BackendService
from app.data.database_handler import VideoDatabase


class EnrichmentPendingQueueTest(unittest.TestCase):
    QUEUE_TABLES = {
        'pending_video_javtxt',
        'pending_video_avfan',
        'pending_code_prefix_avfan',
        'pending_code_prefix_javtxt',
        'pending_code_prefix_supplement',
        'pending_actor_avfan',
        'pending_actor_javtxt',
        'pending_actor_supplement',
        'pending_actor_binghuo',
        'pending_actor_baomu',
    }

    def test_source_specific_pending_tables_are_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                existing = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }

        self.assertTrue(self.QUEUE_TABLES.issubset(existing))

    def test_claim_physically_moves_rows_from_source_queue_to_single_running_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plan = db.create_enrichment_batch_plan(
                'actor',
                'actor_library',
                'javtxt',
                batch_limit=1,
                batch_count_limit=2,
                candidates=[
                    {'actor_name': '演员甲', 'code': 'SDDE-714'},
                    {'actor_name': '演员甲', 'code': 'SDDE-715'},
                ],
            )

            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'actor', 1)

            with closing(sqlite3.connect(db_path)) as conn:
                source_rows = conn.execute(
                    'SELECT sequence_index FROM pending_actor_javtxt WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchall()
                running_row = conn.execute(
                    '''
                    SELECT origin_table, actor_name, code, status
                    FROM enrichment_running_items
                    WHERE plan_id = ?
                    ''',
                    (plan['plan_id'],),
                ).fetchone()

        self.assertEqual([row[0] for row in source_rows], [2])
        self.assertEqual(running_row, ('pending_actor_javtxt', '演员甲', 'SDDE-714', 'running'))
        self.assertEqual(claimed[0]['sequence_index'], 1)
        self.assertEqual(claimed[0]['origin_table'], 'pending_actor_javtxt')

    def test_completed_running_item_is_deleted_without_returning_to_source_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plan = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'SDDE-714'}]
            )
            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)

            updated = db.mark_enrichment_batch_item(
                plan['plan_id'], 'video', claimed[0]['sequence_index'], 'completed'
            )
            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'video')

            with closing(sqlite3.connect(db_path)) as conn:
                source_count = conn.execute(
                    'SELECT COUNT(*) FROM pending_video_javtxt WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchone()[0]
                running_count = conn.execute(
                    'SELECT COUNT(*) FROM enrichment_running_items WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchone()[0]

        self.assertEqual(updated, 1)
        self.assertEqual(source_count, 0)
        self.assertEqual(running_count, 0)
        self.assertEqual(progress['completed_count'], 1)
        self.assertEqual(progress['total_count'], 1)

    def test_failed_running_item_returns_to_exact_source_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plan = db.create_enrichment_batch_plan(
                'actor',
                'actor_library',
                'supplement',
                1,
                1,
                candidates=[
                    {
                        'actor_name': '演员甲',
                        'code': 'SDDE-714',
                        'supplement_mode': 'actors_only',
                    }
                ],
            )
            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'actor', 1)

            updated = db.mark_enrichment_batch_item(
                plan['plan_id'],
                'actor',
                claimed[0]['sequence_index'],
                'failed',
                error='网络连接失败',
            )

            with closing(sqlite3.connect(db_path)) as conn:
                restored = conn.execute(
                    '''
                    SELECT actor_name, code, supplement_mode, status, last_error, attempt_count
                    FROM pending_actor_supplement
                    WHERE plan_id = ?
                    ''',
                    (plan['plan_id'],),
                ).fetchone()
                running_count = conn.execute(
                    'SELECT COUNT(*) FROM enrichment_running_items WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchone()[0]

        self.assertEqual(updated, 1)
        self.assertEqual(
            restored,
            ('演员甲', 'SDDE-714', 'actors_only', 'failed', '网络连接失败', 1),
        )
        self.assertEqual(running_count, 0)

    def test_each_plan_writes_only_its_source_queue_and_keeps_concrete_code(self):
        cases = [
            ('video', 'video_library', 'javtxt', 'pending_video_javtxt', {'code': 'SDDE-714'}),
            ('video', 'video_library', 'supplement', 'pending_video_avfan', {'code': 'SDDE-715', 'supplement_mode': 'actors_only'}),
            ('code_prefix', 'code_prefix_library', 'avfan', 'pending_code_prefix_avfan', {'prefix': 'SDDE'}),
            ('code_prefix', 'code_prefix_library', 'javtxt', 'pending_code_prefix_javtxt', {'prefix': 'SDDE', 'code': 'SDDE-714'}),
            ('code_prefix', 'code_prefix_library', 'supplement', 'pending_code_prefix_supplement', {'prefix': 'SDDE', 'code': 'SDDE-714', 'supplement_mode': 'full'}),
            ('actor', 'actor_library', 'avfan', 'pending_actor_avfan', {'actor_name': '演员甲'}),
            ('actor', 'actor_library', 'javtxt', 'pending_actor_javtxt', {'actor_name': '演员甲', 'code': 'SDDE-714'}),
            ('actor', 'actor_library', 'supplement', 'pending_actor_supplement', {'actor_name': '演员甲', 'code': 'SDDE-714', 'supplement_mode': 'actors_only'}),
            ('actor_birthday', 'actor_birthday', 'binghuo', 'pending_actor_binghuo', {'actor_name': '演员甲'}),
            ('actor_birthday', 'actor_birthday', 'baomu', 'pending_actor_baomu', {'actor_name': '演员甲'}),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plans = []
            for task_kind, target_type, source_key, table_name, candidate in cases:
                plan = db.create_enrichment_batch_plan(
                    task_kind,
                    target_type,
                    source_key,
                    batch_limit=1,
                    batch_count_limit=1,
                    candidates=[candidate],
                )
                plans.append((plan, task_kind, table_name, candidate))

            with closing(sqlite3.connect(db_path)) as conn:
                for plan, task_kind, table_name, candidate in plans:
                    row = conn.execute(
                        f'SELECT code, prefix, actor_name, supplement_mode FROM {table_name} WHERE plan_id = ?',
                        (plan['plan_id'],),
                    ).fetchone()
                    self.assertIsNotNone(row, table_name)
                    self.assertEqual(row[0], candidate.get('code', ''))
                    self.assertEqual(row[1], candidate.get('prefix', ''))
                    self.assertEqual(row[2], candidate.get('actor_name', ''))
                    self.assertEqual(row[3], candidate.get('supplement_mode', ''))
                    self.assertEqual(
                        db.list_enrichment_batch_items(plan['plan_id'], task_kind)[0]['target_key'],
                        candidate.get('code') or candidate.get('prefix') or candidate.get('actor_name'),
                    )

    def test_javtxt_cache_bulk_lookup_chunks_large_code_sets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            rows = [(f'BIG-{index:04d}', '演员甲') for index in range(1200)]
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    'INSERT INTO processed_videos (code, javtxt_actors) VALUES (?, ?)',
                    rows,
                )
                conn.commit()

            cached = db.get_javtxt_actor_cache_by_codes([row[0] for row in rows])

        self.assertEqual(len(cached), 1200)
        self.assertEqual(cached['BIG-1199']['javtxt_actors'], '演员甲')

    def test_concrete_actor_javtxt_items_complete_by_exact_processed_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'actor',
                'actor_library',
                'javtxt',
                batch_limit=2,
                batch_count_limit=1,
                candidates=[
                    {'actor_name': '演员甲', 'code': 'SDDE-714'},
                    {'actor_name': '演员甲', 'code': 'SDDE-715'},
                ],
            )
            db.claim_enrichment_batch_items(plan['plan_id'], 'actor', 2)
            service = object.__new__(BackendService)
            service.db = db

            service._apply_enrichment_batch_plan_result(
                plan['plan_id'],
                'actor',
                {
                    'processed_count': 1,
                    'stopped': True,
                    'processed_items': [
                        {'actor_name': '演员甲', 'code': 'SDDE-715', 'status': '无搜索结果'}
                    ],
                    'results': [
                        {
                            'actor_name': '演员甲',
                            'processed_video_count': 1,
                            'count_unit': '视频',
                            'status': '已补全',
                        }
                    ],
                },
            )

            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'actor')

            items = db.list_enrichment_batch_items(plan['plan_id'], 'actor', status=None)

        self.assertEqual(progress['completed_count'], 1)
        self.assertEqual(progress['pending_count'], 1)
        self.assertEqual(
            {item['code']: item['status'] for item in items},
            {'SDDE-714': 'pending'},
        )

    def test_running_table_blocks_a_different_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            first = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'AAA-001'}]
            )
            second = db.create_enrichment_batch_plan(
                'actor', 'actor_library', 'avfan', 1, 1, candidates=[{'actor_name': '演员甲'}]
            )
            db.claim_enrichment_batch_items(first['plan_id'], 'video', 1)

            with self.assertRaisesRegex(RuntimeError, '当前已有补全任务正在执行'):
                db.claim_enrichment_batch_items(second['plan_id'], 'actor', 1)

    def test_restart_recovery_returns_running_row_to_its_origin_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plan = db.create_enrichment_batch_plan(
                'code_prefix',
                'code_prefix_library',
                'javtxt',
                1,
                1,
                candidates=[{'prefix': 'SDDE', 'code': 'SDDE-714'}],
            )
            db.claim_enrichment_batch_items(plan['plan_id'], 'code_prefix', 1)

            recovered = db.recover_running_enrichment_plans('程序重启恢复')

            with closing(sqlite3.connect(db_path)) as conn:
                restored = conn.execute(
                    '''
                    SELECT prefix, code, status
                    FROM pending_code_prefix_javtxt
                    WHERE plan_id = ?
                    ''',
                    (plan['plan_id'],),
                ).fetchone()
                running_count = conn.execute(
                    'SELECT COUNT(*) FROM enrichment_running_items'
                ).fetchone()[0]

        self.assertEqual(recovered, 1)
        self.assertEqual(restored, ('SDDE', 'SDDE-714', 'pending'))
        self.assertEqual(running_count, 0)

    def test_same_code_for_two_actors_is_acknowledged_by_composite_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'actor',
                'actor_library',
                'javtxt',
                batch_limit=2,
                batch_count_limit=1,
                candidates=[
                    {'actor_name': '演员甲', 'code': 'SDDE-714'},
                    {'actor_name': '演员乙', 'code': 'SDDE-714'},
                ],
            )
            db.claim_enrichment_batch_items(plan['plan_id'], 'actor', 2)
            service = object.__new__(BackendService)
            service.db = db

            service._apply_enrichment_batch_plan_result(
                plan['plan_id'],
                'actor',
                {
                    'processed_count': 1,
                    'processed_items': [
                        {'actor_name': '演员甲', 'code': 'SDDE-714', 'status': '已补全'},
                        {'actor_name': '演员乙', 'code': 'SDDE-714', 'status': '已补全'},
                    ],
                    'results': [],
                },
            )

            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'actor')

        self.assertEqual(progress['completed_count'], 2)
        self.assertEqual(progress['pending_count'], 0)

    def test_retryable_item_can_be_claimed_after_configured_batch_rounds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'SDDE-714'}]
            )
            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)
            db.mark_enrichment_batch_item(plan['plan_id'], 'video', claimed[0]['sequence_index'], 'failed')
            db.update_enrichment_plan_progress(
                plan['plan_id'], 'video', completed_batch=True, status='running'
            )

            retried = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)

        self.assertEqual(len(retried), 1)
        self.assertEqual(retried[0]['attempt_count'], 2)

    def test_error_pause_releases_claimed_items_without_consuming_batch_round(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'SDDE-714'}]
            )
            db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)
            service = object.__new__(BackendService)
            service.db = db

            service._pause_enrichment_plan_after_error(plan['plan_id'], 'video', 'boom')
            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'video')
            retried = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)

        self.assertEqual(progress['status'], 'paused')
        self.assertEqual(progress['completed_batch_count'], 0)
        self.assertEqual(progress['pending_count'], 1)
        self.assertEqual(len(retried), 1)

    def test_atomic_pause_returns_running_rows_and_pauses_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'SDDE-714'}]
            )
            db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)

            restored = db.pause_enrichment_batch_plan(
                plan['plan_id'], 'video', '网络连接失败'
            )
            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'video')

        self.assertEqual(restored, 1)
        self.assertEqual(progress['status'], 'paused')
        self.assertEqual(progress['paused_reason'], '网络连接失败')
        self.assertEqual(progress['pending_count'], 1)
        self.assertEqual(progress['running_count'], 0)

    def test_release_resolves_duplicate_origin_row_without_blocking_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            plan = db.create_enrichment_batch_plan(
                'video', 'video_library', 'javtxt', 1, 1, candidates=[{'code': 'SDDE-714'}]
            )
            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO pending_video_javtxt (
                        plan_id, sequence_index, target_key, code, source_key, status
                    )
                    VALUES (?, ?, ?, ?, 'javtxt', 'pending')
                    ''',
                    (plan['plan_id'], claimed[0]['sequence_index'], 'STALE-001', 'STALE-001'),
                )
                conn.commit()

            restored_count = db.release_enrichment_batch_items(
                plan['plan_id'], 'video', '程序重启恢复'
            )

            with closing(sqlite3.connect(db_path)) as conn:
                restored = conn.execute(
                    '''
                    SELECT code, status, last_error, attempt_count
                    FROM pending_video_javtxt
                    WHERE plan_id = ? AND sequence_index = ?
                    ''',
                    (plan['plan_id'], claimed[0]['sequence_index']),
                ).fetchone()
                running_count = conn.execute(
                    'SELECT COUNT(*) FROM enrichment_running_items WHERE plan_id = ?',
                    (plan['plan_id'],),
                ).fetchone()[0]

        self.assertEqual(restored_count, 1)
        self.assertEqual(restored, ('SDDE-714', 'pending', '程序重启恢复', 1))
        self.assertEqual(running_count, 0)

    def test_new_plan_rejects_unknown_source_instead_of_using_legacy_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            with self.assertRaisesRegex(ValueError, '不支持的补全任务来源组合'):
                db.create_enrichment_batch_plan(
                    'actor', 'actor_library', 'unknown', 1, 1, candidates=[{'actor_name': '演员甲'}]
                )

    def test_legacy_plan_with_blank_item_table_still_uses_legacy_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'actor', 'actor_library', 'avfan', 1, 1, candidates=[{'actor_name': '演员甲'}]
            )
            with closing(sqlite3.connect(db.db_path)) as conn:
                conn.execute(
                    '''
                    INSERT INTO actor_enrichment_batch_items
                    SELECT * FROM pending_actor_avfan WHERE plan_id = ?
                    ''',
                    (plan['plan_id'],),
                )
                conn.execute('DELETE FROM pending_actor_avfan WHERE plan_id = ?', (plan['plan_id'],))
                conn.execute(
                    "UPDATE enrichment_batch_plans SET item_table = '' WHERE plan_id = ?",
                    (plan['plan_id'],),
                )
                conn.commit()

            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'actor', 1)
            db.mark_enrichment_batch_item(
                plan['plan_id'], 'actor', claimed[0]['sequence_index'], 'completed'
            )
            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'actor')

        self.assertEqual(claimed[0]['actor_name'], '演员甲')
        self.assertEqual(progress['completed_count'], 1)


if __name__ == '__main__':
    unittest.main()
