import gc
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.core.actor_profile_display import UNKNOWN_ACTOR_AGE_TEXT
from app.data.database_handler import VideoDatabase
from app.services.actor_profile_update_service import ActorProfileUpdateService
from app.services.library_admin_service import LibraryAdminService


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
            self.assertEqual(rows[0]['birthday'], '2005-07-18')
            self.assertEqual(rows[0]['age'], '20')

            del rows
            del db
            gc.collect()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
