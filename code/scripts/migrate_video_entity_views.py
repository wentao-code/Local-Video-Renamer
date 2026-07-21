"""Finalize migration from legacy movie objects to canonical tables."""

import sys
import traceback
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from app.core.project_paths import DATABASE_FILE
from app.data.database_handler import VideoDatabase


def main():
    database = object.__new__(VideoDatabase)
    database.db_path = Path(DATABASE_FILE)
    database._startup_maintenance_completed = False
    database.finalize_legacy_schema()
    with database._connect() as conn:
        rows = conn.execute(
            """
            SELECT name, type
            FROM sqlite_master
            WHERE name IN (
                'processed_videos', 'actor_movies', 'code_prefix_movies',
                'processed_videos_legacy_backup', 'actor_movies_legacy_backup',
                'code_prefix_movies_legacy_backup'
            )
            ORDER BY name
            """
        ).fetchall()
        print('database:', database.db_path)
        print('objects:', rows)


if __name__ == '__main__':
    try:
        main()
        print('migration: completed')
    except Exception as exc:
        print(f'migration: failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        print('请完全退出主程序、任务进程和数据库查看工具后重试。', file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
