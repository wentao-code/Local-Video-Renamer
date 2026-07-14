import gc
import importlib
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from app.core.enrichment_status import ENRICHED_STATUS
from app.data.database_handler import VideoDatabase


def test_refresh_expires_only_after_ninety_days_for_active_or_suspect_items():
    module = importlib.import_module('app.core.library_refresh_expiry')
    now = datetime(2026, 7, 14, 12, 0, 0)

    assert not module.is_library_refresh_expired('2026-04-15 12:00:00', 'active', now=now)
    assert module.is_library_refresh_expired('2026-04-15 11:59:59', 'active', now=now)
    assert module.is_library_refresh_expired('2026-04-15 11:59:59', 'suspect', now=now)
    assert not module.is_library_refresh_expired('2026-04-15 11:59:59', 'inactive', now=now)
    assert not module.is_library_refresh_expired('', 'active', now=now)


def test_effective_status_marks_only_terminal_refreshes_as_expired():
    module = importlib.import_module('app.core.library_refresh_expiry')
    now = datetime(2026, 7, 14, 12, 0, 0)

    assert module.effective_library_refresh_status(
        ENRICHED_STATUS,
        '2026-04-01 00:00:00',
        'active',
        now=now,
    ) == module.EXPIRED_STATUS
    assert module.effective_library_refresh_status(
        '补全失败',
        '2026-04-01 00:00:00',
        'active',
        now=now,
    ) == '补全失败'


def test_refresh_tables_exist_and_backfill_existing_source_timestamps():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / 'video_database.db'
    try:
        db = VideoDatabase(db_path)
        db.save_actor_enrichment('Actor A', ENRICHED_STATUS, source_key='avfan')
        db.save_code_prefix_enrichment('ABC', ENRICHED_STATUS, source_key='javtxt')
        del db
        gc.collect()

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute('DELETE FROM actor_enrichment_refresh_times')
            conn.execute('DELETE FROM code_prefix_enrichment_refresh_times')
            conn.commit()

        db = VideoDatabase(db_path)
        actor_times = db.list_actor_enrichment_refresh_times(['Actor A'])
        prefix_times = db.list_code_prefix_enrichment_refresh_times(['ABC'])

        assert actor_times[('Actor A', 'avfan')]['last_completed_at']
        assert prefix_times[('ABC', 'javtxt')]['last_completed_at']
        with sqlite3.connect(str(db_path)) as conn:
            table_names = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        assert {
            'actor_enrichment_refresh_times',
            'code_prefix_enrichment_refresh_times',
            'actor_expired_refresh_history',
            'code_prefix_expired_refresh_history',
        }.issubset(table_names)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_database_tracks_source_expiry_and_refresh_growth_history():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / 'video_database.db'
    try:
        db = VideoDatabase(db_path)
        db.record_actor_enrichment_refresh_completion(
            'Actor A',
            'avfan',
            update_status='active',
            completed_at='2026-04-01 00:00:00',
        )
        db.record_code_prefix_enrichment_refresh_completion(
            'abc',
            'javtxt',
            update_status='suspect',
            completed_at='2026-04-01 00:00:00',
        )

        now = datetime(2026, 7, 14, 12, 0, 0)
        assert db.list_expired_actor_enrichment_entities('avfan', now=now) == {'Actor A'}
        assert db.list_expired_code_prefix_enrichment_entities('javtxt', now=now) == {'ABC'}

        db.update_actor_enrichment_refresh_statuses({'Actor A': 'inactive'})
        assert db.list_expired_actor_enrichment_entities('avfan', now=now) == set()

        db.record_actor_expired_refresh_history('Actor A', 'avfan', 10, 13, completed_at='2026-07-14 12:00:00')
        db.record_code_prefix_expired_refresh_history('ABC', 'javtxt', 20, 20, completed_at='2026-07-14 12:00:00')

        assert db.list_actor_expired_refresh_history('Actor A')[0]['added_video_count'] == 3
        assert db.list_code_prefix_expired_refresh_history('ABC')[0]['added_video_count'] == 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
