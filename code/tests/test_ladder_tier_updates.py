import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_ENTITY_CODE_PREFIX,
    ladder_tier_sort_key,
    normalize_ladder_tier,
)
from app.data.database_handler import VideoDatabase
from app.services.detail import ActorDetailLibrary, CodePrefixDetailLibrary


class LadderTierUpdateTest(unittest.TestCase):
    def test_normalize_ladder_tier_accepts_d(self):
        self.assertEqual(normalize_ladder_tier('d'), 'D')

    def test_ladder_tier_sort_key_places_d_after_c(self):
        self.assertGreater(ladder_tier_sort_key('D'), ladder_tier_sort_key('C'))

    def test_save_ladder_entry_overwrites_existing_actor_tier_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Actor A', 'A')
            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Actor A', 'D')

            entries = db.list_ladder_entries(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['entity_name'], 'Actor A')
        self.assertEqual(entries[0]['tier'], 'D')

    def test_actor_detail_reads_latest_ladder_tier(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, ?)",
                    ('Actor A', '', '', 1),
                )
                conn.commit()
            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Actor A', 'A')
            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, 'Actor A', 'D')

            detail = ActorDetailLibrary(db).get_actor_detail('Actor A')

            self.assertEqual(detail['ladder_tier'], 'D')

            del detail
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_code_prefix_detail_reads_latest_ladder_tier(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.import_local_videos(
                [
                    {
                        'code': 'NEM-001',
                        'storage_location': 'D:\\videos',
                        'size': '1GB',
                    }
                ]
            )
            db.save_ladder_entry(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, 'NEM', 'B')
            db.save_ladder_entry(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, 'NEM', 'D')

            detail = CodePrefixDetailLibrary(db).get_prefix_detail('NEM')

        self.assertEqual(detail['ladder_tier'], 'D')


if __name__ == '__main__':
    unittest.main()
