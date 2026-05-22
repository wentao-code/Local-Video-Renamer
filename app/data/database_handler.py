import sqlite3
from pathlib import Path

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.core.project_paths import DATABASE_FILE
from app.services.actor_identifier import IGNORED_ACTOR_NAMES, is_ignored_actor_name


def join_values(value):
    if isinstance(value, (list, tuple)):
        return ' '.join(str(item) for item in value if str(item).strip())
    return str(value or '')


class VideoDatabase:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DATABASE_FILE
        self._init_db()

    def _init_db(self):
        """初始化表结构（以 code 为主键实现绝对去重）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    code TEXT PRIMARY KEY,
                    title TEXT,
                    author TEXT,
                    duration TEXT,
                    size TEXT,
                    storage_location TEXT,
                    avfan_movie_id TEXT,
                    release_date TEXT,
                    maker TEXT,
                    publisher TEXT,
                    enrichment_status TEXT DEFAULT '未补全',
                    enrichment_error TEXT,
                    enriched_at TEXT
                )
            ''')
            self._ensure_column(cursor, 'processed_videos', 'storage_location', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_movie_id', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'maker', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'publisher', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enriched_at', 'TEXT')
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = '未补全'
                WHERE enrichment_status IS NULL OR enrichment_status = ''
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actors (
                    name TEXT PRIMARY KEY,
                    birthday TEXT,
                    age TEXT,
                    matched INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS path_library (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_total_bytes INTEGER DEFAULT 0,
                    last_used_bytes INTEGER DEFAULT 0,
                    last_free_bytes INTEGER DEFAULT 0,
                    last_usage_percent REAL DEFAULT 0,
                    last_volume_type TEXT DEFAULT '',
                    last_checked_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_prefix_enrichments (
                    prefix TEXT PRIMARY KEY,
                    enrichment_status TEXT DEFAULT '',
                    avfan_total_pages INTEGER DEFAULT 0,
                    avfan_total_videos INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    last_enriched_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_prefix_movies (
                    prefix TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (prefix, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_enrichments (
                    actor_name TEXT PRIMARY KEY,
                    enrichment_status TEXT DEFAULT '',
                    avfan_total_pages INTEGER DEFAULT 0,
                    avfan_total_videos INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    last_enriched_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_movies (
                    actor_name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (actor_name, code)
                )
            ''')
            self._ensure_column(cursor, 'path_library', 'last_total_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_used_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_free_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_usage_percent', 'REAL DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_volume_type', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'path_library', 'last_checked_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'page_number', 'INTEGER DEFAULT 1')
            self._ensure_column(cursor, 'actor_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'page_number', 'INTEGER DEFAULT 1')
            cursor.executemany(
                'DELETE FROM actors WHERE lower(name) = ?',
                [(name,) for name in IGNORED_ACTOR_NAMES],
            )
            conn.commit()

    def _ensure_column(self, cursor, table_name, column_name, column_type):
        cursor.execute(f'PRAGMA table_info({table_name})')
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for plan in plans:
                cursor.execute('''
                    INSERT INTO processed_videos (
                        code, title, author, duration, size, storage_location, enrichment_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, '未补全')
                    ON CONFLICT(code) DO UPDATE SET
                        title = excluded.title,
                        author = excluded.author,
                        duration = excluded.duration,
                        size = excluded.size,
                        storage_location = excluded.storage_location,
                        enrichment_status = COALESCE(NULLIF(processed_videos.enrichment_status, ''), '未补全')
                ''', (
                    plan.metadata.code,
                    plan.metadata.title,
                    plan.metadata.author,
                    plan.metadata.duration,
                    plan.metadata.size,
                    plan.storage_location
                ))
                success_count += 1
            conn.commit()

        return success_count

    def save_actors(self, actors):
        """将识别出的演员单独写入演员表。"""
        if not actors:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for actor in actors:
                name = actor.get('name', '').strip()
                if not name or is_ignored_actor_name(name):
                    continue

                cursor.execute('''
                    REPLACE INTO actors (name, birthday, age, matched)
                    VALUES (?, ?, ?, ?)
                ''', (
                    name,
                    actor.get('birthday', ''),
                    actor.get('age', ''),
                    1 if actor.get('matched') else 0,
                ))
                success_count += 1
            conn.commit()

        return success_count

    def list_actors(self, search_text=''):
        """读取演员库，必要时按主角/生日/年龄筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT name, birthday, age, matched
                    FROM actors
                    WHERE name LIKE ? OR birthday LIKE ? OR age LIKE ?
                    ORDER BY name
                ''', (like_value, like_value, like_value))
            else:
                cursor.execute('''
                    SELECT name, birthday, age, matched
                    FROM actors
                    ORDER BY name
                ''')

            return [
                {
                    'name': row[0] or '',
                    'birthday': row[1] or '',
                    'age': row[2] or '',
                    'matched': bool(row[3]),
                }
                for row in cursor.fetchall()
                if not is_ignored_actor_name(row[0] or '')
            ]

    def list_videos(self, search_text=''):
        """读取数据库台账，必要时按编号/标题/演员筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, release_date, maker, publisher, enrichment_status
                    FROM processed_videos
                    WHERE code LIKE ? OR title LIKE ? OR author LIKE ? OR storage_location LIKE ?
                       OR avfan_movie_id LIKE ? OR release_date LIKE ? OR maker LIKE ? OR publisher LIKE ?
                       OR enrichment_status LIKE ?
                    ORDER BY code
                ''', (
                    like_value, like_value, like_value, like_value, like_value,
                    like_value, like_value, like_value, like_value,
                ))
            else:
                cursor.execute('''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, release_date, maker, publisher, enrichment_status
                    FROM processed_videos
                    ORDER BY code
                ''')

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                    'duration': row[3] or '',
                    'size': row[4] or '',
                    'storage_location': row[5] or '',
                    'avfan_movie_id': row[6] or '',
                    'release_date': row[7] or '',
                    'maker': row[8] or '',
                    'publisher': row[9] or '',
                    'enrichment_status': row[10] or '未补全',
                }
                for row in cursor.fetchall()
            ]

    def list_videos_for_enrichment(self, limit):
        """读取需要补全的未补全视频。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, title, author
                FROM processed_videos
                WHERE COALESCE(enrichment_status, '未补全') != '已补全'
                ORDER BY code
                LIMIT ?
            ''', (int(limit),))

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def update_video_enrichment(self, code, info, status='已补全'):
        """写入网页补全信息。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET avfan_movie_id = ?,
                    release_date = ?,
                    maker = ?,
                    publisher = ?,
                    enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (
                info.get('avfan_movie_id', ''),
                info.get('release_date', ''),
                join_values(info.get('maker')),
                join_values(info.get('publisher')),
                status,
                info.get('error', ''),
                code,
            ))
            conn.commit()

    def mark_video_enrichment_failed(self, code, error):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = '补全失败',
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (error, code))
            conn.commit()

    def count_videos_by_enrichment_status(self, status):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE(enrichment_status, '未补全') = ?
            ''', (status,))
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        CASE
                            WHEN COALESCE(enrichment_status, '鏈ˉ鍏?) = '宸茶ˉ鍏? THEN 1
                            ELSE 0
                        END
                    ) AS enriched_count
                FROM processed_videos
            ''')
            row = cursor.fetchone() or (0, 0)

        total_count = int(row[0] or 0)
        enriched_count = int(row[1] or 0)
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def add_path(self, folder_path):
        """写入一个路径库记录，已存在时保持一条记录。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO path_library (path)
                VALUES (?)
            ''', (folder_path,))
            conn.commit()

        return self.get_path_by_value(folder_path)

    def delete_path(self, path_id):
        """按 id 删除路径库记录。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM path_library WHERE id = ?', (path_id,))
            conn.commit()
            return cursor.rowcount

    def list_paths(self):
        """读取路径库。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, path, created_at, last_total_bytes, last_used_bytes,
                       last_free_bytes, last_usage_percent, last_volume_type, last_checked_at
                FROM path_library
                ORDER BY created_at DESC, id DESC
            ''')

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
        """保存路径最后一次成功检测到的容量快照。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE path_library
                SET last_total_bytes = ?,
                    last_used_bytes = ?,
                    last_free_bytes = ?,
                    last_usage_percent = ?,
                    last_volume_type = ?,
                    last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                storage_info.get('total_bytes', 0),
                storage_info.get('used_bytes', 0),
                storage_info.get('free_bytes', 0),
                storage_info.get('usage_percent', 0),
                storage_info.get('volume_type', ''),
                path_id,
            ))
            conn.commit()

    def list_videos_for_enrichment(self, limit):
        """只返回仍应继续补全的视频，跳过已补全和无搜索结果。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, title, author
                FROM processed_videos
                WHERE COALESCE(enrichment_status, ?) IN (?, ?)
                ORDER BY code
                LIMIT ?
            ''', (
                UNENRICHED_STATUS,
                UNENRICHED_STATUS,
                FAILED_STATUS,
                int(limit),
            ))

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def mark_video_no_search_results(self, code, error='未搜索到匹配影片'):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (NO_SEARCH_RESULTS_STATUS, error, code))
            conn.commit()

    def mark_video_enrichment_failed(self, code, error):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (FAILED_STATUS, error, code))
            conn.commit()

    def count_videos_by_enrichment_status(self, status):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE(enrichment_status, ?) = ?
            ''', (UNENRICHED_STATUS, status))
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        CASE
                            WHEN COALESCE(enrichment_status, ?) = ? THEN 1
                            ELSE 0
                        END
                    ) AS enriched_count
                FROM processed_videos
            ''', (UNENRICHED_STATUS, ENRICHED_STATUS))
            row = cursor.fetchone() or (0, 0)

        total_count = int(row[0] or 0)
        enriched_count = int(row[1] or 0)
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def list_code_prefix_enrichment_records(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at
                FROM code_prefix_enrichments
            ''')

            return {
                (row[0] or ''): {
                    'prefix': row[0] or '',
                    'enrichment_status': row[1] or '',
                    'avfan_total_pages': int(row[2] or 0),
                    'avfan_total_videos': int(row[3] or 0),
                    'last_error': row[4] or '',
                    'last_enriched_at': row[5] or '',
                }
                for row in cursor.fetchall()
                if row[0]
            }

    def save_code_prefix_enrichment(self, prefix, status, total_pages=0, total_videos=0, error=''):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO code_prefix_enrichments (
                    prefix, enrichment_status, avfan_total_pages, avfan_total_videos, last_error, last_enriched_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(prefix) DO UPDATE SET
                    enrichment_status = excluded.enrichment_status,
                    avfan_total_pages = excluded.avfan_total_pages,
                    avfan_total_videos = excluded.avfan_total_videos,
                    last_error = excluded.last_error,
                    last_enriched_at = CURRENT_TIMESTAMP
            ''', (
                str(prefix or '').strip().upper(),
                status,
                int(total_pages or 0),
                int(total_videos or 0),
                str(error or ''),
            ))
            conn.commit()

    def replace_code_prefix_movies(self, prefix, movies):
        prefix = str(prefix or '').strip().upper()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (prefix,))
            if movies:
                cursor.executemany('''
                    INSERT OR REPLACE INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', [
                    (
                        prefix,
                        str(movie.get('code', '')).strip().upper(),
                        movie.get('title', ''),
                        movie.get('author', ''),
                        movie.get('release_date', ''),
                        movie.get('avfan_url', ''),
                        int(movie.get('page_number', 1) or 1),
                    )
                    for movie in movies
                    if movie.get('code')
                ])
            conn.commit()

    def get_code_prefix_enrichment_record(self, prefix):
        prefix = str(prefix or '').strip().upper()
        records = self.list_code_prefix_enrichment_records()
        return records.get(prefix, {
            'prefix': prefix,
            'enrichment_status': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'last_error': '',
            'last_enriched_at': '',
        })

    def list_code_prefix_movies(self, prefix):
        prefix = str(prefix or '').strip().upper()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number
                FROM code_prefix_movies
                WHERE prefix = ?
                ORDER BY release_date DESC, code DESC
            ''', (prefix,))

            return [
                {
                    'prefix': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': row[3] or '',
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                }
                for row in cursor.fetchall()
            ]

    def list_actor_enrichment_records(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at
                FROM actor_enrichments
            ''')

            return {
                (row[0] or ''): {
                    'actor_name': row[0] or '',
                    'enrichment_status': row[1] or '',
                    'avfan_total_pages': int(row[2] or 0),
                    'avfan_total_videos': int(row[3] or 0),
                    'last_error': row[4] or '',
                    'last_enriched_at': row[5] or '',
                }
                for row in cursor.fetchall()
                if row[0]
            }

    def save_actor_enrichment(self, actor_name, status, total_pages=0, total_videos=0, error=''):
        normalized_name = str(actor_name or '').strip()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO actor_enrichments (
                    actor_name, enrichment_status, avfan_total_pages, avfan_total_videos, last_error, last_enriched_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(actor_name) DO UPDATE SET
                    enrichment_status = excluded.enrichment_status,
                    avfan_total_pages = excluded.avfan_total_pages,
                    avfan_total_videos = excluded.avfan_total_videos,
                    last_error = excluded.last_error,
                    last_enriched_at = CURRENT_TIMESTAMP
            ''', (
                normalized_name,
                status,
                int(total_pages or 0),
                int(total_videos or 0),
                str(error or ''),
            ))
            conn.commit()

    def replace_actor_movies(self, actor_name, movies):
        normalized_name = str(actor_name or '').strip()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            if movies:
                cursor.executemany('''
                    INSERT OR REPLACE INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', [
                    (
                        normalized_name,
                        str(movie.get('code', '')).strip().upper(),
                        movie.get('title', ''),
                        movie.get('author', ''),
                        movie.get('release_date', ''),
                        movie.get('avfan_url', ''),
                        int(movie.get('page_number', 1) or 1),
                    )
                    for movie in movies
                    if movie.get('code')
                ])
            conn.commit()

    def get_actor_enrichment_record(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        records = self.list_actor_enrichment_records()
        return records.get(normalized_name, {
            'actor_name': normalized_name,
            'enrichment_status': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'last_error': '',
            'last_enriched_at': '',
        })

    def list_actor_movies(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number
                FROM actor_movies
                WHERE actor_name = ?
                ORDER BY release_date DESC, code DESC
            ''', (normalized_name,))

            return [
                {
                    'actor_name': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': row[3] or '',
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                }
                for row in cursor.fetchall()
            ]

    def get_path_by_value(self, folder_path):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, path, created_at, last_total_bytes, last_used_bytes,
                       last_free_bytes, last_usage_percent, last_volume_type, last_checked_at
                FROM path_library
                WHERE path = ?
            ''', (folder_path,))
            row = cursor.fetchone()

        if not row:
            return None

        return {
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
