# Queen Library Backups

This folder stores one-off SQLite backups created before queen library data migrations.

- `queen_library.db.source-backup-*`: backup before repairing legacy `source` values.
- `queen_library.db.domain-backup-*`: backup before migrating queen library domain values to English keys.
- `queen_library.db-wal.domain-backup-*` and `queen_library.db-shm.domain-backup-*`: WAL/SHM companions captured with the domain migration backup.

Keep the latest backup until the migrated queen library data has been verified.
