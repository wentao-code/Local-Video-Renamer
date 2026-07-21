import sqlite3
import tempfile
from pathlib import Path

from app.data.database_handler import VideoDatabase
from app.core.enrichment_status import ENRICHED_STATUS
from app.core.enrichment_status import FAILED_STATUS, UNENRICHED_STATUS
from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, BAOMU_ACTOR_SOURCE, BINGHUO_ACTOR_SOURCE


def test_legacy_source_statuses_are_migrated_to_stable_codes():
    connection = sqlite3.connect(':memory:')
    cursor = connection.cursor()
    cursor.execute('CREATE TABLE actor_enrichments (actor_name TEXT, avfan_enrichment_status TEXT)')
    cursor.execute(
        'INSERT INTO actor_enrichments(actor_name, avfan_enrichment_status) VALUES (?, ?)',
        ('Actor A', '已补全'),
    )

    VideoDatabase._migrate_enrichment_status_values(object(), cursor)

    assert cursor.execute(
        'SELECT avfan_enrichment_status FROM actor_enrichments WHERE actor_name = ?',
        ('Actor A',),
    ).fetchone()[0] == ENRICHED_STATUS


def test_sql_actor_candidate_selection_uses_stable_avfan_codes():
    with tempfile.TemporaryDirectory() as temp_dir:
        database = VideoDatabase(Path(temp_dir) / 'video_database.db')
        with database._connect() as connection:
            connection.executemany(
                'INSERT INTO actors(name) VALUES (?)',
                [('Pending Actor',), ('Completed Actor',), ('Failed Actor',)],
            )
            connection.executemany(
                'INSERT INTO actor_enrichments(actor_name, avfan_enrichment_status) VALUES (?, ?)',
                [
                    ('Pending Actor', UNENRICHED_STATUS),
                    ('Completed Actor', ENRICHED_STATUS),
                    ('Failed Actor', FAILED_STATUS),
                ],
            )
            connection.commit()

        assert database.list_sql_enrichment_candidates(
            'actor', AVFAN_VIDEO_SOURCE, 10
        ) == [{'actor_name': 'Failed Actor'}, {'actor_name': 'Pending Actor'}]


def test_sql_actor_birthday_candidate_selection_uses_source_codes():
    with tempfile.TemporaryDirectory() as temp_dir:
        database = VideoDatabase(Path(temp_dir) / 'video_database.db')
        with database._connect() as connection:
            connection.executemany(
                'INSERT INTO actors(name, birthday) VALUES (?, ?)',
                [('Binghuo Candidate', ''), ('Baomu Candidate', '1990-01-01')],
            )
            connection.executemany(
                '''INSERT INTO actor_enrichments(
                    actor_name, binghuo_enrichment_status, binghuo_birthday,
                    binghuo_height, binghuo_person_id, baomu_enrichment_status
                ) VALUES (?, ?, ?, ?, ?, ?)''',
                [
                    ('Binghuo Candidate', UNENRICHED_STATUS, '', '', '', UNENRICHED_STATUS),
                    ('Baomu Candidate', ENRICHED_STATUS, '1990-01-01', '168', '1001', UNENRICHED_STATUS),
                ],
            )
            connection.commit()

        assert database.list_sql_enrichment_candidates(
            'actor_birthday', BINGHUO_ACTOR_SOURCE, 10
        ) == [{'actor_name': 'Binghuo Candidate'}]
        assert database.list_sql_enrichment_candidates(
            'actor_birthday', BAOMU_ACTOR_SOURCE, 10
        ) == [{'actor_name': 'Baomu Candidate'}]


def test_sql_code_prefix_candidate_selection_uses_stable_avfan_codes():
    with tempfile.TemporaryDirectory() as temp_dir:
        database = VideoDatabase(Path(temp_dir) / 'video_database.db')
        with database._connect() as connection:
            connection.executemany(
                'INSERT INTO code_prefix_enrichments(prefix, avfan_enrichment_status) VALUES (?, ?)',
                [
                    ('DONE', ENRICHED_STATUS),
                    ('PENDING', UNENRICHED_STATUS),
                    ('FAILED', FAILED_STATUS),
                ],
            )
            connection.commit()

        assert database.list_sql_code_prefix_candidates(AVFAN_VIDEO_SOURCE, 10) == [
            {'prefix': 'FAILED'},
            {'prefix': 'PENDING'},
        ]


def test_sql_javtxt_candidates_join_processed_video_cache():
    with tempfile.TemporaryDirectory() as temp_dir:
        database = VideoDatabase(Path(temp_dir) / 'video_database.db')
        with database._connect() as connection:
            connection.execute(
                'INSERT INTO actors(name) VALUES (?)', ('Actor A',)
            )
            connection.execute(
                '''INSERT INTO actor_enrichments(
                    actor_name, avfan_enrichment_status, avfan_total_videos
                ) VALUES (?, ?, ?)''',
                ('Actor A', ENRICHED_STATUS, 2),
            )
            connection.execute(
                '''INSERT INTO video_entities(
                    code, title, author, release_date, javtxt_actors, javtxt_movie_id, javtxt_url,
                    javtxt_enrichment_status, javtxt_release_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('ABC-001', 'Title', '', '2025-01-01', 'Cached Actor', '1', 'https://example.test/1', UNENRICHED_STATUS, '2025-01-01'),
            )
            connection.execute(
                'INSERT INTO video_actor_relations (actor_name, video_code) VALUES (?, ?)',
                ('Actor A', 'ABC-001'),
            )
            connection.commit()

        rows = database.list_sql_javtxt_candidate_items('actor', 10)

        assert len(rows) == 1
        assert rows[0]['actor_name'] == 'Actor A'
        assert rows[0]['code'] == 'ABC-001'
        assert rows[0]['cached_javtxt_actors'] == 'Cached Actor'


def test_sql_supplement_candidates_exclude_pending_rows():
    with tempfile.TemporaryDirectory() as temp_dir:
        database = VideoDatabase(Path(temp_dir) / 'video_database.db')
        with database._connect() as connection:
            connection.execute(
                '''INSERT INTO video_entities(
                    code, title, author, javtxt_movie_id, javtxt_url,
                    javtxt_enrichment_status, supplement_enrichment_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                ('ABC-001', 'Title', '', '1', 'https://example.test/1', ENRICHED_STATUS, UNENRICHED_STATUS),
            )
            connection.execute(
                '''INSERT INTO pending_video_avfan(
                    plan_id, sequence_index, target_key, code, source_key, status
                ) VALUES (?, ?, ?, ?, ?, ?)''',
                ('plan-1', 1, 'ABC-001', 'ABC-001', 'supplement', 'pending'),
            )
            connection.commit()

            assert database.list_sql_supplement_candidates('video', 10) == []
            assert database.list_sql_supplement_candidates('video', 10, include_queued=True)[0]['code'] == 'ABC-001'
