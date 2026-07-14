class PathRepositoryMixin:
    def add_path(self, folder_path):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO path_library (path)
                VALUES (?)
                ''',
                (folder_path,),
            )
            conn.commit()

        return self.get_path_by_value(folder_path)

    def delete_path(self, path_id):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM path_library WHERE id = ?', (path_id,))
            conn.commit()
            return cursor.rowcount

    def list_paths(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, path, created_at, last_total_bytes, last_used_bytes,
                       last_free_bytes, last_usage_percent, last_volume_type, last_checked_at
                FROM path_library
                ORDER BY created_at DESC, id DESC
                '''
            )

            return [
                {
                    'id': row[0],
                    'path': row[1] or '',
                    'created_at': row[2] or '',
                    'last_total_bytes': row[3] or 0,
                    'last_used_bytes': row[4] or 0,
                    'last_free_bytes': row[5] or 0,
                    'last_usage_percent': row[6] or 0,
                    'last_volume_type': row[7] or '',
                    'last_checked_at': row[8] or '',
                }
                for row in cursor.fetchall()
            ]

    def update_path_storage_info(self, path_id, storage_info):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE path_library
                SET last_total_bytes = ?,
                    last_used_bytes = ?,
                    last_free_bytes = ?,
                    last_usage_percent = ?,
                    last_volume_type = ?,
                    last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                ''',
                (
                    storage_info.get('total_bytes', 0),
                    storage_info.get('used_bytes', 0),
                    storage_info.get('free_bytes', 0),
                    storage_info.get('usage_percent', 0),
                    storage_info.get('volume_type', ''),
                    path_id,
                ),
            )
            conn.commit()
