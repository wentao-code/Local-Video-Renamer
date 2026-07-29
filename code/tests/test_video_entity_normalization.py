import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.data.repositories.video_entity_repo import VideoEntityRepositoryMixin


class VideoEntityNormalizationTest(unittest.TestCase):
    def test_video_entity_writes_are_provided_by_repository(self):
        self.assertIs(VideoDatabase.upsert_video_entity, VideoEntityRepositoryMixin.upsert_video_entity)
        self.assertIs(VideoDatabase.list_actor_movies, VideoEntityRepositoryMixin.list_actor_movies)
        self.assertIs(VideoDatabase.list_actor_movies_by_names, VideoEntityRepositoryMixin.list_actor_movies_by_names)
        self.assertIs(VideoDatabase.list_code_prefix_movies, VideoEntityRepositoryMixin.list_code_prefix_movies)
        self.assertIs(
            VideoDatabase.list_code_prefix_movies_by_prefixes,
            VideoEntityRepositoryMixin.list_code_prefix_movies_by_prefixes,
        )
        self.assertIs(VideoDatabase.replace_actor_movies, VideoEntityRepositoryMixin.replace_actor_movies)
        self.assertIs(VideoDatabase.rebuild_active_video_entities, VideoEntityRepositoryMixin.rebuild_active_video_entities)
        self.assertIs(
            VideoDatabase.list_sql_javtxt_video_candidates,
            VideoEntityRepositoryMixin.list_sql_javtxt_video_candidates,
        )
        self.assertIs(
            VideoDatabase.list_video_supplement_candidates,
            VideoEntityRepositoryMixin.list_video_supplement_candidates,
        )
        self.assertIs(
            VideoDatabase.list_sql_video_supplement_candidates,
            VideoEntityRepositoryMixin.list_sql_video_supplement_candidates,
        )
        self.assertIs(
            VideoDatabase.save_video_supplement_status,
            VideoEntityRepositoryMixin.save_video_supplement_status,
        )
        self.assertIs(
            VideoDatabase.replace_code_prefix_movies,
            VideoEntityRepositoryMixin.replace_code_prefix_movies,
        )
        self.assertIs(VideoDatabase.update_video_enrichment, VideoEntityRepositoryMixin.update_video_enrichment)
        self.assertIs(VideoDatabase.mark_video_enrichment_failed, VideoEntityRepositoryMixin.mark_video_enrichment_failed)
        self.assertIs(VideoDatabase.list_actor_dashboard_stats, VideoEntityRepositoryMixin.list_actor_dashboard_stats)
        self.assertIs(VideoDatabase.list_code_prefix_dashboard_stats, VideoEntityRepositoryMixin.list_code_prefix_dashboard_stats)
        self.assertIs(VideoDatabase.list_videos_for_enrichment, VideoEntityRepositoryMixin.list_videos_for_enrichment)
        self.assertIs(
            VideoDatabase.count_videos_by_enrichment_status,
            VideoEntityRepositoryMixin.count_videos_by_enrichment_status,
        )
        self.assertIs(
            VideoDatabase.count_pending_video_enrichments,
            VideoEntityRepositoryMixin.count_pending_video_enrichments,
        )
        self.assertIs(VideoDatabase.save_javtxt_cache_for_video, VideoEntityRepositoryMixin.save_javtxt_cache_for_video)
        self.assertIs(VideoDatabase.get_video_enrichment_summary, VideoEntityRepositoryMixin.get_video_enrichment_summary)
    def test_new_database_exposes_only_canonical_video_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')

            self.assertFalse(hasattr(db, 'convert_legacy_tables_to_compatibility_views'))
            self.assertFalse(hasattr(db, 'finalize_legacy_schema'))
            self.assertFalse(hasattr(db, 'list_legacy_actor_movies'))
            self.assertFalse(hasattr(db, 'list_legacy_code_prefix_movies'))

            with db._connect() as conn:
                legacy_rows = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE name IN ('processed_videos', 'actor_movies', 'code_prefix_movies')
                    """
                ).fetchall()

            self.assertEqual(legacy_rows, [])

    def test_canonical_entity_preserves_relation_specific_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Canonical title'},
                actor_relations=[{
                    'actor_name': 'Actor A',
                    'avfan_url': 'https://example.test/actor',
                    'avfan_movie_id': 'actor-001',
                    'page_number': 2,
                }],
                prefix_relations=[{
                    'prefix': 'ABC',
                    'avfan_url': 'https://example.test/prefix',
                    'avfan_movie_id': 'prefix-001',
                    'page_number': 3,
                }],
            )

            with closing(sqlite3.connect(db_path)) as conn:
                self.assertEqual(
                    conn.execute('SELECT code, title FROM video_entities').fetchall(),
                    [('ABC-001', 'Canonical title')],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT video_code, actor_name, avfan_url, avfan_movie_id, page_number '
                        'FROM video_actor_relation_meta'
                    ).fetchall(),
                    [('ABC-001', 'Actor A', 'https://example.test/actor', 'actor-001', 2)],
                )
                self.assertEqual(
                    conn.execute(
                        'SELECT video_code, prefix, avfan_url, avfan_movie_id, page_number '
                        'FROM video_prefix_relation_meta'
                    ).fetchall(),
                    [('ABC-001', 'ABC', 'https://example.test/prefix', 'prefix-001', 3)],
                )

    def test_avfan_enrichment_writes_entity_and_local_record_separately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.upsert_video_entity(
                {'code': 'ABC-001', 'title': 'Original'},
                local_record={'duration': '0:01:00', 'storage_location': 'D:/videos/ABC-001.mp4'},
            )

            db.update_video_enrichment(
                'ABC-001',
                {
                    'title': 'Enriched title',
                    'actors': ['Actor A'],
                    'duration': '1:23:45',
                    'avfan_movie_id': 'avfan-001',
                },
                source_key='avfan',
            )

            row = db.list_videos()[0]
            self.assertEqual(row['title'], 'Enriched title')
            self.assertEqual(row['duration'], '1:23:45')
    def test_video_library_reads_only_local_canonical_entities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.upsert_video_entity({'code': 'WEB-001', 'title': 'Web only'})
            db.upsert_video_entity(
                {'code': 'LOC-001', 'title': 'Local'},
                local_record={'storage_location': 'D:/videos/LOC-001.mp4'},
            )

            self.assertEqual([row['code'] for row in db.list_videos()], ['LOC-001'])
            self.assertEqual(db.count_videos(), 1)


if __name__ == '__main__':
    unittest.main()
