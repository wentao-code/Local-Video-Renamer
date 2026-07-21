import sqlite3
import tempfile
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from unittest.mock import patch

from app.core.enrichment_sources import SUPPLEMENT_TASK_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS
from app.data.database_handler import VideoDatabase
from app.services.enrichment.supplement_enrichment import (
    ActorSupplementEnrichmentService,
    CodePrefixSupplementEnrichmentService,
    VideoSupplementEnrichmentService,
)


class _FakeScraper:
    def __init__(self, payload_by_code=None, payload_by_url=None):
        self.payload_by_code = dict(payload_by_code or {})
        self.payload_by_url = dict(payload_by_url or {})
        self.code_calls = []
        self.url_calls = []

    def session(self):
        return nullcontext()

    def fetch_by_code(self, code):
        self.code_calls.append(code)
        return dict(self.payload_by_code.get(code, {'found': False, 'error': 'not found'}))

    def fetch_by_url(self, url):
        self.url_calls.append(url)
        return dict(self.payload_by_url.get(url, {'found': False, 'error': 'not found'}))


class _FakeProgressTracker:
    def __init__(self):
        self.starts = []
        self.updates = []
        self.finishes = []

    def start(
        self,
        target_label,
        total_count,
        source_label='',
        message='',
        count_unit='',
        target_type='',
        source_key='',
        log_path='',
        task_kind='single',
    ):
        self.starts.append(
            {
                'target_label': target_label,
                'total_count': total_count,
                'source_label': source_label,
                'count_unit': count_unit,
                'target_type': target_type,
                'source_key': source_key,
                'task_kind': task_kind,
            }
        )

    def update(self, processed_count, success_count, failed_count, current_item=''):
        self.updates.append(
            {
                'processed_count': processed_count,
                'success_count': success_count,
                'failed_count': failed_count,
                'current_item': current_item,
            }
        )

    def finish(self, message='', stopped=False):
        self.finishes.append({'message': message, 'stopped': stopped})


