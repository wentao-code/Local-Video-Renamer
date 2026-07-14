import sqlite3
import shutil
import tempfile
import unittest
import os
from pathlib import Path

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE
from app.core.ladder_board import LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR
from app.backend.service import BackendService
from app.data.database_handler import VideoDatabase
from app.services.video import VIDEO_CATEGORY_CO_STAR


class MasterpieceLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
        self.original_avfan_base_url = os.environ.get('AVFAN_BASE_URL')
        os.environ['AVFAN_BASE_URL'] = 'https://avfan.example'
        self.db = VideoDatabase(self.db_path)
        self._insert_video(
            code='PFSA-001',
            title='Perfect First Scene',
            author='Alice',
            javtxt_url='https://example.com/pfsa-001',
            javtxt_tags='剧情,新人',
            supplement_status='pending',
        )

    def tearDown(self):
        self.db = None
        if self.original_avfan_base_url is None:
            os.environ.pop('AVFAN_BASE_URL', None)
        else:
            os.environ['AVFAN_BASE_URL'] = self.original_avfan_base_url
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _insert_video(
        self,
        code,
        title,
        author,
        javtxt_url='',
        javtxt_tags='',
        supplement_status='',
        video_category='鍗曚綋',
        release_date='2024-05-01',
    ):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    duration,
                    size,
                    storage_location,
                    avfan_movie_id,
                    release_date,
                    maker,
                    publisher,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_tags,
                    javtxt_release_date,
                    video_category,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    supplement_enrichment_status,
                    supplement_enrichment_error,
                    supplement_enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    code,
                    title,
                    author,
                    '01:30:00',
                    '3.20',
                    r'D:\videos',
                    'avfan-001',
                    release_date,
                    'Maker A',
                    'Publisher A',
                    'javtxt-001',
                    javtxt_url,
                    title,
                    author,
                    javtxt_tags,
                    '2024-05-02',
                    '单体',
                    '已补全',
                    '已补全',
                    supplement_status,
                    '',
                    '2026-07-06 00:00:00',
                ),
            )
            conn.commit()

    def _replace_code_prefix_movies(self, prefix, movies):
        self.db.replace_code_prefix_movies(prefix, movies)

    def _replace_actor_movies(self, actor_name, movies):
        self.db.replace_actor_movies(actor_name, movies)

    def _update_processed_video_author(self, code, author, release_date='2024-05-01'):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                UPDATE processed_videos
                SET author = ?, javtxt_actors = ?, release_date = ?, javtxt_release_date = ?
                WHERE code = ?
                ''',
                (author, author, release_date, release_date, code),
            )
            conn.commit()

    def _insert_collaboration_video(self, code, author, release_date):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    duration,
                    size,
                    storage_location,
                    avfan_movie_id,
                    release_date,
                    maker,
                    publisher,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_tags,
                    javtxt_release_date,
                    video_category,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    supplement_enrichment_status,
                    supplement_enrichment_error,
                    supplement_enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    code,
                    code,
                    author,
                    '01:10:00',
                    '2.10',
                    r'D:\videos',
                    '',
                    release_date,
                    '',
                    '',
                    '',
                    '',
                    code,
                    author,
                    '',
                    release_date,
                    VIDEO_CATEGORY_CO_STAR,
                    '',
                    '',
                    '',
                    '',
                    '',
                ),
            )
            conn.commit()

    def test_add_masterpiece_entry_lists_video_and_normalizes_medals(self):
        entry = self.db.add_masterpiece_entry('pfsa-001')
        self.assertEqual(entry['code'], 'PFSA-001')
        self.assertEqual(entry['title'], 'Perfect First Scene')
        self.assertEqual(entry['author'], 'Alice')
        self.assertEqual(entry['medal'], '')
        self.assertEqual(entry['medals'], [])

        updated = self.db.update_masterpiece_entry_medal('PFSA-001', '年度新人, 白金常青\n年度新人')
        self.assertEqual(updated['medal'], '年度新人\n白金常青')
        self.assertEqual(updated['medals'], ['年度新人', '白金常青'])

        rows = self.db.list_masterpiece_entries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], 'PFSA-001')
        self.assertEqual(rows[0]['medal'], '年度新人\n白金常青')
        self.assertEqual(rows[0]['medals'], ['年度新人', '白金常青'])
        self.assertEqual(rows[0]['avfan_enrichment_status'], '已补全')
        self.assertEqual(rows[0]['javtxt_enrichment_status'], '已补全')

    def test_add_masterpiece_entry_requires_existing_video(self):
        with self.assertRaises(ValueError) as context:
            self.db.add_masterpiece_entry('MISS-001')

        self.assertEqual(str(context.exception), '视频不存在: MISS-001')

    def test_add_masterpiece_entry_requires_code(self):
        with self.assertRaises(ValueError) as context:
            self.db.add_masterpiece_entry('')

        self.assertEqual(str(context.exception), '缺少视频编号')

    def test_backend_masterpiece_missing_detail_error_is_readable(self):
        class MissingDetailDatabase:
            def get_masterpiece_detail_record(self, _code):
                return {}

        service = object.__new__(BackendService)
        service.db = MissingDetailDatabase()
        service.ensure_database_loaded = lambda: None

        with self.assertRaises(FileNotFoundError) as context:
            service.get_masterpiece_detail('RCTD-729')

        self.assertEqual(str(context.exception), '名作堂详情不存在: RCTD-729')

    def test_add_masterpiece_entry_accepts_actor_library_only_match(self):
        self._replace_actor_movies(
            'Actor Only',
            [
                {
                    'code': 'act-002',
                    'title': 'Actor Library Story',
                    'author': 'Actor Only',
                    'release_date': '2024-04-02',
                    'javtxt_url': 'https://javtxt.example/act-002',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('act002')
        detail = self.db.get_masterpiece_detail_record('ACT-002')

        self.assertEqual(entry['code'], 'ACT-002')
        self.assertEqual(entry['title'], 'Actor Library Story')
        self.assertEqual(entry['author'], 'Actor Only')
        self.assertEqual(entry['primary_source'], 'actor_library')
        self.assertEqual(detail['primary_source'], 'actor_library')
        self.assertEqual(len(detail['references']), 1)
        self.assertEqual(detail['references'][0]['reference_source'], 'actor_library')
        self.assertEqual(detail['references'][0]['reference_key'], 'Actor Only')

    def test_add_masterpiece_entry_accepts_code_prefix_library_only_match(self):
        self._replace_code_prefix_movies(
            'IPX',
            [
                {
                    'code': 'ipx001',
                    'title': 'Prefix Library Story',
                    'author': 'Prefix Actor',
                    'release_date': '2024-03-01',
                    'avfan_url': 'https://avfan.example/movies/prefix-001',
                    'javtxt_url': 'https://javtxt.example/ipx-001',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('IPX-001')
        detail = self.db.get_masterpiece_detail_record('IPX-001')

        self.assertEqual(entry['code'], 'IPX-001')
        self.assertEqual(entry['title'], 'Prefix Library Story')
        self.assertEqual(entry['author'], 'Prefix Actor')
        self.assertEqual(entry['primary_source'], 'code_prefix_library')
        self.assertEqual(detail['primary_detail_url'], 'https://avfan.example/movies/prefix-001')
        self.assertEqual(len(detail['references']), 1)
        self.assertEqual(detail['references'][0]['reference_source'], 'code_prefix_library')
        self.assertEqual(detail['references'][0]['reference_key'], 'IPX')

    def test_add_masterpiece_entry_persists_all_library_references_and_primary_priority(self):
        self._replace_code_prefix_movies(
            'PFSA',
            [
                {
                    'code': 'PFSA001',
                    'title': 'Prefix Copy',
                    'author': 'Prefix Actor',
                    'release_date': '2024-04-01',
                    'avfan_url': 'https://avfan.example/movies/prefix-copy',
                }
            ],
        )
        self._replace_actor_movies(
            'Actor A',
            [
                {
                    'code': 'PFSA-001',
                    'title': 'Actor Copy',
                    'author': 'Actor Copy',
                    'release_date': '2024-04-03',
                    'javtxt_url': 'https://javtxt.example/pfsa-001',
                }
            ],
        )

        entry = self.db.add_masterpiece_entry('PFSA001')
        rows = self.db.list_masterpiece_entries()
        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual(entry['primary_source'], 'video_library')
        self.assertEqual(entry['primary_detail_url'], 'https://avfan.example/movies/avfan-001')
        self.assertEqual(rows[0]['title'], 'Perfect First Scene')
        self.assertEqual(rows[0]['author'], 'Alice')
        self.assertEqual(rows[0]['primary_source'], 'video_library')
        self.assertEqual(detail['display_title'], 'Perfect First Scene')
        self.assertEqual(detail['display_author'], 'Alice')
        self.assertEqual(detail['primary_source'], 'video_library')
        self.assertEqual(detail['primary_detail_url'], 'https://avfan.example/movies/avfan-001')
        self.assertEqual(
            [row['reference_source'] for row in detail['references']],
            ['video_library', 'code_prefix_library', 'actor_library'],
        )

    def test_add_masterpiece_entry_registers_missing_actor_without_auto_admitting_until_marked(self):
        self._update_processed_video_author('PFSA-001', 'Alice Beta', release_date='2024-05-01')
        self.db.add_actor('Alice')
        self.db.save_binghuo_actor_profile(
            'Alice',
            '已补全',
            birthday='2000-04-10',
            age='24',
            height='168',
            bust='88',
            waist='59',
            hip='89',
            cup='E',
            measurements_raw='B88(E) W59 H89',
        )

        self.db.add_masterpiece_entry('PFSA-001')
        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual([row['actor_name'] for row in detail['actor_details']], ['Alice', 'Beta'])
        self.assertEqual(detail['actor_details'][0]['appearance_age'], '24')
        self.assertEqual(detail['actor_details'][0]['height'], '168')
        self.assertEqual(detail['actor_details'][0]['cup'], 'E')
        self.assertEqual(detail['actor_details'][0]['measurements_raw'], 'B88(E) W59 H89')
        self.assertEqual(detail['actor_details'][0]['actor_exists_in_library'], 1)
        self.assertEqual(detail['actor_details'][1]['actor_exists_in_library'], 0)
        self.assertFalse(any(row['name'] == 'Beta' for row in self.db.list_actors('Beta')))

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                '''
                SELECT actor_name, status, handle_mark
                FROM masterpiece_actors
                ORDER BY actor_name
                '''
            ).fetchall()
            self.assertEqual(rows, [('Alice', 1, 0), ('Beta', 0, 0)])
            conn.execute(
                '''
                UPDATE masterpiece_actors
                SET handle_mark = 1
                WHERE actor_name = ?
                ''',
                ('Beta',),
            )
            conn.commit()

        self.db.add_masterpiece_entry('PFSA-001')

        with sqlite3.connect(self.db_path) as conn:
            beta_row = conn.execute(
                '''
                SELECT actor_name, status, handle_mark
                FROM masterpiece_actors
                WHERE actor_name = ?
                ''',
                ('Beta',),
            ).fetchone()
        self.assertEqual(beta_row, ('Beta', 1, 1))
        self.assertTrue(any(row['name'] == 'Beta' for row in self.db.list_actors('Beta')))

    def test_masterpiece_actor_handle_mark_two_hides_actor_from_detail(self):
        self._update_processed_video_author('PFSA-001', 'Alice Beta', release_date='2024-05-01')
        self.db.add_actor('Alice')
        self.db.add_masterpiece_entry('PFSA-001')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                UPDATE masterpiece_actors
                SET handle_mark = 2
                WHERE actor_name = ?
                ''',
                ('Beta',),
            )
            conn.commit()

        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual([row['actor_name'] for row in detail['actor_details']], ['Alice'])
        self.assertNotIn(
            'Beta',
            [row['actor_name'] for section in detail['collaborator_sections'] for row in section['collaborators']],
        )

    def test_masterpiece_detail_backfills_registered_actor_table_for_existing_library_actor(self):
        self._update_processed_video_author('PFSA-001', 'Alice Beta', release_date='2024-05-01')
        self.db.add_actor('Alice')
        self.db.add_masterpiece_entry('PFSA-001')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                DELETE FROM masterpiece_actors
                WHERE actor_name = ?
                ''',
                ('Alice',),
            )
            conn.commit()

        self.db.get_masterpiece_detail_record('PFSA-001')

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                '''
                SELECT actor_name, status, handle_mark
                FROM masterpiece_actors
                WHERE actor_name = ?
                ''',
                ('Alice',),
            ).fetchone()
        self.assertEqual(row, ('Alice', 1, 0))

    def test_masterpiece_actor_details_include_full_actor_basic_snapshot(self):
        self._update_processed_video_author('PFSA-001', 'Alice', release_date='2026-06-01')
        self._insert_video('ALC-002', 'Alice Local 2', 'Alice', release_date='2026-06-15')
        self.db.add_actor('Alice', birthday='2000-04-10', age='24')
        self.db.save_actor_enrichment(
            'Alice',
            '已补全',
            total_videos=915,
            actor_id='avfan-1',
        )
        self.db.save_binghuo_actor_profile(
            'Alice',
            '已补全',
            person_id='binghuo-1',
            birthday='2000-04-10',
            age='24',
            height='168',
            bust='88',
            waist='59',
            hip='89',
            cup='E',
            measurements_raw='B88(E) W59 H89',
        )
        self._replace_actor_movies(
            'Alice',
            [
                {
                    'code': 'PFSA-001',
                    'title': 'Perfect First Scene',
                    'author': 'Alice',
                    'release_date': '2026-06-01',
                    'javtxt_release_date': '2026-06-01',
                    'javtxt_enrichment_status': '已补全',
                    'javtxt_movie_id': 'pfsa',
                    'javtxt_url': 'https://example.com/pfsa',
                    'video_category': '单体',
                },
                {
                    'code': 'ALC-002',
                    'title': 'Alice Web 2',
                    'author': 'Alice',
                    'release_date': '2026-06-15',
                    'javtxt_release_date': '2026-06-15',
                    'javtxt_enrichment_status': '已补全',
                    'javtxt_movie_id': 'alc',
                    'javtxt_url': 'https://example.com/alc',
                    'video_category': '单体',
                },
            ],
        )
        self._replace_code_prefix_movies('PFSA', [{'code': 'PFSA-001', 'title': 'Prefix Copy', 'author': 'Alice'}])
        self.db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Alice', 'S')

        self.db.add_masterpiece_entry('PFSA-001')
        detail = self.db.get_masterpiece_detail_record('PFSA-001')
        actor = detail['actor_details'][0]

        self.assertEqual(actor['actor_id'], 'avfan-1')
        self.assertEqual(actor['binghuo_person_id'], 'binghuo-1')
        self.assertEqual(actor['update_status'], 'active')
        self.assertEqual(actor['local_video_count'], 2)
        self.assertEqual(actor['web_total_videos'], 915)
        self.assertEqual(actor['appearance_code_count'], 2)
        self.assertEqual(actor['code_prefix_library_count'], 1)
        self.assertEqual(actor['web_update_frequency']['video_count'], 2)
        self.assertIn('天限阁', actor['web_enrichment_status'])

    def test_actor_library_only_entry_uses_actor_library_names_for_actor_snapshots(self):
        self.db.add_actor('Actor Only')
        self.db.save_baomu_actor_profile(
            'Actor Only',
            '已补全',
            birthday='1998-02-14',
            height='160',
            bust='84',
            waist='57',
            hip='86',
            cup='C',
            measurements_raw='breast=84cm; waist=57cm; hip=86cm; cup=C',
        )
        self._replace_actor_movies(
            'Actor Only',
            [
                {
                    'code': 'ACT-002',
                    'title': 'Actor Library Story',
                    'author': 'Actor Only',
                    'release_date': '2024-04-02',
                    'javtxt_url': 'https://javtxt.example/act-002',
                }
            ],
        )

        self.db.add_masterpiece_entry('ACT-002')
        detail = self.db.get_masterpiece_detail_record('ACT-002')

        self.assertEqual(len(detail['actor_details']), 1)
        self.assertEqual(detail['actor_details'][0]['actor_name'], 'Actor Only')
        self.assertEqual(detail['actor_details'][0]['cup'], 'C')
        self.assertEqual(detail['actor_details'][0]['birthday'], '1998/2/14')

    def test_detail_collects_collaborators_for_s_and_a_tier_actors_only(self):
        self._update_processed_video_author('PFSA-001', 'Alice Beta', release_date='2024-05-01')
        self._insert_collaboration_video('COSTAR-001', 'Alice Carol', '2024-04-01')
        self._insert_collaboration_video('COSTAR-002', 'Alice Dana', '2024-03-01')
        self._insert_collaboration_video('COSTAR-003', 'Alice Carol', '2024-02-01')
        self.db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Alice', 'S')
        self.db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Beta', 'B')

        self.db.add_masterpiece_entry('PFSA-001')
        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual(len(detail['collaborator_sections']), 1)
        self.assertEqual(detail['collaborator_sections'][0]['actor_name'], 'Alice')
        self.assertEqual(detail['collaborator_sections'][0]['ladder_tier'], 'S')
        self.assertEqual(
            detail['collaborator_sections'][0]['collaborators'],
            [
                {'actor_name': 'Carol', 'count': 2},
                {'actor_name': 'Dana', 'count': 1},
            ],
        )

    def test_get_video_detail_record_returns_full_video_fields(self):
        detail = self.db.get_video_detail_record('pfsa-001')
        self.assertEqual(detail['code'], 'PFSA-001')
        self.assertEqual(detail['title'], 'Perfect First Scene')
        self.assertEqual(detail['author'], 'Alice')
        self.assertEqual(detail['javtxt_url'], 'https://example.com/pfsa-001')
        self.assertEqual(detail['javtxt_tags'], '剧情,新人')
        self.assertEqual(detail['supplement_enrichment_status'], 'pending')
        self.assertEqual(detail['maker'], 'Maker A')
        self.assertEqual(detail['publisher'], 'Publisher A')

    def test_masterpiece_detail_exposes_tags_description_and_first_source_duration(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                '''
                UPDATE processed_videos
                SET duration = ?, javtxt_tags = ?, javtxt_description = ?
                WHERE code = ?
                ''',
                ('130 分钟', 'Drama,Newcomer', 'Second source plot description', 'PFSA-001'),
            )
            conn.commit()

        video_detail = self.db.get_video_detail_record('PFSA-001')
        self.assertEqual(video_detail['duration'], '130 分钟')
        self.assertEqual(video_detail['javtxt_tags'], 'Drama,Newcomer')
        self.assertEqual(video_detail['javtxt_description'], 'Second source plot description')

        self.db.add_masterpiece_entry('PFSA-001')
        detail = self.db.get_masterpiece_detail_record('PFSA-001')

        self.assertEqual(detail['display_tags'], 'Drama,Newcomer')
        self.assertEqual(detail['second_source_description'], 'Second source plot description')
        self.assertEqual(detail['first_source_duration'], '130 分钟')

    def test_ensure_masterpiece_enrichment_candidate_creates_processed_video_from_actor_reference(self):
        self._replace_actor_movies(
            'Actor Only',
            [
                {
                    'code': 'ROE-511',
                    'title': 'Actor Reference Title',
                    'author': 'Actor Only',
                    'release_date': '2026-06-18',
                    'avfan_url': 'https://avfan.example/movies/roe-511',
                    'javtxt_movie_id': '547613',
                    'javtxt_url': 'https://javtxt.example/v/547613',
                    'javtxt_tags': '剧情,熟女',
                }
            ],
        )
        self.db.add_masterpiece_entry('ROE-511')

        candidate = self.db.ensure_masterpiece_enrichment_candidate('roe511')
        pending_avfan = self.db.list_videos_for_enrichment(
            10,
            candidate_filter=lambda row: row.get('code') == 'ROE-511',
        )
        pending_javtxt = self.db.list_videos_for_enrichment(
            10,
            JAVTXT_VIDEO_SOURCE,
            candidate_filter=lambda row: row.get('code') == 'ROE-511',
        )
        detail = self.db.get_video_detail_record('ROE-511')

        self.assertEqual(candidate['code'], 'ROE-511')
        self.assertEqual(detail['title'], 'Actor Reference Title')
        self.assertEqual(detail['author'], 'Actor Only')
        self.assertEqual(detail['javtxt_url'], 'https://javtxt.example/v/547613')
        self.assertEqual([row['code'] for row in pending_avfan], ['ROE-511'])
        self.assertEqual([row['code'] for row in pending_javtxt], ['ROE-511'])


if __name__ == '__main__':
    unittest.main()
