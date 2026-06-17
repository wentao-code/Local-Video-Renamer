from app.core.ladder_board import normalize_ladder_board_key, normalize_ladder_entity_type, normalize_ladder_tier


class LadderRepositoryMixin:
    def list_ladder_entries(self, board_key=None, entity_type=None):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        clauses = []
        params = []
        if normalized_board_key:
            clauses.append('board_key = ?')
            params.append(normalized_board_key)
        if normalized_entity_type:
            clauses.append('entity_type = ?')
            params.append(normalized_entity_type)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT board_key, entity_type, entity_name, tier, medal, created_at, updated_at
                FROM ladder_entries
                {where_sql}
                ORDER BY updated_at DESC, entity_name
                ''',
                params,
            )
            return [
                self._ladder_entry_from_row(row)
                for row in cursor.fetchall()
            ]

    def get_ladder_entry(self, board_key, entity_type, entity_name):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        normalized_name = str(entity_name or '').strip()
        if not normalized_entity_type or not normalized_name:
            return {}

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT board_key, entity_type, entity_name, tier, medal, created_at, updated_at
                FROM ladder_entries
                WHERE board_key = ? AND entity_type = ? AND entity_name = ?
                LIMIT 1
                ''',
                (normalized_board_key, normalized_entity_type, normalized_name),
            )
            row = cursor.fetchone()

        return self._ladder_entry_from_row(row) if row else {}

    def save_ladder_entry(self, board_key, entity_type, entity_name, tier):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        normalized_name = str(entity_name or '').strip()
        normalized_tier = normalize_ladder_tier(tier)
        if not normalized_entity_type:
            raise ValueError('缺少榜单类型')
        if not normalized_name:
            raise ValueError('缺少榜单名称')
        if not normalized_tier:
            raise ValueError('缺少榜单等级')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO ladder_entries (
                    board_key, entity_type, entity_name, tier, medal, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''',
                (normalized_board_key, normalized_entity_type, normalized_name, normalized_tier),
            )
            cursor.execute(
                '''
                UPDATE ladder_entries
                SET tier = ?, updated_at = CURRENT_TIMESTAMP
                WHERE board_key = ? AND entity_type = ? AND entity_name = ?
                ''',
                (normalized_tier, normalized_board_key, normalized_entity_type, normalized_name),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def update_ladder_entry_medal(self, board_key, entity_type, entity_name, medal):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        normalized_name = str(entity_name or '').strip()
        if not normalized_entity_type:
            raise ValueError('缺少榜单类型')
        if not normalized_name:
            raise ValueError('缺少榜单名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE ladder_entries
                SET medal = ?, updated_at = CURRENT_TIMESTAMP
                WHERE board_key = ? AND entity_type = ? AND entity_name = ?
                ''',
                (str(medal or '').strip(), normalized_board_key, normalized_entity_type, normalized_name),
            )
            if int(cursor.rowcount or 0) <= 0:
                raise ValueError('未找到对应入选者')
            conn.commit()
            return int(cursor.rowcount or 0)

    @staticmethod
    def _ladder_entry_from_row(row):
        return {
            'board_key': row[0] or '',
            'entity_type': row[1] or '',
            'entity_name': row[2] or '',
            'tier': row[3] or '',
            'medal': row[4] or '',
            'created_at': row[5] or '',
            'updated_at': row[6] or '',
        }
