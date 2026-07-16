import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE
from app.core.enrichment_status import ENRICHED_STATUS, UNENRICHED_STATUS
from app.core.video_filter_rules import (
    FILTER_FIELD_CODE,
    FILTER_FIELD_JAVTXT_TAGS,
    FILTER_FIELD_TITLE,
    RuleSet,
)
from app.data.database_handler import VideoDatabase


class RuleSetContractTest(unittest.TestCase):
    def test_normalize_fingerprint_is_stable_and_deduplicates_rules(self):
        first = RuleSet.normalize(
            {
                'rules': {
                    FILTER_FIELD_CODE: [' aaa ', 'AAA'],
                    FILTER_FIELD_TITLE: ['collection'],
                    FILTER_FIELD_JAVTXT_TAGS: [],
                }
            }
        )
        second = RuleSet.normalize(
            {
                'rules': {
                    FILTER_FIELD_CODE: ['AAA'],
                    FILTER_FIELD_TITLE: ['collection'],
                    FILTER_FIELD_JAVTXT_TAGS: [],
                }
            }
        )

        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(first.rules[FILTER_FIELD_CODE], ('aaa',))

    def test_compile_sql_pushes_safe_text_and_prefix_rules_but_keeps_vr_residual(self):
        ruleset = RuleSet.normalize(
            {
                'rules': {
                    FILTER_FIELD_CODE: ['SDDE'],
                    FILTER_FIELD_TITLE: ['collection', 'VR'],
                    FILTER_FIELD_JAVTXT_TAGS: ['featured'],
                }
            }
        )

        where_sql, parameters = ruleset.compile_sql('p')

        self.assertIn('p.title', where_sql)
        self.assertIn('p.javtxt_tags', where_sql)
        self.assertIn('p.code', where_sql)
        self.assertTrue(any('collection' in str(value) for value in parameters))
        self.assertTrue(any('featured' in str(value) for value in parameters))
        self.assertNotIn('VR', parameters)

    def test_apply_residual_preserves_post_enrichment_and_vr_semantics(self):
        ruleset = RuleSet.normalize(
            {
                'rules': {
                    FILTER_FIELD_CODE: ['SDDE'],
                    FILTER_FIELD_TITLE: ['VR'],
                    FILTER_FIELD_JAVTXT_TAGS: [],
                }
            }
        )

        visible = ruleset.apply_residual(
            [
                {'code': 'SDDE-001', 'title': '普通标题', 'javtxt_enrichment_status': ENRICHED_STATUS},
                {'code': 'SDDE-002', 'title': '普通标题', 'javtxt_enrichment_status': UNENRICHED_STATUS},
                {'code': 'AAA-003', 'title': 'V R 作品', 'javtxt_url': 'https://example.com/3'},
            ]
        )

        self.assertEqual([row['code'] for row in visible], ['SDDE-002'])

    def test_filtered_sql_query_keeps_rows_matched_only_by_vr_residual_rule(self):
        ruleset = RuleSet.normalize(
            {
                'rules': {
                    FILTER_FIELD_TITLE: ['collection', 'VR'],
                }
            }
        )

        where_sql, _parameters = ruleset.compile_sql('p', visibility='filtered')

        self.assertNotIn('p.title', where_sql)
        self.assertIn('p.javtxt_enrichment_status', where_sql)


class RuleSetDatabaseFilteringTest(unittest.TestCase):
    def test_video_summary_query_accepts_ruleset_and_returns_only_visible_rows(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            database = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, release_date, javtxt_enrichment_status,
                        javtxt_tags, javtxt_url
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('SDDE-001', 'ordinary title', '2024-01-01', ENRICHED_STATUS, '', 'https://example.com/1'),
                        ('AAA-002', 'ordinary title', '2024-01-02', ENRICHED_STATUS, '', 'https://example.com/2'),
                    ],
                )
                conn.commit()

            ruleset = RuleSet.normalize({'rules': {FILTER_FIELD_CODE: ['SDDE']}})
            rows = database.list_video_summary_rows(rule_set=ruleset)

            self.assertEqual([row['code'] for row in rows], ['AAA-002'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_web_movie_queries_accept_ruleset_without_loading_hidden_rows(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            database = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO actor_movies (
                        actor_name, code, title, javtxt_enrichment_status, javtxt_tags, javtxt_url
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('Actor A', 'SDDE-001', 'ordinary title', ENRICHED_STATUS, '', 'https://example.com/1'),
                        ('Actor A', 'AAA-002', 'ordinary title', ENRICHED_STATUS, '', 'https://example.com/2'),
                    ],
                )
                conn.executemany(
                    '''
                    INSERT INTO code_prefix_movies (
                        prefix, code, title, javtxt_enrichment_status, javtxt_tags, javtxt_url
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        ('SDDE', 'SDDE-001', 'ordinary title', ENRICHED_STATUS, '', 'https://example.com/1'),
                        ('AAA', 'AAA-002', 'ordinary title', ENRICHED_STATUS, '', 'https://example.com/2'),
                    ],
                )
                conn.commit()

            ruleset = RuleSet.normalize({'rules': {FILTER_FIELD_CODE: ['SDDE']}})
            actor_rows = database.list_actor_movies_by_names(['Actor A'], rule_set=ruleset)
            prefix_rows = database.list_code_prefix_movies_by_prefixes(['SDDE', 'AAA'], rule_set=ruleset)

            self.assertEqual([row['code'] for row in actor_rows['Actor A']], ['AAA-002'])
            self.assertEqual([row['code'] for row in prefix_rows['AAA']], ['AAA-002'])
            self.assertEqual(prefix_rows['SDDE'], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_video_enrichment_query_pushes_pre_enrichment_rules_into_sql(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            database = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code, title, avfan_enrichment_status, javtxt_enrichment_status
                    ) VALUES (?, ?, ?, ?)
                    ''',
                    [
                        ('AAA-001', 'ordinary title', UNENRICHED_STATUS, ENRICHED_STATUS),
                        ('AAA-002', 'skip this title', UNENRICHED_STATUS, ENRICHED_STATUS),
                    ],
                )
                conn.commit()

            ruleset = RuleSet.normalize(
                {'rules': {FILTER_FIELD_TITLE: ['skip']}},
                scope='pre_enrichment',
            )
            rows = database.list_videos_for_enrichment(
                10,
                AVFAN_VIDEO_SOURCE,
                candidate_filter=lambda _row: True,
                rule_set=ruleset,
            )

            self.assertEqual([row['code'] for row in rows], ['AAA-001'])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
