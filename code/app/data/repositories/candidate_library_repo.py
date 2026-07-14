class CandidateLibraryRepositoryMixin:
    def replace_candidate_actor_records(self, rows):
        normalized_rows = self._normalize_candidate_actor_rows(rows)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM candidate_actor_records')
            cursor.executemany(
                '''
                INSERT INTO candidate_actor_records (actor_name, video_count, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ''',
                [(row['actor_name'], row['video_count']) for row in normalized_rows],
            )
            conn.commit()

    def list_candidate_actor_records(self, limit=50):
        normalized_limit = max(1, int(limit or 50))
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT actor_name, video_count
                FROM candidate_actor_records
                ORDER BY video_count DESC, actor_name COLLATE NOCASE ASC
                LIMIT ?
                ''',
                (normalized_limit,),
            )
            return [
                {'actor_name': str(row[0] or '').strip(), 'video_count': int(row[1] or 0)}
                for row in cursor.fetchall()
            ]

    def delete_candidate_actor_record(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM candidate_actor_records WHERE actor_name = ?', (normalized_name,))
            conn.commit()
            return int(cursor.rowcount or 0)

    def replace_candidate_code_prefix_records(self, rows):
        normalized_rows = self._normalize_candidate_code_prefix_rows(rows)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM candidate_code_prefix_records')
            cursor.executemany(
                '''
                INSERT INTO candidate_code_prefix_records (prefix, video_count, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ''',
                [(row['prefix'], row['video_count']) for row in normalized_rows],
            )
            conn.commit()

    def list_candidate_code_prefix_records(self, limit=50):
        normalized_limit = max(1, int(limit or 50))
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT prefix, video_count
                FROM candidate_code_prefix_records
                ORDER BY video_count DESC, prefix ASC
                LIMIT ?
                ''',
                (normalized_limit,),
            )
            return [
                {'prefix': str(row[0] or '').strip().upper(), 'video_count': int(row[1] or 0)}
                for row in cursor.fetchall()
            ]

    def delete_candidate_code_prefix_record(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM candidate_code_prefix_records WHERE prefix = ?', (normalized_prefix,))
            conn.commit()
            return int(cursor.rowcount or 0)

    @staticmethod
    def _normalize_candidate_actor_rows(rows):
        normalized_rows = []
        seen = set()
        for row in rows or []:
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            seen.add(actor_name)
            normalized_rows.append({'actor_name': actor_name, 'video_count': max(0, int((row or {}).get('video_count', 0) or 0))})
        return normalized_rows

    @staticmethod
    def _normalize_candidate_code_prefix_rows(rows):
        normalized_rows = []
        seen = set()
        for row in rows or []:
            prefix = str((row or {}).get('prefix', '') or '').strip().upper()
            if not prefix or prefix in seen:
                continue
            seen.add(prefix)
            normalized_rows.append({'prefix': prefix, 'video_count': max(0, int((row or {}).get('video_count', 0) or 0))})
        return normalized_rows
