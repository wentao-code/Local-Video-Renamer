import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.data.database_handler import VideoDatabase


class GlobalMedalLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'video_database.db'
        self.db = VideoDatabase(self.db_path)

    def tearDown(self):
        self.db = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_update_delete_global_medals(self):
        first = self.db.add_global_medal('年度新人', '授予新人演员或作品', medal_type='age')
        second = self.db.add_global_medal('白金常青', '适合长期稳定的高质量对象', medal_type='special')

        self.assertEqual(first['name'], '年度新人')
        self.assertEqual(first['description'], '授予新人演员或作品')
        self.assertEqual(first['medal_type'], 'age')
        self.assertEqual(second['name'], '白金常青')

        rows = self.db.list_global_medals()
        self.assertEqual([row['name'] for row in rows], ['年度新人', '白金常青'])

        updated = self.db.update_global_medal('年度新人', '更新后的描述', medal_type='body')
        self.assertEqual(updated['description'], '更新后的描述')
        self.assertEqual(updated['medal_type'], 'body')

        self.db.delete_global_medal('白金常青')
        rows = self.db.list_global_medals()
        self.assertEqual([row['name'] for row in rows], ['年度新人'])

    def test_add_global_medal_rejects_duplicate_name(self):
        self.db.add_global_medal('年度新人', '授予新人演员或作品')

        with self.assertRaises(ValueError):
            self.db.add_global_medal('年度新人', '重复')

    def test_lists_medals_in_type_order_and_defaults_existing_rows_to_special(self):
        self.db.add_global_medal('特殊勋章', '特殊', medal_type='special')
        self.db.add_global_medal('发型勋章', '发型', medal_type='hairstyle')
        self.db.add_global_medal('肤色勋章', '肤色', medal_type='skin_tone')
        self.db.add_global_medal('身材勋章', '身材', medal_type='body')
        self.db.add_global_medal('年龄勋章', '年龄', medal_type='age')

        self.assertEqual(
            [row['name'] for row in self.db.list_global_medals()],
            ['年龄勋章', '身材勋章', '肤色勋章', '发型勋章', '特殊勋章'],
        )

    def test_initialization_migrates_legacy_medal_rows_to_special_type(self):
        legacy_path = Path(self.temp_dir) / 'legacy_medals.db'
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                '''
                CREATE TABLE global_medals (
                    name TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            connection.execute(
                "INSERT INTO global_medals (name, description) VALUES ('旧勋章', '旧记录')"
            )

        migrated_database = VideoDatabase(legacy_path)
        rows = migrated_database.list_global_medals()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], '旧勋章')
        self.assertEqual(rows[0]['description'], '旧记录')
        self.assertEqual(rows[0]['medal_type'], 'special')


if __name__ == '__main__':
    unittest.main()
