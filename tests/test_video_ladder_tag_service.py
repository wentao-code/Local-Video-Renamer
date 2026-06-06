from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_ENTITY_CODE_PREFIX,
)
from app.data.database_handler import VideoDatabase
from app.services.video_ladder_tag_service import VideoLadderTagService


class VideoLadderTagServiceTest(unittest.TestCase):
    def test_enrich_video_rows_splits_actor_and_prefix_medals_into_individual_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {
                        'code': 'IPX-001',
                        'storage_location': 'D:\\videos',
                        'size': '1GB',
                    }
                ]
            )

            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    'UPDATE processed_videos SET author = ? WHERE code = ?',
                    ('演员A 演员B', 'IPX-001'),
                )
                conn.commit()

            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, '演员A', 'S')
            db.save_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, '演员B', 'A')
            db.save_ladder_entry(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, 'IPX', 'S')
            db.update_ladder_entry_medal(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, '演员A', '白金常青树，年度新人')
            db.update_ladder_entry_medal(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, '演员B', '年度新人，封面女王')
            db.update_ladder_entry_medal(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, 'IPX', '神级系列')

            service = VideoLadderTagService(db)
            rows = service.enrich_video_rows(db.list_videos())

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]['ladder_tags'],
            ['白金常青树', '年度新人', '封面女王', '神级系列'],
        )
        self.assertEqual(
            rows[0]['ladder_tag_text'],
            '白金常青树 | 年度新人 | 封面女王 | 神级系列',
        )


if __name__ == '__main__':
    unittest.main()
