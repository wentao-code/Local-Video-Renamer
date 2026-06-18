import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.services.detail import ActorDetailLibrary


class ActorProfileDisplayTest(unittest.TestCase):
    def test_list_actors_shows_unknown_age_when_birthday_is_missing_placeholder(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    ('演员A', '暂无', '126'),
                )
                conn.commit()

            rows = db.list_actors('演员A')

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['birthday'], '暂无')
            self.assertEqual(rows[0]['age'], '未知')

            del rows
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_actor_detail_shows_unknown_age_when_birthday_is_missing_placeholder(self):
        actor_row = {
            'name': '演员B',
            'birthday': '暂无',
            'age': '126',
            'matched': True,
            'actor_id': '',
        }

        class FakeDatabase:
            def list_actors(self, search_text=''):
                return [actor_row] if str(search_text or '').strip() in ('', '演员B') else []

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {'tier': 'S'} if entity_name == '演员B' else {}

            def list_videos(self):
                return []

            def list_actor_movies(self, actor_name):
                return []

            def get_actor_enrichment_record(self, actor_name):
                return {}

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = ActorDetailLibrary(FakeDatabase()).get_actor_detail('演员B')

        self.assertEqual(detail['birthday'], '暂无')
        self.assertEqual(detail['age'], '未知')
        self.assertEqual(detail['ladder_tier'], 'S')


if __name__ == '__main__':
    unittest.main()
