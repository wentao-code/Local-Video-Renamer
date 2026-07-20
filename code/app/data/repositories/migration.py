class MigrationMixin:
    @staticmethod
    def _is_view(cursor, table_name):
        cursor.execute(
            'SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?',
            ('view', table_name),
        )
        return cursor.fetchone() is not None

    def _ensure_column(self, cursor, table_name, column_name, column_type):
        if self._is_view(cursor, table_name):
            return
        cursor.execute(f'PRAGMA table_info({table_name})')
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')

    @staticmethod
    def _ensure_index(cursor, index_name, table_name, columns_sql):
        cursor.execute(
            'SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?',
            ('view', table_name),
        )
        if cursor.fetchone() is not None:
            return
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_sql})'
        )
