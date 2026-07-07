import shutil
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
        first = self.db.add_global_medal('年度新人', '授予新人演员或作品')
        second = self.db.add_global_medal('白金常青', '适合长期稳定的高质量对象')

        self.assertEqual(first['name'], '年度新人')
        self.assertEqual(first['description'], '授予新人演员或作品')
        self.assertEqual(second['name'], '白金常青')

        rows = self.db.list_global_medals()
        self.assertEqual([row['name'] for row in rows], ['年度新人', '白金常青'])

        updated = self.db.update_global_medal_description('年度新人', '更新后的描述')
        self.assertEqual(updated['description'], '更新后的描述')

        self.db.delete_global_medal('白金常青')
        rows = self.db.list_global_medals()
        self.assertEqual([row['name'] for row in rows], ['年度新人'])

    def test_add_global_medal_rejects_duplicate_name(self):
        self.db.add_global_medal('年度新人', '授予新人演员或作品')

        with self.assertRaises(ValueError):
            self.db.add_global_medal('年度新人', '重复')


if __name__ == '__main__':
    unittest.main()
