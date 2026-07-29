from app.core.video_code import standardize_video_code
from app.core.video_filter_settings import load_video_filter_settings
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.core.supplement_task_state import build_supplement_candidate
from app.services.identity import split_actor_names
from app.services.library.code_prefix_library import extract_code_prefix
from app.services.video import normalize_video_category
VIDEO_ENTITY_MATERIALIZATION_META_KEY = 'video_entity_materialization_version'
VIDEO_ENTITY_MATERIALIZATION_VERSION = '1'



def sanitize_actor_text(value):
    return normalize_second_source_actor_text(value)


class VideoEntityRepositoryMixin:
    """Persistence operations for unified video entities and their relations."""

    def upsert_video_entity(self, entity, actor_relations=None, prefix_relations=None, local_record=None):
        payload = dict(entity or {})
        normalized_code = standardize_video_code(payload.get('code', ''))
        if not normalized_code:
            raise ValueError('视频编号不能为空')

        fields = (
            'title', 'author', 'release_date', 'maker', 'publisher', 'avfan_url',
            'avfan_movie_id', 'javtxt_movie_id', 'javtxt_url', 'javtxt_title',
            'javtxt_actors', 'javtxt_actors_raw', 'javtxt_tags', 'javtxt_release_date',
            'javtxt_enrichment_status', 'video_category', 'supplement_enrichment_status',
            'supplement_enrichment_error', 'supplement_enriched_at',
        )
        values = [str(payload.get(field, '') or '').strip() for field in fields]
        columns = ', '.join(('code', *fields))
        placeholders = ', '.join('?' for _ in ('code', *fields))
        update_sql = ', '.join(
            f"{field} = CASE WHEN excluded.{field} <> '' THEN excluded.{field} ELSE video_entities.{field} END"
            for field in fields
        )

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                INSERT INTO video_entities ({columns})
                VALUES ({placeholders})
                ON CONFLICT(code) DO UPDATE SET
                    {update_sql}, updated_at = CURRENT_TIMESTAMP
                ''',
                [normalized_code, *values],
            )

            for relation in actor_relations or ():
                actor_name = str((relation or {}).get('actor_name', '') or '').strip()
                if not actor_name:
                    continue
                cursor.execute(
                    'INSERT OR IGNORE INTO video_actor_relations (video_code, actor_name) VALUES (?, ?)',
                    (normalized_code, actor_name),
                )
                cursor.execute(
                    '''
                    INSERT INTO video_actor_relation_meta (
                        video_code, actor_name, avfan_url, avfan_movie_id, page_number
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(video_code, actor_name) DO UPDATE SET
                        avfan_url = CASE WHEN excluded.avfan_url <> '' THEN excluded.avfan_url ELSE video_actor_relation_meta.avfan_url END,
                        avfan_movie_id = CASE WHEN excluded.avfan_movie_id <> '' THEN excluded.avfan_movie_id ELSE video_actor_relation_meta.avfan_movie_id END,
                        page_number = CASE WHEN excluded.page_number > 0 THEN excluded.page_number ELSE video_actor_relation_meta.page_number END
                    ''',
                    (
                        normalized_code,
                        actor_name,
                        str((relation or {}).get('avfan_url', '') or '').strip(),
                        str((relation or {}).get('avfan_movie_id', '') or '').strip(),
                        max(1, int((relation or {}).get('page_number', 1) or 1)),
                    ),
                )

            for relation in prefix_relations or ():
                prefix = str((relation or {}).get('prefix', '') or '').strip().upper()
                if not prefix:
                    continue
                cursor.execute(
                    'INSERT OR IGNORE INTO video_code_prefix_relations (video_code, prefix) VALUES (?, ?)',
                    (normalized_code, prefix),
                )
                cursor.execute(
                    '''
                    INSERT INTO video_prefix_relation_meta (
                        video_code, prefix, avfan_url, avfan_movie_id, page_number
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(video_code, prefix) DO UPDATE SET
                        avfan_url = CASE WHEN excluded.avfan_url <> '' THEN excluded.avfan_url ELSE video_prefix_relation_meta.avfan_url END,
                        avfan_movie_id = CASE WHEN excluded.avfan_movie_id <> '' THEN excluded.avfan_movie_id ELSE video_prefix_relation_meta.avfan_movie_id END,
                        page_number = CASE WHEN excluded.page_number > 0 THEN excluded.page_number ELSE video_prefix_relation_meta.page_number END
                    ''',
                    (
                        normalized_code,
                        prefix,
                        str((relation or {}).get('avfan_url', '') or '').strip(),
                        str((relation or {}).get('avfan_movie_id', '') or '').strip(),
                        max(1, int((relation or {}).get('page_number', 1) or 1)),
                    ),
                )

            if local_record is not None:
                local = dict(local_record or {})
                cursor.execute(
                    '''
                    INSERT INTO local_video_records (code, duration, size, storage_location)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        duration = CASE WHEN excluded.duration <> '' THEN excluded.duration ELSE local_video_records.duration END,
                        size = CASE WHEN excluded.size <> '' THEN excluded.size ELSE local_video_records.size END,
                        storage_location = CASE WHEN excluded.storage_location <> '' THEN excluded.storage_location ELSE local_video_records.storage_location END,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        normalized_code,
                        str(local.get('duration', '') or '').strip(),
                        str(local.get('size', '') or '').strip(),
                        str(local.get('storage_location', '') or '').strip(),
                    ),
                )
            conn.commit()
        self.rebuild_video_entity_exclusions()
        return normalized_code
    @staticmethod
    def _ensure_video_entity_tables(cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS video_entities (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                release_date TEXT NOT NULL DEFAULT '',
                maker TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                avfan_url TEXT NOT NULL DEFAULT '',
                avfan_movie_id TEXT NOT NULL DEFAULT '',
                javtxt_movie_id TEXT NOT NULL DEFAULT '',
                javtxt_url TEXT NOT NULL DEFAULT '',
                javtxt_title TEXT NOT NULL DEFAULT '',
                javtxt_actors TEXT NOT NULL DEFAULT '',
                javtxt_actors_raw TEXT NOT NULL DEFAULT '',
                javtxt_tags TEXT NOT NULL DEFAULT '',
                javtxt_release_date TEXT NOT NULL DEFAULT '',
                javtxt_enrichment_status TEXT NOT NULL DEFAULT '',
                javtxt_enrichment_error TEXT NOT NULL DEFAULT '',
                javtxt_enriched_at TEXT NOT NULL DEFAULT '',
                video_category TEXT NOT NULL DEFAULT '',
                supplement_enrichment_status TEXT NOT NULL DEFAULT '',
                supplement_enrichment_error TEXT NOT NULL DEFAULT '',
                supplement_enriched_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS video_actor_relations (
                video_code TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                actor_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (video_code, actor_name)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS video_code_prefix_relations (
                video_code TEXT NOT NULL,
                prefix TEXT NOT NULL,
                PRIMARY KEY (video_code, prefix)
            )
            '''
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_video_actor_relations_actor '
            'ON video_actor_relations (actor_name, video_code)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_video_prefix_relations_prefix '
            'ON video_code_prefix_relations (prefix, video_code)'
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS video_actor_relation_meta (
                video_code TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                avfan_url TEXT NOT NULL DEFAULT '',
                avfan_movie_id TEXT NOT NULL DEFAULT '',
                page_number INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (video_code, actor_name)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS video_prefix_relation_meta (
                video_code TEXT NOT NULL,
                prefix TEXT NOT NULL,
                avfan_url TEXT NOT NULL DEFAULT '',
                avfan_movie_id TEXT NOT NULL DEFAULT '',
                page_number INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (video_code, prefix)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS local_video_records (
                code TEXT PRIMARY KEY,
                duration TEXT NOT NULL DEFAULT '',
                size TEXT NOT NULL DEFAULT '',
                storage_location TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS active_video_entities (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                release_date TEXT NOT NULL DEFAULT '',
                maker TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '',
                avfan_url TEXT NOT NULL DEFAULT '',
                avfan_movie_id TEXT NOT NULL DEFAULT '',
                javtxt_movie_id TEXT NOT NULL DEFAULT '',
                javtxt_url TEXT NOT NULL DEFAULT '',
                javtxt_title TEXT NOT NULL DEFAULT '',
                javtxt_actors TEXT NOT NULL DEFAULT '',
                javtxt_actors_raw TEXT NOT NULL DEFAULT '',
                javtxt_tags TEXT NOT NULL DEFAULT '',
                javtxt_release_date TEXT NOT NULL DEFAULT '',
                javtxt_enrichment_status TEXT NOT NULL DEFAULT '',
                video_category TEXT NOT NULL DEFAULT '',
                supplement_enrichment_status TEXT NOT NULL DEFAULT '',
                supplement_enrichment_error TEXT NOT NULL DEFAULT '',
                supplement_enriched_at TEXT NOT NULL DEFAULT '',
                enrichment_status TEXT NOT NULL DEFAULT '',
                enrichment_error TEXT NOT NULL DEFAULT '',
                enriched_at TEXT NOT NULL DEFAULT '',
                avfan_enrichment_status TEXT NOT NULL DEFAULT '',
                avfan_enrichment_error TEXT NOT NULL DEFAULT '',
                avfan_enriched_at TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                javtxt_description TEXT NOT NULL DEFAULT '',
                avfan_actors TEXT NOT NULL DEFAULT '',
                avfan_tags TEXT NOT NULL DEFAULT '',
                duration TEXT NOT NULL DEFAULT '',
                size TEXT NOT NULL DEFAULT '',
                storage_location TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_active_video_entities_storage_code '
            'ON active_video_entities (storage_location, code)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_active_video_entities_release_code '
            'ON active_video_entities (release_date, code)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_video_actor_relation_meta_actor '
            'ON video_actor_relation_meta (actor_name, video_code)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_video_prefix_relation_meta_prefix '
            'ON video_prefix_relation_meta (prefix, video_code)'
        )
    def _ensure_active_video_entity_sync_triggers(self, cursor):
        entity_columns = (
            'code, title, author, release_date, maker, publisher, avfan_url, avfan_movie_id, '
            'javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_actors_raw, '
            'javtxt_tags, javtxt_release_date, javtxt_enrichment_status, video_category, '
            'supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at, '
            'enrichment_status, enrichment_error, enriched_at, avfan_enrichment_status, '
            'avfan_enrichment_error, avfan_enriched_at, description, javtxt_description, '
            'avfan_actors, avfan_tags'
        )
        active_columns = f'{entity_columns}, duration, size, storage_location, updated_at'
        entity_values = ', '.join(f'NEW.{column}' for column in entity_columns.split(', '))
        cursor.execute('DROP TRIGGER IF EXISTS trg_video_entities_sync_active_insert')
        cursor.execute('DROP TRIGGER IF EXISTS trg_video_entities_sync_active_update')
        cursor.execute('DROP TRIGGER IF EXISTS trg_video_entities_sync_active_delete')
        cursor.execute('DROP TRIGGER IF EXISTS trg_local_video_records_sync_active_insert')
        cursor.execute('DROP TRIGGER IF EXISTS trg_local_video_records_sync_active_update')
        cursor.execute('DROP TRIGGER IF EXISTS trg_active_video_entities_sync_archive_update')
        cursor.execute(
            f'''
            CREATE TRIGGER trg_video_entities_sync_active_insert
            AFTER INSERT ON video_entities
            BEGIN
                DELETE FROM active_video_entities WHERE code = NEW.code;
                INSERT INTO active_video_entities ({active_columns})
                SELECT {entity_values}, COALESCE(local.duration, ''), COALESCE(local.size, ''),
                       COALESCE(local.storage_location, ''), CURRENT_TIMESTAMP
                FROM video_entities AS entity
                LEFT JOIN local_video_records AS local ON local.code = entity.code
                WHERE entity.code = NEW.code
                  AND NOT EXISTS (
                      SELECT 1 FROM video_entity_exclusions AS exclusion
                      WHERE exclusion.code = NEW.code AND exclusion.scope = 'all'
                  );
            END
            '''
        )
        cursor.execute(
            f'''
            CREATE TRIGGER trg_video_entities_sync_active_update
            AFTER UPDATE ON video_entities
            BEGIN
                DELETE FROM active_video_entities WHERE code = NEW.code;
                INSERT INTO active_video_entities ({active_columns})
                SELECT {entity_values}, COALESCE(local.duration, ''), COALESCE(local.size, ''),
                       COALESCE(local.storage_location, ''), CURRENT_TIMESTAMP
                FROM video_entities AS entity
                LEFT JOIN local_video_records AS local ON local.code = entity.code
                WHERE entity.code = NEW.code
                  AND NOT EXISTS (
                      SELECT 1 FROM video_entity_exclusions AS exclusion
                      WHERE exclusion.code = NEW.code AND exclusion.scope = 'all'
                  );
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER trg_video_entities_sync_active_delete
            AFTER DELETE ON video_entities
            BEGIN
                DELETE FROM active_video_entities WHERE code = OLD.code;
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER trg_local_video_records_sync_active_insert
            AFTER INSERT ON local_video_records
            BEGIN
                UPDATE active_video_entities
                SET duration = NEW.duration, size = NEW.size,
                    storage_location = NEW.storage_location,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = NEW.code;
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER trg_local_video_records_sync_active_update
            AFTER UPDATE ON local_video_records
            BEGIN
                UPDATE active_video_entities
                SET duration = NEW.duration, size = NEW.size,
                    storage_location = NEW.storage_location,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = NEW.code;
            END
            '''
        )
    def list_videos(
        self,
        search_text='',
        sort_field='code',
        sort_order='asc',
        limit=None,
        offset=0,
        rule_set=None,
    ):
        where_sql, parameters = self._video_search_where_sql(search_text)
        return self._fetch_processed_video_rows(
            where_sql,
            parameters,
            order_by_sql=self._video_order_by_sql(sort_field, sort_order),
            limit=limit,
            offset=offset,
            refresh_categories=False,
            rule_set=rule_set,
        )

    def count_videos(self, search_text='', rule_set=None):
        where_sql, parameters = self._video_search_where_sql(search_text)
        where_sql, parameters = self._append_rule_set_where(
            where_sql,
            parameters,
            rule_set=rule_set,
            table_alias='p',
        )
        where_sql = self._local_video_where_sql(where_sql)
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_read_sql = self._processed_video_read_sql(cursor)
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM ({processed_read_sql}) AS p
                {where_sql}
                ''',
                tuple(parameters),
            )
            row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    def list_local_videos_by_actor_name(self, actor_name, refresh_categories=True):
        rows = self.list_local_videos_by_actor_names([actor_name], refresh_categories=refresh_categories)
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return []
        return [
            row
            for row in rows
            if normalized_name in split_actor_names(row.get('author', ''))
        ]

    def list_local_videos_by_actor_names(self, actor_names, refresh_categories=True):
        normalized_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_names.append(normalized_name)
        if not normalized_names:
            return []

        rows = []
        chunk_size = 50
        for start_index in range(0, len(normalized_names), chunk_size):
            chunk = normalized_names[start_index:start_index + chunk_size]
            rows.extend(
                self._fetch_processed_video_rows(
                    'WHERE ' + ' OR '.join('author LIKE ?' for _ in chunk),
                    [f'%{actor_name}%' for actor_name in chunk],
                    refresh_categories=refresh_categories and start_index == 0,
                )
            )
        target_names = set(normalized_names)
        deduplicated_rows = {}
        for row in rows:
            normalized_code = standardize_video_code((row or {}).get('code', ''))
            deduplicated_rows[normalized_code or str(len(deduplicated_rows))] = dict(row or {})
        return [
            row
            for row in deduplicated_rows.values()
            if target_names.intersection(split_actor_names(row.get('author', '')))
        ]

    def list_local_videos_by_prefix(self, prefix, refresh_categories=True):
        rows = self.list_local_videos_by_prefixes([prefix], refresh_categories=refresh_categories)
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return []
        return [
            row
            for row in rows
            if extract_code_prefix(row.get('code', '')) == normalized_prefix
        ]

    def list_local_videos_by_prefixes(self, prefixes, refresh_categories=True):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix in seen:
                continue
            seen.add(normalized_prefix)
            normalized_prefixes.append(normalized_prefix)
        if not normalized_prefixes:
            return []

        rows = self._fetch_processed_video_rows(
            'WHERE ' + ' OR '.join('code LIKE ?' for _ in normalized_prefixes),
            [f'{prefix}%' for prefix in normalized_prefixes],
            refresh_categories=refresh_categories,
        )
        target_prefixes = set(normalized_prefixes)
        return [
            row
            for row in rows
            if extract_code_prefix(row.get('code', '')) in target_prefixes
        ]

    def list_video_summary_rows(self, rule_set=None, visibility='visible'):
        where_sql, query_parameters = self._append_rule_set_where(
            '',
            [],
            rule_set=rule_set,
            table_alias='p',
            visibility=visibility,
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_read_table = self._processed_video_storage_target(cursor)
            cursor.execute(
                f'''
                SELECT code, title, release_date, video_category,
                       avfan_enrichment_status, javtxt_enrichment_status,
                       javtxt_movie_id, javtxt_url, javtxt_title, avfan_movie_id,
                       javtxt_actors, javtxt_actors_raw, javtxt_tags, javtxt_release_date, author,
                       supplement_enrichment_status
                FROM {processed_read_table} AS p
                {where_sql}
                ORDER BY code
                ''',
                query_parameters,
            )
            rows = cursor.fetchall()

        result = [
            {
                'code': row[0] or '',
                'title': row[1] or '',
                'release_date': row[2] or '',
                'video_category': normalize_video_category(row[3]),
                'avfan_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_enrichment_status': row[5] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[6] or '',
                'javtxt_url': row[7] or '',
                'javtxt_title': row[8] or '',
                'avfan_movie_id': row[9] or '',
                'author': sanitize_actor_text(row[10] or ''),
                'author_raw': self._normalize_actor_raw_text(row[11] or row[10] or ''),
                'javtxt_tags': row[12] or '',
                'javtxt_release_date': row[13] or '',
                'local_author': sanitize_actor_text(row[14] or ''),
                'supplement_enrichment_status': row[15] or UNENRICHED_STATUS,
            }
            for row in rows
        ]
        return self._apply_rule_set_residual(
            result,
            rule_set=rule_set,
            visibility=visibility,
        )
    def list_code_prefix_movies(self, prefix):
        prefix = str(prefix or '').strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.prefix = relation.prefix AND meta.video_code = entity.code
                WHERE relation.prefix = ?
                  AND NOT EXISTS (
                        SELECT 1 FROM video_entity_exclusions AS ex
                        WHERE ex.code = entity.code
                          AND ex.scope IN ('all', 'code_prefix_library')
                  )
                ORDER BY entity.release_date DESC, entity.code DESC
            ''', (prefix,))

            return [
                {
                    'prefix': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                    'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                }
                for row in cursor.fetchall()
            ]

    def list_all_code_prefix_movies(self, rule_set=None):
        where_sql, query_parameters = self._append_rule_set_where(
            '',
            [],
            rule_set=rule_set,
            table_alias='entity',
        )
        where_sql, query_parameters = self._append_entity_exclusion_where(
            where_sql,
            query_parameters,
            table_alias='entity',
            scopes=('all', 'code_prefix_library'),
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.prefix = relation.prefix AND meta.video_code = entity.code
                {where_sql}
                ORDER BY relation.prefix, entity.release_date DESC, entity.code DESC
                ''',
                query_parameters,
            )

            rows = [
                {
                    'prefix': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                    'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                }
                for row in cursor.fetchall()
            ]
        return self._apply_rule_set_residual(rows, rule_set=rule_set)

    def list_code_prefix_movies_by_prefixes(self, prefixes, rule_set=None):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix in seen:
                continue
            seen.add(normalized_prefix)
            normalized_prefixes.append(normalized_prefix)

        results = {prefix: [] for prefix in normalized_prefixes}
        if not normalized_prefixes:
            return results

        placeholders = ','.join('?' for _ in normalized_prefixes)
        where_sql, query_parameters = self._append_rule_set_where(
            f'WHERE relation.prefix IN ({placeholders})',
            normalized_prefixes,
            rule_set=rule_set,
            table_alias='entity',
        )
        where_sql, query_parameters = self._append_entity_exclusion_where(
            where_sql,
            query_parameters,
            table_alias='entity',
            scopes=('all', 'code_prefix_library'),
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.prefix = relation.prefix AND meta.video_code = entity.code
                {where_sql}
                ORDER BY relation.prefix, entity.release_date DESC, entity.code DESC
                ''',
                query_parameters,
            )

            for row in cursor.fetchall():
                prefix = row[0] or ''
                results.setdefault(prefix, []).append(
                    {
                        'prefix': prefix,
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': sanitize_actor_text(row[3] or ''),
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': int(row[6] or 1),
                        'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': normalize_video_category(row[13]),
                        'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                    }
                )

        return {
            prefix: self._apply_rule_set_residual(rows, rule_set=rule_set)
            for prefix, rows in results.items()
        }
    def list_actor_movies(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.actor_name = relation.actor_name AND meta.video_code = entity.code
                WHERE relation.actor_name = ?
                  AND NOT EXISTS (
                        SELECT 1 FROM video_entity_exclusions AS ex
                        WHERE ex.code = entity.code
                          AND ex.scope IN ('all', 'actor_library')
                  )
                ORDER BY entity.release_date DESC, entity.code DESC
            ''', (normalized_name,))

            return [
                {
                    'actor_name': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                    'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                }
                for row in cursor.fetchall()
            ]

    def list_all_actor_movies(self, rule_set=None):
        where_sql, query_parameters = self._append_rule_set_where(
            '',
            [],
            rule_set=rule_set,
            table_alias='entity',
        )
        where_sql, query_parameters = self._append_entity_exclusion_where(
            where_sql,
            query_parameters,
            table_alias='entity',
            scopes=('all', 'actor_library'),
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.actor_name = relation.actor_name AND meta.video_code = entity.code
                {where_sql}
                ORDER BY relation.actor_name, entity.release_date DESC, entity.code DESC
                ''',
                query_parameters,
            )

            rows = [
                {
                    'actor_name': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                    'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                }
                for row in cursor.fetchall()
            ]
        return self._apply_rule_set_residual(rows, rule_set=rule_set)

    def list_actor_movies_by_names(self, actor_names, rule_set=None):
        normalized_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_names.append(normalized_name)

        results = {actor_name: [] for actor_name in normalized_names}
        if not normalized_names:
            return results

        placeholders = ','.join('?' for _ in normalized_names)
        where_sql, query_parameters = self._append_rule_set_where(
            f'WHERE relation.actor_name IN ({placeholders})',
            normalized_names,
            rule_set=rule_set,
            table_alias='entity',
        )
        where_sql, query_parameters = self._append_entity_exclusion_where(
            where_sql,
            query_parameters,
            table_alias='entity',
            scopes=('all', 'actor_library'),
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN active_video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.actor_name = relation.actor_name AND meta.video_code = entity.code
                {where_sql}
                ORDER BY relation.actor_name, entity.release_date DESC, entity.code DESC
                ''',
                query_parameters,
            )

            for row in cursor.fetchall():
                actor_name = row[0] or ''
                results.setdefault(actor_name, []).append(
                    {
                        'actor_name': actor_name,
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': sanitize_actor_text(row[3] or ''),
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': int(row[6] or 1),
                        'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': normalize_video_category(row[13]),
                        'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
                    }
                )

        return {
            actor_name: self._apply_rule_set_residual(rows, rule_set=rule_set)
            for actor_name, rows in results.items()
        }
    @staticmethod
    def _upsert_code_prefix_movie_canonical(cursor, prefix, movie):
        prefix = str(prefix or '').strip().upper()
        code = standardize_video_code((movie or {}).get('code', ''))
        if not prefix or not code:
            return
        fields = (
            'title', 'author', 'release_date', 'avfan_url', 'javtxt_movie_id',
            'javtxt_url', 'javtxt_tags', 'javtxt_release_date',
            'javtxt_enrichment_status', 'javtxt_actors_raw', 'video_category',
            'supplement_enrichment_status', 'supplement_enrichment_error',
            'supplement_enriched_at',
        )
        values = [str((movie or {}).get(field, '') or '').strip() for field in fields]
        update_fields = ', '.join(
            f"{field} = CASE WHEN video_entities.{field} <> '' AND video_entities.{field} <> video_entities.code "
            f"THEN video_entities.{field} ELSE CASE WHEN excluded.{field} <> '' THEN excluded.{field} ELSE video_entities.{field} END END"
            if field in {'title', 'author', 'release_date'}
            else f"{field} = CASE WHEN excluded.{field} <> '' THEN excluded.{field} ELSE video_entities.{field} END"
            for field in fields
        )
        cursor.execute(
            f'''
            INSERT INTO video_entities (code, {', '.join(fields)})
            VALUES ({', '.join('?' for _ in ('code', *fields))})
            ON CONFLICT(code) DO UPDATE SET
                {update_fields},
                updated_at = CURRENT_TIMESTAMP
            ''',
            [code, *values],
        )
        cursor.execute(
            'INSERT OR IGNORE INTO video_code_prefix_relations (video_code, prefix) VALUES (?, ?)',
            (code, prefix),
        )
        cursor.execute(
            '''
            INSERT INTO video_prefix_relation_meta (
                video_code, prefix, avfan_url, avfan_movie_id, page_number
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_code, prefix) DO UPDATE SET
                avfan_url = CASE WHEN excluded.avfan_url <> '' THEN excluded.avfan_url ELSE video_prefix_relation_meta.avfan_url END,
                avfan_movie_id = CASE WHEN excluded.avfan_movie_id <> '' THEN excluded.avfan_movie_id ELSE video_prefix_relation_meta.avfan_movie_id END,
                page_number = CASE WHEN excluded.page_number > 0 THEN excluded.page_number ELSE video_prefix_relation_meta.page_number END
            ''',
            (
                code,
                prefix,
                str((movie or {}).get('avfan_url', '') or '').strip(),
                str((movie or {}).get('javtxt_movie_id', '') or '').strip(),
                max(1, int((movie or {}).get('page_number', 1) or 1)),
            ),
        )

    def replace_code_prefix_movies(self, prefix, movies):
        prefix = str(prefix or '').strip().upper()
        normalized_movies = []
        filter_settings = self._load_video_category_filter_settings()
        existing_movies = {row.get('code', ''): dict(row or {}) for row in self.list_code_prefix_movies(prefix)}
        if movies:
            for movie in movies:
                if not movie or not movie.get('code'):
                    continue
                normalized_code = standardize_video_code(movie.get('code', ''))
                if not normalized_code:
                    continue
                normalized_movie = dict(movie)
                normalized_movie['code'] = normalized_code
                normalized_movies.append(normalized_movie)
        processed_videos = self.get_videos_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        web_javtxt_states = self._load_web_movie_javtxt_state_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        excluded_reasons = self._list_excluded_web_movie_reasons(
            'excluded_code_prefix_movies',
            'prefix',
            [prefix],
            [movie['code'] for movie in normalized_movies],
            uppercase_owner=True,
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM video_prefix_relation_meta WHERE prefix = ?', (prefix,))
            cursor.execute('DELETE FROM video_code_prefix_relations WHERE prefix = ?', (prefix,))
            if normalized_movies:
                values = []
                excluded_movies = []
                active_codes = []
                owner_blacklisted = self._is_hidden_web_movie_owner(
                    cursor,
                    'hidden_code_prefixes',
                    'prefix',
                    prefix,
                )
                for movie in normalized_movies:
                    normalized_code = movie['code']
                    processed_record = self._merge_javtxt_state_records(
                        processed_videos.get(normalized_code, {}) or {},
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    movie_with_preserved_actor = self._merge_web_movie_actor_source(
                        movie,
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    (
                        javtxt_status,
                        javtxt_movie_id,
                        javtxt_url,
                        javtxt_tags,
                        javtxt_release_date,
                        video_category,
                    ) = self._normalize_web_movie_javtxt_fields(
                        movie_with_preserved_actor,
                        processed_record,
                        filter_settings=filter_settings,
                    )
                    author, author_raw = self._normalize_web_movie_actor_fields(
                        movie_with_preserved_actor,
                        javtxt_movie_id=javtxt_movie_id,
                        javtxt_url=javtxt_url,
                    )
                    if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                        {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                    ):
                        javtxt_status = UNENRICHED_STATUS
                    existing_movie = existing_movies.get(normalized_code, {})
                    stored_movie = {
                        **movie,
                        'code': normalized_code,
                        'author': author,
                        'release_date': javtxt_release_date or movie.get('release_date', ''),
                        'javtxt_enrichment_status': javtxt_status,
                        'javtxt_movie_id': javtxt_movie_id,
                        'javtxt_url': javtxt_url,
                        'javtxt_tags': javtxt_tags,
                        'javtxt_release_date': javtxt_release_date,
                        'author_raw': author_raw,
                        'video_category': video_category,
                        'supplement_enrichment_status': str(existing_movie.get('supplement_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                        'supplement_enrichment_error': str(existing_movie.get('supplement_enrichment_error', '') or '').strip(),
                        'supplement_enriched_at': str(existing_movie.get('supplement_enriched_at', '') or '').strip(),
                    }
                    exclusion_reason = self._resolve_web_movie_exclusion_reason(
                        stored_movie,
                        filter_settings=filter_settings,
                        owner_blacklisted=owner_blacklisted,
                        owner_reason='code_blacklist',
                    )
                    exclusion_reason = exclusion_reason or excluded_reasons.get((prefix, normalized_code), '')
                    if exclusion_reason:
                        excluded_movies.append({**stored_movie, 'exclude_reason': exclusion_reason})
                        continue
                    active_codes.append(normalized_code)
                    self._upsert_code_prefix_movie_canonical(cursor, prefix, stored_movie)
                    values.append(
                        (
                            prefix, normalized_code, stored_movie.get('title', ''), stored_movie.get('author', ''),
                            stored_movie.get('release_date', ''), stored_movie.get('avfan_url', ''),
                            int(stored_movie.get('page_number', 1) or 1), stored_movie.get('javtxt_enrichment_status', ''),
                            stored_movie.get('javtxt_movie_id', ''), stored_movie.get('javtxt_url', ''),
                            stored_movie.get('javtxt_tags', ''), stored_movie.get('javtxt_release_date', ''),
                            stored_movie.get('author_raw', ''), stored_movie.get('video_category', ''),
                            stored_movie.get('supplement_enrichment_status', UNENRICHED_STATUS),
                            stored_movie.get('supplement_enrichment_error', ''), stored_movie.get('supplement_enriched_at', ''),
                        )
                    )
                if excluded_movies:
                    self._store_excluded_web_movie_rows(
                        cursor,
                        'excluded_code_prefix_movies',
                        'prefix',
                        prefix,
                        excluded_movies,
                        ','.join(sorted({movie.get('exclude_reason', '') for movie in excluded_movies})),
                    )
                if values:
                    self._propagate_web_movie_javtxt_state_for_codes(cursor, active_codes)
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses([prefix])
    @staticmethod
    def _upsert_actor_movie_canonical(cursor, actor_name, movie):
        code = standardize_video_code((movie or {}).get('code', ''))
        actor_name = str(actor_name or '').strip()
        if not code or not actor_name:
            return
        fields = (
            'title', 'author', 'release_date', 'avfan_url', 'javtxt_movie_id',
            'javtxt_url', 'javtxt_tags', 'javtxt_release_date',
            'javtxt_enrichment_status', 'javtxt_actors_raw', 'video_category',
            'supplement_enrichment_status', 'supplement_enrichment_error',
            'supplement_enriched_at',
        )
        values = [str((movie or {}).get(field, '') or '').strip() for field in fields]
        update_fields = ', '.join(
            f"{field} = CASE WHEN video_entities.{field} <> '' AND video_entities.{field} <> video_entities.code "
            f"THEN video_entities.{field} ELSE CASE WHEN excluded.{field} <> '' THEN excluded.{field} ELSE video_entities.{field} END END"
            if field in {'title', 'author', 'release_date'}
            else f"{field} = CASE WHEN excluded.{field} <> '' THEN excluded.{field} ELSE video_entities.{field} END"
            for field in fields
        )
        cursor.execute(
            f'''
            INSERT INTO video_entities (code, {', '.join(fields)})
            VALUES ({', '.join('?' for _ in ('code', *fields))})
            ON CONFLICT(code) DO UPDATE SET
                {update_fields},
                updated_at = CURRENT_TIMESTAMP
            ''',
            [code, *values],
        )
        cursor.execute(
            'INSERT OR IGNORE INTO video_actor_relations (video_code, actor_name) VALUES (?, ?)',
            (code, actor_name),
        )
        cursor.execute(
            '''
            INSERT INTO video_actor_relation_meta (
                video_code, actor_name, avfan_url, avfan_movie_id, page_number
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(video_code, actor_name) DO UPDATE SET
                avfan_url = CASE WHEN excluded.avfan_url <> '' THEN excluded.avfan_url ELSE video_actor_relation_meta.avfan_url END,
                avfan_movie_id = CASE WHEN excluded.avfan_movie_id <> '' THEN excluded.avfan_movie_id ELSE video_actor_relation_meta.avfan_movie_id END,
                page_number = CASE WHEN excluded.page_number > 0 THEN excluded.page_number ELSE video_actor_relation_meta.page_number END
            ''',
            (
                code,
                actor_name,
                str((movie or {}).get('avfan_url', '') or '').strip(),
                str((movie or {}).get('javtxt_movie_id', '') or '').strip(),
                max(1, int((movie or {}).get('page_number', 1) or 1)),
            ),
        )

    def replace_actor_movies(self, actor_name, movies):
        normalized_name = str(actor_name or '').strip()
        normalized_movies = []
        filter_settings = self._load_video_category_filter_settings()
        existing_movies = {row.get('code', ''): dict(row or {}) for row in self.list_actor_movies(normalized_name)}
        if movies:
            for movie in movies:
                if not movie or not movie.get('code'):
                    continue
                normalized_code = standardize_video_code(movie.get('code', ''))
                if not normalized_code:
                    continue
                normalized_movie = dict(movie)
                normalized_movie['code'] = normalized_code
                normalized_movies.append(normalized_movie)
        processed_videos = self.get_videos_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        web_javtxt_states = self._load_web_movie_javtxt_state_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        excluded_reasons = self._list_excluded_web_movie_reasons(
            'excluded_actor_movies',
            'actor_name',
            [normalized_name],
            [movie['code'] for movie in normalized_movies],
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM video_actor_relation_meta WHERE actor_name = ?',
                (normalized_name,),
            )
            cursor.execute(
                'DELETE FROM video_actor_relations WHERE actor_name = ?',
                (normalized_name,),
            )
            if normalized_movies:
                excluded_movies = []
                legacy_values = []
                active_codes = []
                owner_blacklisted = self._is_hidden_web_movie_owner(
                    cursor,
                    'hidden_actors',
                    'name',
                    normalized_name,
                )
                for movie in normalized_movies:
                    normalized_code = movie['code']
                    processed_record = self._merge_javtxt_state_records(
                        processed_videos.get(normalized_code, {}) or {},
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    movie_with_preserved_actor = self._merge_web_movie_actor_source(
                        movie,
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    (
                        javtxt_status,
                        javtxt_movie_id,
                        javtxt_url,
                        javtxt_tags,
                        javtxt_release_date,
                        video_category,
                    ) = self._normalize_web_movie_javtxt_fields(
                        movie_with_preserved_actor,
                        processed_record,
                        filter_settings=filter_settings,
                    )
                    author, author_raw = self._normalize_web_movie_actor_fields(
                        movie_with_preserved_actor,
                        javtxt_movie_id=javtxt_movie_id,
                        javtxt_url=javtxt_url,
                    )
                    if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                        {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                    ):
                        javtxt_status = UNENRICHED_STATUS
                    existing_movie = existing_movies.get(normalized_code, {})
                    stored_movie = {
                        **movie,
                        'code': normalized_code,
                        'author': author,
                        'release_date': javtxt_release_date or movie.get('release_date', ''),
                        'javtxt_enrichment_status': javtxt_status,
                        'javtxt_movie_id': javtxt_movie_id,
                        'javtxt_url': javtxt_url,
                        'javtxt_tags': javtxt_tags,
                        'javtxt_release_date': javtxt_release_date,
                        'author_raw': author_raw,
                        'video_category': video_category,
                        'supplement_enrichment_status': str(existing_movie.get('supplement_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                        'supplement_enrichment_error': str(existing_movie.get('supplement_enrichment_error', '') or '').strip(),
                        'supplement_enriched_at': str(existing_movie.get('supplement_enriched_at', '') or '').strip(),
                    }
                    exclusion_reason = self._resolve_web_movie_exclusion_reason(
                        stored_movie,
                        filter_settings=filter_settings,
                        owner_blacklisted=owner_blacklisted,
                        owner_reason='actor_blacklist',
                    )
                    exclusion_reason = exclusion_reason or excluded_reasons.get((normalized_name, normalized_code), '')
                    if exclusion_reason:
                        excluded_movies.append({**stored_movie, 'exclude_reason': exclusion_reason})
                        continue
                    active_codes.append(normalized_code)
                    self._upsert_actor_movie_canonical(cursor, normalized_name, stored_movie)
                    legacy_values.append(
                        (
                            normalized_name, normalized_code, stored_movie.get('title', ''),
                            stored_movie.get('author', ''), stored_movie.get('release_date', ''),
                            stored_movie.get('avfan_url', ''), int(stored_movie.get('page_number', 1) or 1),
                            stored_movie.get('javtxt_enrichment_status', ''), stored_movie.get('javtxt_movie_id', ''),
                            stored_movie.get('javtxt_url', ''), stored_movie.get('javtxt_tags', ''),
                            stored_movie.get('javtxt_release_date', ''), stored_movie.get('author_raw', ''),
                            stored_movie.get('video_category', ''), stored_movie.get('supplement_enrichment_status', UNENRICHED_STATUS),
                            stored_movie.get('supplement_enrichment_error', ''), stored_movie.get('supplement_enriched_at', ''),
                        )
                    )
                if excluded_movies:
                    self._store_excluded_web_movie_rows(
                        cursor,
                        'excluded_actor_movies',
                        'actor_name',
                        normalized_name,
                        excluded_movies,
                        ','.join(sorted({movie.get('exclude_reason', '') for movie in excluded_movies})),
                    )
                if active_codes:
                    self._propagate_web_movie_javtxt_state_for_codes(cursor, active_codes)
            conn.commit()
        self.refresh_actor_javtxt_statuses([normalized_name])
    def rebuild_active_video_entities(self):
        """Materialize the non-excluded archive rows used by UI and enrichment."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM active_video_entities')
            cursor.execute(
                '''
                INSERT INTO active_video_entities (
                    code, title, author, release_date, maker, publisher, avfan_url, avfan_movie_id,
                    javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_actors_raw,
                    javtxt_tags, javtxt_release_date, javtxt_enrichment_status, video_category,
                    supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at,
                    enrichment_status, enrichment_error, enriched_at, avfan_enrichment_status,
                    avfan_enrichment_error, avfan_enriched_at, description, javtxt_description,
                    avfan_actors, avfan_tags, duration, size, storage_location, updated_at
                )
                SELECT entity.code, entity.title, entity.author, entity.release_date,
                       entity.maker, entity.publisher, entity.avfan_url, entity.avfan_movie_id,
                       entity.javtxt_movie_id, entity.javtxt_url, entity.javtxt_title,
                       entity.javtxt_actors, entity.javtxt_actors_raw, entity.javtxt_tags,
                       entity.javtxt_release_date, entity.javtxt_enrichment_status,
                       entity.video_category, entity.supplement_enrichment_status,
                       entity.supplement_enrichment_error, entity.supplement_enriched_at,
                       entity.enrichment_status, entity.enrichment_error, entity.enriched_at,
                       entity.avfan_enrichment_status, entity.avfan_enrichment_error,
                       entity.avfan_enriched_at, entity.description, entity.javtxt_description,
                       entity.avfan_actors, entity.avfan_tags, COALESCE(local.duration, ''),
                       COALESCE(local.size, ''), COALESCE(local.storage_location, ''),
                       CURRENT_TIMESTAMP
                FROM video_entities AS entity
                LEFT JOIN local_video_records AS local ON local.code = entity.code
                WHERE NOT EXISTS (
                    SELECT 1 FROM video_entity_exclusions AS exclusion
                    WHERE exclusion.code = entity.code
                      AND exclusion.scope = 'all'
                )
                '''
            )
            self._set_runtime_meta(
                cursor,
                VIDEO_ENTITY_MATERIALIZATION_META_KEY,
                VIDEO_ENTITY_MATERIALIZATION_VERSION,
            )
            conn.commit()
        return int(cursor.rowcount or 0)
    def list_sql_javtxt_video_candidates(self, limit, rule_set=None):
        """Return a bounded, retryable JAVTXT video set from SQLite."""
        normalized_limit = max(0, int(limit or 0))
        if normalized_limit <= 0:
            return []
        where_sql = '''
            WHERE COALESCE(NULLIF(TRIM(p.javtxt_enrichment_status), ''), ?) IN (?, ?)
              AND COALESCE(NULLIF(TRIM(p.javtxt_release_date), ''), NULLIF(TRIM(p.release_date), '')) >= '2020-01-01'
              AND p.code LIKE '%-%'
              AND NOT EXISTS (
                    SELECT 1 FROM video_entity_exclusions AS ex
                    WHERE ex.code = p.code
                      AND ex.scope IN ('all', 'javtxt')
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM pending_video_javtxt AS pending
                    WHERE pending.code = p.code
                      AND pending.status IN ('pending', 'failed')
                  )
              AND NOT EXISTS (
                    SELECT 1 FROM enrichment_running_items AS running
                    WHERE running.task_kind = 'video'
                      AND running.origin_table = 'pending_video_javtxt'
                      AND running.code = p.code
                  )
        '''
        where_sql, query_parameters = self._append_rule_set_where(
            where_sql,
            [UNENRICHED_STATUS, UNENRICHED_STATUS, FAILED_STATUS],
            rule_set=rule_set,
            table_alias='p',
            scope='pre_enrichment',
        )
        query_parameters.append(normalized_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT p.code,
                       COALESCE(NULLIF(p.javtxt_title, ''), NULLIF(p.title, ''), p.code),
                       p.author,
                       p.javtxt_actors, p.javtxt_actors_raw,
                       p.javtxt_movie_id, p.javtxt_url, p.javtxt_tags,
                       p.javtxt_enrichment_status, p.release_date,
                       p.video_category, p.javtxt_release_date,
                       p.supplement_enrichment_status
                FROM active_video_entities AS p
                {where_sql}
                ORDER BY p.code ASC
                LIMIT ?
                ''',
                query_parameters,
            ).fetchall()
        return [
            {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[3] or ''),
                'author_raw': self._normalize_actor_raw_text(row[4] or row[2] or ''),
                'local_author': sanitize_actor_text(row[2] or ''),
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_tags': row[7] or '',
                'javtxt_enrichment_status': row[8] or UNENRICHED_STATUS,
                'release_date': row[9] or '',
                'video_category': normalize_video_category(row[10]),
                'javtxt_release_date': row[11] or '',
                'supplement_enrichment_status': row[12] or UNENRICHED_STATUS,
            }
            for row in rows
        ]
    def list_video_supplement_candidates(self, limit, include_queued=False, running_plan_id=''):
        limit = max(int(limit or 0), 0)
        if limit <= 0:
            return []

        candidates = []
        filter_settings = load_video_filter_settings()
        sql_rows = self.list_sql_supplement_candidates(
            'video',
            max(limit * 20, limit),
            include_queued=include_queued,
            running_plan_id=running_plan_id,
        )
        for record in sql_rows:
            candidate = build_supplement_candidate(record, filter_settings=filter_settings)
            if not candidate:
                continue
            candidates.append({**record, **candidate})
        candidates.sort(
            key=lambda row: (
                99 if row.get('supplement_priority') is None else int(row.get('supplement_priority')),
                str(row.get('code', '') or ''),
            )
        )
        return candidates[:limit]

    def count_pending_video_supplements(self):
        return len(self.list_video_supplement_candidates(999999))

    def save_video_supplement_status(self, code, status, error=''):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return 0
        normalized_status = str(status or '').strip() or UNENRICHED_STATUS
        normalized_error = str(error or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_write_table = 'video_entities'
            cursor.execute(
                f'''
                UPDATE {processed_write_table}
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_status, normalized_error, normalized_code),
            )
            cursor.execute(
                '''
                UPDATE video_entities
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_status, normalized_error, normalized_code),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_code_prefix_movie_supplement_status(self, prefix, code, status, error=''):
        normalized_prefix = str(prefix or '').strip().upper()
        normalized_code = standardize_video_code(code)
        if not normalized_prefix or not normalized_code:
            return 0
        normalized_status = str(status or '').strip() or UNENRICHED_STATUS
        normalized_error = str(error or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE video_entities
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_status, normalized_error, normalized_code),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_actor_movie_supplement_status(self, actor_name, code, status, error=''):
        normalized_name = str(actor_name or '').strip()
        normalized_code = standardize_video_code(code)
        if not normalized_name or not normalized_code:
            return 0
        normalized_status = str(status or '').strip() or UNENRICHED_STATUS
        normalized_error = str(error or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE video_entities
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_status, normalized_error, normalized_code),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
