import gc
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from datetime import date
from pathlib import Path

from app.core.actor_profile_display import UNKNOWN_ACTOR_AGE_TEXT
from app.data.database_handler import VideoDatabase
from app.services.library import ActorProfileUpdateService, CodePrefixLibrary, LibraryAdminService


class ActorProfileUpdateServiceTest(unittest.TestCase):
    def test_fills_age_from_birthday(self):
        payload = ActorProfileUpdateService().normalize_payload(
            '演员A',
            birthday='2000-06-18',
            age='',
            today=date(2026, 6, 17),
        )

        self.assertEqual(payload['birthday'], '2000-06-18')
        self.assertEqual(payload['age'], '25')

    def test_fills_birthday_from_age_using_july_18(self):
        payload = ActorProfileUpdateService().normalize_payload(
            '演员B',
            birthday='',
            age='20',
            today=date(2026, 6, 17),
        )

        self.assertEqual(payload['birthday'], '2005-07-18')
        self.assertEqual(payload['age'], '20')

    def test_recalculates_age_when_birthday_and_age_disagree(self):
        payload = ActorProfileUpdateService().normalize_payload(
            '演员C',
            birthday='2000-01-01',
            age='18',
            today=date(2026, 6, 17),
        )

        self.assertEqual(payload['age'], '26')

    def test_accepts_slash_birthday_from_display_text(self):
        payload = ActorProfileUpdateService().normalize_payload(
            '演员D',
            birthday='1950/9/14',
            age='',
            today=date(2026, 6, 17),
        )

        self.assertEqual(payload['birthday'], '1950-09-14')
        self.assertEqual(payload['age'], '75')

    def test_treats_unknown_display_age_as_empty(self):
        payload = ActorProfileUpdateService().normalize_payload(
            '演员E',
            birthday='',
            age=UNKNOWN_ACTOR_AGE_TEXT,
            today=date(2026, 6, 17),
        )

        self.assertEqual(payload['birthday'], '')
        self.assertEqual(payload['age'], '')


class ActorLibraryAdminUpdateTest(unittest.TestCase):
    def test_rename_actor_updates_birthday_and_age(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO actors (name, birthday, age, matched) VALUES (?, ?, ?, 1)",
                    ('演员A', '', ''),
                )
                conn.commit()

            updated_count = LibraryAdminService(db).rename_actor('演员A', '演员A', age='20')

            self.assertEqual(updated_count, 1)
            rows = db.list_actors('演员A')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['birthday'], f'{date.today().year - 20}/7/18')
            self.assertEqual(rows[0]['age'], '20')

            with sqlite3.connect(str(db_path)) as conn:
                stored_birthday = conn.execute(
                    'SELECT birthday FROM actors WHERE name = ?',
                    (rows[0]['name'],),
                ).fetchone()[0]
            self.assertEqual(stored_birthday, f'{date.today().year - 20}-07-18')

            del rows
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class LibraryAdminAddTest(unittest.TestCase):
    def test_add_actor_rejects_hidden_actor_name(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT INTO hidden_actors (name) VALUES (?)",
                    ('婕斿憳A',),
                )
                conn.commit()

            with self.assertRaisesRegex(ValueError, '已被删除'):
                LibraryAdminService(db).add_actor('婕斿憳A')
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_add_code_prefix_creates_visible_empty_library_row(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)

            created_count = LibraryAdminService(db).add_code_prefix('ipx')

            self.assertEqual(created_count, 1)
            rows = CodePrefixLibrary(db).list_prefixes()
            self.assertEqual([row['prefix'] for row in rows], ['IPX'])
            self.assertEqual(rows[0]['video_count'], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_add_code_prefix_rejects_existing_visible_prefix(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {
                        'code': 'ABC-001',
                        'storage_location': 'D:/videos/ABC-001.mp4',
                        'duration': '',
                        'size': '',
                    }
                ]
            )

            with self.assertRaisesRegex(ValueError, '已存在'):
                LibraryAdminService(db).add_code_prefix('ABC')
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
