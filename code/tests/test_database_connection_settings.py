import unittest
from pathlib import Path
from unittest.mock import patch

from app.data.database_handler import VideoDatabase


class DatabaseConnectionSettingsTest(unittest.TestCase):
    def test_database_connect_configures_wal_and_busy_timeout(self):
        calls = []

        class _ConnectionStub:
            def execute(self, sql):
                calls.append(sql)
                return self

            def create_function(self, name, arg_count, callback):
                calls.append((name, arg_count, callable(callback)))

            def close(self):
                calls.append('close')

        database = VideoDatabase.__new__(VideoDatabase)
        database.db_path = Path('test.db')

        with patch('app.data.database_handler.sqlite3.connect', return_value=_ConnectionStub()):
            with VideoDatabase._connect(database):
                pass

        self.assertIn('PRAGMA journal_mode = WAL', calls)
        self.assertIn('PRAGMA busy_timeout = 60000', calls)
        self.assertIn('PRAGMA synchronous = NORMAL', calls)
        self.assertIn('close', calls)

    def test_database_handler_source_has_no_direct_sqlite_connections(self):
        source_path = Path(__file__).resolve().parents[1] / 'app' / 'data' / 'database_handler.py'
        source_text = source_path.read_text(encoding='utf-8')

        self.assertNotIn('with sqlite3.connect(self.db_path) as conn', source_text)


if __name__ == '__main__':
    unittest.main()