class SupplementTaskDatabaseTest(unittest.TestCase):
    def test_enrichment_batch_plan_tables_are_created_at_execution_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                plan_count = conn.execute('SELECT COUNT(*) FROM enrichment_batch_plans').fetchone()[0]
                video_item_count = conn.execute('SELECT COUNT(*) FROM video_enrichment_batch_items').fetchone()[0]
                code_prefix_item_count = conn.execute(
                    'SELECT COUNT(*) FROM code_prefix_enrichment_batch_items'
                ).fetchone()[0]
                actor_item_count = conn.execute('SELECT COUNT(*) FROM actor_enrichment_batch_items').fetchone()[0]
                actor_birthday_item_count = conn.execute(
                    'SELECT COUNT(*) FROM actor_birthday_enrichment_batch_items'
                ).fetchone()[0]

            self.assertEqual(plan_count, 0)
            self.assertEqual(video_item_count, 0)
            self.assertEqual(code_prefix_item_count, 0)
            self.assertEqual(actor_item_count, 0)
            self.assertEqual(actor_birthday_item_count, 0)

            video_plan = db.create_enrichment_batch_plan(
                'video',
                'video_library',
                SUPPLEMENT_TASK_SOURCE,
                batch_limit=2,
                batch_count_limit=3,
                candidates=[
                    {'code': 'AAA-001'},
                    {'code': 'AAA-002'},
                ],
            )
            code_prefix_plan = db.create_enrichment_batch_plan(
                'code_prefix',
                'code_prefix_library',
                SUPPLEMENT_TASK_SOURCE,
                batch_limit=1,
                batch_count_limit=1,
                candidates=[
                    {'prefix': 'BBB', 'code': 'BBB-001'},
                ],
            )
            actor_plan = db.create_enrichment_batch_plan(
                'actor',
                'actor_library',
                SUPPLEMENT_TASK_SOURCE,
                batch_limit=1,
                batch_count_limit=1,
                candidates=[
                    {'actor_name': 'Actor A', 'code': 'ACT-001'},
                ],
            )
            actor_birthday_plan = db.create_enrichment_batch_plan(
                'actor_birthday',
                'actor_birthday',
                'binghuo',
                batch_limit=1,
                batch_count_limit=1,
                candidates=[
                    {'name': 'Actor B'},
                ],
            )

            self.assertNotEqual(video_plan['plan_id'], code_prefix_plan['plan_id'])
            self.assertEqual(video_plan['item_count'], 2)
            self.assertEqual(code_prefix_plan['item_count'], 1)
            self.assertEqual(actor_plan['item_count'], 1)
            self.assertEqual(actor_birthday_plan['item_count'], 1)
            self.assertEqual(
                [row['code'] for row in db.list_enrichment_batch_items(video_plan['plan_id'], 'video')],
                ['AAA-001', 'AAA-002'],
            )
            self.assertEqual(
                [row['prefix'] for row in db.list_enrichment_batch_items(code_prefix_plan['plan_id'], 'code_prefix')],
                ['BBB'],
            )
            self.assertEqual(
                [row['actor_name'] for row in db.list_enrichment_batch_items(actor_plan['plan_id'], 'actor')],
                ['Actor A'],
            )
            self.assertEqual(
                [
                    row['actor_name']
                    for row in db.list_enrichment_batch_items(actor_birthday_plan['plan_id'], 'actor_birthday')
                ],
                ['Actor B'],
            )

            claimed = db.claim_enrichment_batch_items(video_plan['plan_id'], 'video', 1)
            db.mark_enrichment_batch_item(
                video_plan['plan_id'], 'video', claimed[0]['sequence_index'], 'completed'
            )

            video_items = db.list_enrichment_batch_items(video_plan['plan_id'], 'video', status=None)
            code_prefix_items = db.list_enrichment_batch_items(
                code_prefix_plan['plan_id'],
                'code_prefix',
                status=None,
            )
            self.assertEqual(
                [(row['sequence_index'], row['status']) for row in video_items],
                [(2, 'pending')],
            )
            self.assertEqual(code_prefix_items[0]['status'], 'pending')

    def test_enrichment_plan_claim_and_progress_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'video',
                'video_library',
                'avfan',
                batch_limit=2,
                batch_count_limit=2,
                candidates=[{'code': 'AAA-001'}, {'code': 'AAA-002'}, {'code': 'AAA-003'}],
            )

            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 2)
            self.assertEqual([row['sequence_index'] for row in claimed], [1, 2])
            self.assertEqual([row['status'] for row in claimed], ['running', 'running'])
            self.assertTrue(claimed[0]['started_at'])
            self.assertTrue(claimed[0]['claimed_at'])
            self.assertEqual(claimed[0]['attempt_count'], 1)
            resumed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 1)
            self.assertEqual([row['sequence_index'] for row in resumed], [1, 2])
            self.assertEqual([row['attempt_count'] for row in resumed], [1, 1])

            db.mark_enrichment_batch_item(plan['plan_id'], 'video', 1, 'completed')
            db.mark_enrichment_batch_item(plan['plan_id'], 'video', 2, 'failed', error='temporary')
            progress = db.update_enrichment_plan_progress(
                plan['plan_id'],
                'video',
                completed_batch=True,
                status='running',
            )

            self.assertEqual(progress['completed_batch_count'], 1)
            self.assertEqual(progress['pending_count'], 1)
            self.assertEqual(progress['completed_count'], 1)
            self.assertEqual(progress['failed_count'], 1)
            self.assertEqual(progress['running_count'], 0)

    def test_recover_running_enrichment_plan_releases_only_running_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            plan = db.create_enrichment_batch_plan(
                'video',
                'video_library',
                'avfan',
                batch_limit=2,
                batch_count_limit=1,
                candidates=[{'code': 'AAA-001'}, {'code': 'AAA-002'}],
            )
            claimed = db.claim_enrichment_batch_items(plan['plan_id'], 'video', 2)
            db.mark_enrichment_batch_item(plan['plan_id'], 'video', claimed[0]['sequence_index'], 'completed')

            recovered = db.recover_running_enrichment_plans('程序重启恢复')
            self.assertEqual(recovered, 1)
            progress = db.get_enrichment_batch_plan_progress(plan['plan_id'], 'video')
            self.assertEqual(progress['status'], 'paused')
            self.assertEqual(progress['paused_reason'], '程序重启恢复')
            self.assertEqual(progress['completed_count'], 1)
            self.assertEqual(progress['pending_count'], 1)
            self.assertEqual(progress['running_count'], 0)
            self.assertEqual(
                db.list_enrichment_batch_items(plan['plan_id'], 'video', status='completed'),
                [],
            )

    def test_video_supplement_candidates_include_unpublished_actor_rows_as_actor_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-000',
                title='Unpublished Actor',
                author='未公开',
                release_date='2024-01-01',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m0',
                javtxt_url='https://javtxt.example/m0',
                javtxt_title='Unpublished Actor',
                javtxt_actors_raw='未公开',
                javtxt_release_date='2024-01-01',
            )
            self._insert_processed_video(
                db_path,
                code='AAA-002',
                title='No Search',
                release_date='2024-01-02',
                javtxt_status=NO_SEARCH_RESULTS_STATUS,
                javtxt_title='No Search',
                javtxt_release_date='2024-01-02',
            )

            candidates = db.list_video_supplement_candidates(limit=10)

        self.assertEqual(
            [(row['code'], row['supplement_mode']) for row in candidates],
            [('AAA-000', 'actors_only'), ('AAA-002', 'full')],
        )

    def test_video_supplement_candidates_prioritize_missing_actor_before_no_search(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-001',
                title='Missing Actor',
                release_date='2024-01-01',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m1',
                javtxt_url='https://javtxt.example/m1',
                javtxt_title='Missing Actor',
                javtxt_release_date='2024-01-01',
            )
            self._insert_processed_video(
                db_path,
                code='AAA-002',
                title='No Search',
                release_date='2024-01-02',
                javtxt_status=NO_SEARCH_RESULTS_STATUS,
                javtxt_title='No Search',
                javtxt_release_date='2024-01-02',
            )
            self._insert_processed_video(
                db_path,
                code='AAA-003',
                title='Already Complete',
                author='Actor C',
                release_date='2024-01-03',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m3',
                javtxt_url='https://javtxt.example/m3',
                javtxt_title='Already Complete',
                javtxt_actors='Actor C',
                javtxt_actors_raw='Actor C',
                javtxt_release_date='2024-01-03',
            )

            candidates = db.list_video_supplement_candidates(limit=10)

        self.assertEqual(
            [(row['code'], row['supplement_mode']) for row in candidates],
            [('AAA-001', 'actors_only'), ('AAA-002', 'full')],
        )

    def test_video_supplement_candidates_keep_no_result_rows_when_author_is_still_blank(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-010',
                title='Still Missing Author',
                release_date='2024-01-10',
                javtxt_status=NO_SEARCH_RESULTS_STATUS,
                author='Local Actor',
                javtxt_title='Still Missing Author',
                javtxt_release_date='2024-01-10',
                avfan_movie_id='av10',
            )

            candidates = db.list_video_supplement_candidates(limit=10)

        self.assertEqual(
            [(row['code'], row['supplement_mode']) for row in candidates],
            [('AAA-010', 'full')],
        )

    def test_video_supplement_candidates_skip_javtxt_filtered_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='SKIP-001',
                title='Filtered Missing Actor',
                release_date='2024-01-01',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m1',
                javtxt_url='https://javtxt.example/m1',
                javtxt_title='Filtered Missing Actor',
                javtxt_release_date='2024-01-01',
            )
            self._insert_processed_video(
                db_path,
                code='AAA-002',
                title='Visible Missing Actor',
                release_date='2024-01-02',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m2',
                javtxt_url='https://javtxt.example/m2',
                javtxt_title='Visible Missing Actor',
                javtxt_release_date='2024-01-02',
            )

            with patch(
                'app.data.database_handler.load_video_filter_settings',
                return_value={
                    'rules': {
                        'code': ['SKIP'],
                        'title': [],
                        'javtxt_tags': [],
                        'co_star_code': [],
                    }
                },
            ):
                candidates = db.list_video_supplement_candidates(limit=10)

        self.assertEqual(
            [(row['code'], row['supplement_mode']) for row in candidates],
            [('AAA-002', 'actors_only')],
        )

    def test_bulk_update_processed_videos_for_supplement_preserves_actor_only_and_fills_full_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-001',
                title='Keep Title',
                release_date='2024-01-01',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m1',
                javtxt_url='https://javtxt.example/m1',
                javtxt_title='Keep Title',
                javtxt_release_date='2024-01-01',
            )
            self._insert_processed_video(
                db_path,
                code='AAA-002',
                title='Original Title',
                release_date='2024-01-02',
                javtxt_status=NO_SEARCH_RESULTS_STATUS,
                javtxt_title='Original Title',
                javtxt_release_date='2024-01-02',
            )

            db.bulk_update_processed_videos_for_supplement(
                [
                    {
                        'code': 'AAA-001',
                        'title': 'Keep Title',
                        'author': 'Actor A',
                        'author_raw': 'Actor A',
                        'release_date': '2024-01-01',
                        'maker': '',
                        'publisher': '',
                        'avfan_movie_id': '',
                    },
                    {
                        'code': 'AAA-002',
                        'title': 'Filled Title',
                        'author': 'Actor B',
                        'author_raw': 'Actor B',
                        'release_date': '2024-05-06',
                        'maker': 'Maker B',
                        'publisher': 'Publisher B',
                        'avfan_movie_id': 'av2',
                    },
                ]
            )

            rows = db.get_videos_by_codes(['AAA-001', 'AAA-002'])
            candidates = db.list_video_supplement_candidates(limit=10)

        self.assertEqual(rows['AAA-001']['title'], 'Keep Title')
        self.assertEqual(rows['AAA-001']['author'], 'Actor A')
        self.assertEqual(rows['AAA-001']['release_date'], '2024-01-01')
        self.assertEqual(rows['AAA-002']['title'], 'Filled Title')
        self.assertEqual(rows['AAA-002']['author'], 'Actor B')
        self.assertEqual(rows['AAA-002']['release_date'], '2024-05-06')
        self.assertEqual(rows['AAA-002']['maker'], 'Maker B')
        self.assertEqual(rows['AAA-002']['publisher'], 'Publisher B')
        self.assertEqual(rows['AAA-002']['avfan_movie_id'], 'av2')
        self.assertEqual(candidates, [])

    def test_video_supplement_no_result_is_skipped_until_manual_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-020',
                title='Missing Actor',
                release_date='2024-01-20',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m20',
                javtxt_url='https://javtxt.example/m20',
                javtxt_title='Missing Actor',
                javtxt_release_date='2024-01-20',
            )
            service = VideoSupplementEnrichmentService(db, scraper=_FakeScraper())

            first = service.enrich_next_videos(1)
            second = service.enrich_next_videos(1)
            reset_count = db.reset_video_enrichments(['AAA-020'], source_key=SUPPLEMENT_TASK_SOURCE)
            third = service.enrich_next_videos(1)

        self.assertEqual(first['processed_count'], 1)
        self.assertEqual(first['failed_count'], 1)
        self.assertEqual(first['remaining_count'], 0)
        self.assertEqual(second['processed_count'], 0)
        self.assertEqual(reset_count, 1)
        self.assertEqual(third['processed_count'], 1)

    def test_planned_video_supplement_uses_persisted_avfan_url_without_candidate_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            self._insert_processed_video(
                db_path,
                code='AAA-019',
                title='Planned Video',
                release_date='2024-01-19',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m19',
                javtxt_url='https://javtxt.example/m19',
                javtxt_title='Planned Video',
                javtxt_release_date='2024-01-19',
            )
            scraper = _FakeScraper(
                payload_by_url={
                    'https://avfan.example/movies/19': {
                        'found': True,
                        'title': 'Filled Planned Video',
                        'actors': ['Actor 19'],
                        'release_date': '2024-01-19',
                    }
                }
            )

            class PlannedDatabase(VideoDatabase):
                def list_video_supplement_candidates(self, *args, **kwargs):
                    raise AssertionError('planned supplement must not rescan candidate tables')

            planned_db = PlannedDatabase(db_path)
            service = VideoSupplementEnrichmentService(
                planned_db,
                scraper=scraper,
                planned_items=[
                    {
                        'plan_id': 'plan-019',
                        'code': 'AAA-019',
                        'avfan_url': 'https://avfan.example/movies/19',
                        'avfan_movie_id': '19',
                        'supplement_mode': 'full',
                    }
                ],
            )

            result = service.enrich_next_videos(1)

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(scraper.url_calls, ['https://avfan.example/movies/19'])
        self.assertEqual(scraper.code_calls, [])

    def test_video_supplement_incomplete_actor_payload_is_skipped_until_manual_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-021',
                title='Unpublished Actor',
                author='未公开',
                release_date='2024-01-21',
                javtxt_status=ENRICHED_STATUS,
                javtxt_movie_id='m21',
                javtxt_url='https://javtxt.example/m21',
                javtxt_title='Unpublished Actor',
                javtxt_actors_raw='未公开',
                javtxt_release_date='2024-01-21',
            )
            service = VideoSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-021': {
                            'found': True,
                            'title': 'Unpublished Actor',
                            'actors': [],
                            'author': '未公开',
                            'release_date': '2024-01-21',
                        }
                    }
                ),
            )

            first = service.enrich_next_videos(1)
            second = service.enrich_next_videos(1)

        self.assertEqual(first['processed_count'], 1)
        self.assertEqual(first['failed_count'], 1)
        self.assertEqual(first['remaining_count'], 0)
        self.assertEqual(second['processed_count'], 0)

    def test_video_supplement_success_marks_status_completed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            self._insert_processed_video(
                db_path,
                code='AAA-022',
                title='Filled Video',
                release_date='2024-01-22',
                javtxt_status=NO_SEARCH_RESULTS_STATUS,
                javtxt_title='Filled Video',
                javtxt_release_date='2024-01-22',
            )
            service = VideoSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-022': {
                            'found': True,
                            'title': 'Filled Video',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-22',
                            'maker': ['Maker A'],
                            'publisher': ['Publisher A'],
                            'avfan_movie_id': 'av22',
                        }
                    }
                ),
            )

            result = service.enrich_next_videos(1)
            rows = {
                row['code']: row
                for row in db.list_video_summary_rows()
                if row.get('code') == 'AAA-022'
            }

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(rows['AAA-022']['supplement_enrichment_status'], ENRICHED_STATUS)

    def test_actor_supplement_writes_all_videos_in_one_batch_across_actors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.executemany(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    [('Actor A',), ('Actor B',)],
                )
                conn.commit()
            db.replace_actor_movies(
                'Actor A',
                [self._build_library_movie('AAA-101', 'Need A', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS)],
            )
            db.replace_actor_movies(
                'Actor B',
                [self._build_library_movie('BBB-101', 'Need B', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS)],
            )
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-101': {'found': True, 'title': 'Filled A', 'actors': ['Actor A'], 'release_date': '2024-01-01'},
                    'BBB-101': {'found': True, 'title': 'Filled B', 'actors': ['Actor B'], 'release_date': '2024-01-02'},
                }
            )
            original_update = db.bulk_update_actor_movies_for_supplement
            with patch.object(db, 'bulk_update_actor_movies_for_supplement', wraps=original_update) as update_mock:
                result = ActorSupplementEnrichmentService(db, scraper=scraper).enrich_next_actors(2)

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(update_mock.call_count, 1)
        self.assertEqual(len(update_mock.call_args.args[0]), 2)

    def test_code_prefix_supplement_reports_video_progress_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            tracker = _FakeProgressTracker()

            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-001': {
                            'found': True,
                            'title': 'Filled 1',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-01',
                            'avfan_url': 'https://example.com/1',
                        },
                        'AAA-002': {
                            'found': True,
                            'title': 'Filled 2',
                            'actors': ['Actor B'],
                            'release_date': '2024-01-02',
                            'avfan_url': 'https://example.com/2',
                        },
                    }
                ),
                progress_tracker=tracker,
            )

            result = service.enrich_next_prefixes(2)

        self.assertEqual(tracker.starts[0]['total_count'], 2)
        self.assertEqual(tracker.starts[0]['count_unit'], '视频')
        self.assertEqual(tracker.updates[-1]['processed_count'], 2)
        self.assertEqual(tracker.updates[-1]['success_count'], 2)
        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['remaining_count'], 0)
        self.assertEqual(result['count_unit'], '视频')

    def test_code_prefix_supplement_writes_all_videos_in_one_batch_across_prefixes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.replace_code_prefix_movies(
                'AAA',
                [self._build_library_movie('AAA-101', 'Need A', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS)],
            )
            db.replace_code_prefix_movies(
                'BBB',
                [self._build_library_movie('BBB-101', 'Need B', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS)],
            )
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-101': {'found': True, 'title': 'Filled A', 'actors': ['Actor A'], 'release_date': '2024-01-01'},
                    'BBB-101': {'found': True, 'title': 'Filled B', 'actors': ['Actor B'], 'release_date': '2024-01-02'},
                }
            )
            original_update = db.bulk_update_code_prefix_movies_for_supplement
            with patch.object(db, 'bulk_update_code_prefix_movies_for_supplement', wraps=original_update) as update_mock:
                result = CodePrefixSupplementEnrichmentService(db, scraper=scraper).enrich_next_prefixes(2)

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(update_mock.call_count, 1)
        self.assertEqual(len(update_mock.call_args.args[0]), 2)

    def test_code_prefix_supplement_success_marks_status_completed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-023', 'Need Supplement', '', '2024-01-23', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-023': {
                            'found': True,
                            'title': 'Need Supplement',
                            'actors': ['Actor B'],
                            'release_date': '2024-01-23',
                            'avfan_url': 'https://example.com/23',
                        }
                    }
                ),
            )

            result = service.enrich_next_prefixes(1)
            rows = db.list_code_prefix_movies('AAA')

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(rows[0]['supplement_enrichment_status'], ENRICHED_STATUS)

    def test_code_prefix_supplement_no_result_is_skipped_until_manual_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-030', 'No Search', '', '2024-01-30', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(db, scraper=_FakeScraper())

            first = service.enrich_next_prefixes(1)
            second = service.enrich_next_prefixes(1)
            reset_count = db.reset_code_prefix_enrichments(['AAA'], source_key=SUPPLEMENT_TASK_SOURCE)
            third = service.enrich_next_prefixes(1)

        self.assertEqual(first['processed_count'], 1)
        self.assertEqual(first['failed_count'], 1)
        self.assertEqual(first['remaining_count'], 0)
        self.assertEqual(second['processed_count'], 0)
        self.assertEqual(reset_count, 1)
        self.assertEqual(third['processed_count'], 1)

    def test_code_prefix_supplement_prefers_existing_avfan_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_url={
                    'https://avfan.example/movies/aaa001': {
                        'found': True,
                        'title': 'Filled 1',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://avfan.example/movies/aaa001',
                    },
                }
            )

            movie = self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS)
            movie['avfan_url'] = 'https://avfan.example/movies/aaa001'
            db.replace_code_prefix_movies('AAA', [movie])

            service = CodePrefixSupplementEnrichmentService(db, scraper=scraper)
            service.enrich_next_prefixes(1)

        self.assertEqual(scraper.url_calls, ['https://avfan.example/movies/aaa001'])
        self.assertEqual(scraper.code_calls, [])

    def test_code_prefix_supplement_skips_javtxt_filtered_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-001': {
                        'found': True,
                        'title': 'Filled Visible',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://example.com/1',
                    },
                }
            )

            db.replace_code_prefix_movies(
                'SKIP',
                [
                    self._build_library_movie('SKIP-001', 'Filtered Video', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-001', 'Visible Video', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(
                db,
                scraper=scraper,
                filter_settings={
                    'rules': {
                        'code': ['SKIP'],
                        'title': [],
                        'javtxt_tags': [],
                        'co_star_code': [],
                    }
                },
            )

            result = service.enrich_next_prefixes(10)

        self.assertEqual(scraper.code_calls, ['AAA-001'])
        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['remaining_count'], 0)

    def test_code_prefix_supplement_limit_is_applied_by_video_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-003', 'No Search 3', '', '2024-01-03', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-001': {
                            'found': True,
                            'title': 'Filled 1',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-01',
                            'avfan_url': 'https://example.com/1',
                        },
                        'AAA-002': {
                            'found': True,
                            'title': 'Filled 2',
                            'actors': ['Actor B'],
                            'release_date': '2024-01-02',
                            'avfan_url': 'https://example.com/2',
                        },
                        'AAA-003': {
                            'found': True,
                            'title': 'Filled 3',
                            'actors': ['Actor C'],
                            'release_date': '2024-01-03',
                            'avfan_url': 'https://example.com/3',
                        },
                    }
                ),
            )

            result = service.enrich_next_prefixes(2)

        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['remaining_count'], 1)

    def test_code_prefix_supplement_stop_takes_effect_within_current_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-001': {
                        'found': True,
                        'title': 'Filled 1',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://example.com/1',
                    },
                    'AAA-002': {
                        'found': True,
                        'title': 'Filled 2',
                        'actors': ['Actor B'],
                        'release_date': '2024-01-02',
                        'avfan_url': 'https://example.com/2',
                    },
                },
            )
            db.replace_code_prefix_movies(
                'AAA',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = CodePrefixSupplementEnrichmentService(
                db,
                scraper=scraper,
                should_stop=lambda: len(scraper.code_calls) >= 1,
            )

            result = service.enrich_next_prefixes(10)

        self.assertTrue(result['stopped'])
        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['remaining_count'], 1)

    def test_code_prefix_remaining_count_uses_flat_movie_scan(self):
        class FakeDatabase:
            @staticmethod
            def list_all_code_prefix_movies():
                return [
                    {
                        'prefix': 'AAA',
                        'code': 'AAA-001',
                        'title': 'Visible Missing Actor',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2024-01-01',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'm1',
                        'javtxt_url': 'https://example.com/1',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2024-01-01',
                        'supplement_enrichment_status': '',
                    },
                    {
                        'prefix': 'AAA',
                        'code': 'AAA-002',
                        'title': 'Complete',
                        'author': 'Actor B',
                        'author_raw': 'Actor B',
                        'release_date': '2024-01-02',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'm2',
                        'javtxt_url': 'https://example.com/2',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2024-01-02',
                        'supplement_enrichment_status': ENRICHED_STATUS,
                    },
                ]

            @staticmethod
            def list_code_prefix_movies(prefix):
                raise AssertionError('should not fall back to per-prefix scans')

        service = CodePrefixSupplementEnrichmentService(FakeDatabase())

        self.assertEqual(service._remaining_video_count(), 1)

    def test_actor_supplement_reports_video_progress_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            tracker = _FakeProgressTracker()

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-001': {
                            'found': True,
                            'title': 'Filled 1',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-01',
                            'avfan_url': 'https://example.com/1',
                        },
                        'AAA-002': {
                            'found': True,
                            'title': 'Filled 2',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-02',
                            'avfan_url': 'https://example.com/2',
                        },
                    }
                ),
                progress_tracker=tracker,
            )

            result = service.enrich_next_actors(2)

        self.assertEqual(tracker.starts[0]['total_count'], 2)
        self.assertEqual(tracker.starts[0]['count_unit'], '视频')
        self.assertEqual(tracker.updates[-1]['processed_count'], 2)
        self.assertEqual(tracker.updates[-1]['success_count'], 2)
        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['remaining_count'], 0)
        self.assertEqual(result['count_unit'], '视频')

    def test_actor_supplement_success_marks_status_completed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-024', 'Need Supplement', '', '2024-01-24', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-024': {
                            'found': True,
                            'title': 'Need Supplement',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-24',
                            'avfan_url': 'https://example.com/24',
                        }
                    }
                ),
            )

            result = service.enrich_next_actors(1)
            rows = db.list_actor_movies('Actor A')

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(rows[0]['supplement_enrichment_status'], ENRICHED_STATUS)

    def test_actor_supplement_no_result_is_skipped_until_manual_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-040', 'No Search', '', '2024-02-01', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(db, scraper=_FakeScraper())

            first = service.enrich_next_actors(1)
            second = service.enrich_next_actors(1)
            reset_count = db.reset_actor_enrichments(['Actor A'], source_key=SUPPLEMENT_TASK_SOURCE)
            third = service.enrich_next_actors(1)

        self.assertEqual(first['processed_count'], 1)
        self.assertEqual(first['failed_count'], 1)
        self.assertEqual(first['remaining_count'], 0)
        self.assertEqual(second['processed_count'], 0)
        self.assertEqual(reset_count, 1)
        self.assertEqual(third['processed_count'], 1)

    def test_actor_supplement_prefers_existing_avfan_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_url={
                    'https://avfan.example/movies/aaa001': {
                        'found': True,
                        'title': 'Filled 1',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://avfan.example/movies/aaa001',
                    },
                }
            )

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            movie = self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS)
            movie['avfan_url'] = 'https://avfan.example/movies/aaa001'
            db.replace_actor_movies('Actor A', [movie])

            service = ActorSupplementEnrichmentService(db, scraper=scraper)
            service.enrich_next_actors(1)

        self.assertEqual(scraper.url_calls, ['https://avfan.example/movies/aaa001'])
        self.assertEqual(scraper.code_calls, [])

    def test_actor_supplement_skips_javtxt_filtered_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-001': {
                        'found': True,
                        'title': 'Filled Visible',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://example.com/1',
                    },
                }
            )

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('SKIP-001', 'Filtered Video', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-001', 'Visible Video', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=scraper,
                filter_settings={
                    'rules': {
                        'code': ['SKIP'],
                        'title': [],
                        'javtxt_tags': [],
                        'co_star_code': [],
                    }
                },
            )

            result = service.enrich_next_actors(10)

        self.assertEqual(scraper.code_calls, ['AAA-001'])
        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['remaining_count'], 0)

    def test_actor_supplement_limit_is_applied_by_video_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-003', 'No Search 3', '', '2024-01-03', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-001': {
                            'found': True,
                            'title': 'Filled 1',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-01',
                            'avfan_url': 'https://example.com/1',
                        },
                        'AAA-002': {
                            'found': True,
                            'title': 'Filled 2',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-02',
                            'avfan_url': 'https://example.com/2',
                        },
                        'AAA-003': {
                            'found': True,
                            'title': 'Filled 3',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-03',
                            'avfan_url': 'https://example.com/3',
                        },
                    }
                ),
            )

            result = service.enrich_next_actors(2)

        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['remaining_count'], 1)

    def test_actor_supplement_batch_mode_uses_fast_remaining_probe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-003', 'No Search 3', '', '2024-01-03', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=_FakeScraper(
                    payload_by_code={
                        'AAA-001': {
                            'found': True,
                            'title': 'Filled 1',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-01',
                            'avfan_url': 'https://example.com/1',
                        },
                        'AAA-002': {
                            'found': True,
                            'title': 'Filled 2',
                            'actors': ['Actor A'],
                            'release_date': '2024-01-02',
                            'avfan_url': 'https://example.com/2',
                        },
                    }
                ),
            )

            result = service.enrich_next_actors(2, estimate_remaining=True)

        self.assertTrue(result['has_more_pending'])
        self.assertEqual(result['remaining_count'], 1)

    def test_actor_supplement_stop_takes_effect_within_current_actor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            scraper = _FakeScraper(
                payload_by_code={
                    'AAA-001': {
                        'found': True,
                        'title': 'Filled 1',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-01',
                        'avfan_url': 'https://example.com/1',
                    },
                    'AAA-002': {
                        'found': True,
                        'title': 'Filled 2',
                        'actors': ['Actor A'],
                        'release_date': '2024-01-02',
                        'avfan_url': 'https://example.com/2',
                    },
                },
            )

            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, '', '', 0)",
                    ('Actor A',),
                )
                conn.commit()

            db.replace_actor_movies(
                'Actor A',
                [
                    self._build_library_movie('AAA-001', 'No Search 1', '', '2024-01-01', NO_SEARCH_RESULTS_STATUS),
                    self._build_library_movie('AAA-002', 'No Search 2', '', '2024-01-02', NO_SEARCH_RESULTS_STATUS),
                ],
            )
            service = ActorSupplementEnrichmentService(
                db,
                scraper=scraper,
                should_stop=lambda: len(scraper.code_calls) >= 1,
            )

            result = service.enrich_next_actors(10)

        self.assertTrue(result['stopped'])
        self.assertEqual(result['processed_count'], 1)
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['remaining_count'], 1)

    def test_actor_remaining_count_uses_flat_movie_scan(self):
        class FakeDatabase:
            @staticmethod
            def list_all_actor_movies():
                return [
                    {
                        'actor_name': 'Actor A',
                        'code': 'AAA-001',
                        'title': 'Visible Missing Actor',
                        'author': '',
                        'author_raw': '',
                        'release_date': '2024-01-01',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'm1',
                        'javtxt_url': 'https://example.com/1',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2024-01-01',
                        'supplement_enrichment_status': '',
                    },
                    {
                        'actor_name': 'Actor B',
                        'code': 'AAA-002',
                        'title': 'Complete',
                        'author': 'Actor B',
                        'author_raw': 'Actor B',
                        'release_date': '2024-01-02',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'javtxt_movie_id': 'm2',
                        'javtxt_url': 'https://example.com/2',
                        'javtxt_tags': '',
                        'javtxt_release_date': '2024-01-02',
                        'supplement_enrichment_status': ENRICHED_STATUS,
                    },
                ]

            @staticmethod
            def list_actors():
                raise AssertionError('should not fall back to per-actor scans')

            @staticmethod
            def list_actor_movies(actor_name):
                raise AssertionError('should not fall back to per-actor scans')

        service = ActorSupplementEnrichmentService(FakeDatabase())

        self.assertEqual(service._remaining_video_count(), 1)

    @staticmethod
    def _insert_processed_video(
        db_path,
        *,
        code,
        title,
        release_date,
        javtxt_status,
        author='',
        avfan_movie_id='',
        javtxt_movie_id='',
        javtxt_url='',
        javtxt_title='',
        javtxt_actors='',
        javtxt_actors_raw='',
        javtxt_release_date='',
    ):
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute(
                '''
                INSERT INTO video_entities (
                    code,
                    title,
                    author,
                    release_date,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_actors_raw,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_release_date,
                    javtxt_enrichment_status,
                    avfan_movie_id,
                    avfan_enrichment_status,
                    enrichment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '未补全', '未补全')
                ''',
                (
                    code,
                    title,
                    author,
                    release_date,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_actors_raw,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_release_date,
                    javtxt_status,
                    avfan_movie_id,
                ),
            )
            conn.commit()

    @staticmethod
    def _build_library_movie(code, title, author, release_date, status, movie_id='', url=''):
        return {
            'code': code,
            'title': title,
            'author': author if status == ENRICHED_STATUS else '',
            'author_raw': author if status == ENRICHED_STATUS else '',
            'release_date': release_date,
            'avfan_url': '',
            'page_number': 1,
            'javtxt_enrichment_status': status,
            'javtxt_movie_id': movie_id,
            'javtxt_url': url,
            'javtxt_tags': '',
            'javtxt_release_date': release_date,
            'video_category': '',
            'prefix': code.split('-', 1)[0],
            'actor_name': author,
        }


if __name__ == '__main__':
    unittest.main()
