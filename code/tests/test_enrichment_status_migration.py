import sqlite3

from app.data.database_handler import VideoDatabase
from app.core.enrichment_status import ENRICHED_STATUS


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
