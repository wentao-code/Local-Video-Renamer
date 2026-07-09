import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

from app.core.project_paths import QUEEN_LIBRARY_CRAWL_LOG_FILE, QUEEN_LIBRARY_DB_FILE
from app.scraper.queen_search_scraper import QueenSearchScraper


QUEEN_RECORD_PREFIX = '\u5957\u8def\u76f4\u64ad_'
MEDIA_SUFFIXES = {'.mp4', '.mkv', '.avi', '.wmv', '.mov'}
QUEEN_VIDEO_CONTENT_TYPES = ('\u8fb1\u9a82', '\u804a\u5929', '\u8c03\u6559')
QUEEN_VIDEO_CONTENT_LEVELS = ('S', 'A', 'B', 'C')
QUEEN_PROFILE_FIELDS = {
    'body_type': ('身材', ('苗条', '肥胖')),
    'style': ('风格', ('温和', '粗暴')),
    'face': ('露脸', ('是', '否')),
    'age_group': ('年龄', ('萝莉', '少妇', '熟女')),
    'like_level': ('喜欢等级', ('A', 'B', 'C', 'D')),
}


class QueenLibraryService:
    def __init__(self, db_path=None, scraper=None, crawl_log_path=None):
        self.db_path = Path(db_path) if db_path else QUEEN_LIBRARY_DB_FILE
        self.scraper = scraper or QueenSearchScraper(headless=False)
        self.crawl_log_path = Path(crawl_log_path) if crawl_log_path else QUEEN_LIBRARY_CRAWL_LOG_FILE
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA busy_timeout = 60000')
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword_id INTEGER NOT NULL,
                    raw_title TEXT NOT NULL,
                    queen_name TEXT NOT NULL,
                    video_title TEXT NOT NULL,
                    source_url TEXT DEFAULT '',
                    detail_url TEXT DEFAULT '',
                    content_type TEXT DEFAULT '',
                    content_level TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(keyword_id) REFERENCES queen_keywords(id),
                    UNIQUE(queen_name, video_title)
                )
                '''
            )
            self._ensure_column(cursor, 'queen_videos', 'detail_url', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'queen_videos', 'content_type', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'queen_videos', 'content_level', "TEXT DEFAULT ''")
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_import_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword_id INTEGER NOT NULL,
                    source_url TEXT DEFAULT '',
                    scanned_count INTEGER DEFAULT 0,
                    imported_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(keyword_id) REFERENCES queen_keywords(id)
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_profiles (
                    queen_name TEXT PRIMARY KEY,
                    body_type TEXT DEFAULT '',
                    style TEXT DEFAULT '',
                    face TEXT DEFAULT '',
                    age_group TEXT DEFAULT '',
                    like_level TEXT DEFAULT '',
                    profile_confirmed INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.commit()

    def search_keyword(self, keyword, show_browser=True):
        normalized_keyword = str(keyword or '').strip()
        if not normalized_keyword:
            raise ValueError('\u7f3a\u5c11\u5173\u952e\u8bcd')
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM queen_keywords WHERE keyword = ?', (normalized_keyword,))
            if cursor.fetchone() is not None:
                raise ValueError('\u5173\u952e\u8bcd\u5df2\u5b58\u5728')

        result = self._search_and_import_keyword(normalized_keyword, show_browser=show_browser)
        return {
            **result,
            'keywords': self.list_keywords(),
            'queens': self.list_queens(),
        }

    def refresh_all(self, show_browser=True, batch_size=None, progress_callback=None):
        started_at = self._current_timestamp()
        keywords = self.build_refresh_keywords()
        query_results = []
        scanned_count = 0
        imported_count = 0
        skipped_count = 0
        processed_count = 0
        normalized_batch_size = self._normalize_batch_size(batch_size)

        session_factory = getattr(self.scraper, 'session', None)
        session_context = session_factory() if callable(session_factory) else nullcontext(None)
        # Keep one browser page alive for the whole refresh batch so each
        # keyword search only navigates to a new URL instead of reopening Chrome.
        with session_context as page:
            for keyword in keywords:
                result = self._search_and_import_keyword(keyword, show_browser=show_browser, page=page)
                query_result = {
                    'keyword': keyword,
                    'source_url': result.get('source_url', ''),
                    'scanned_count': int(result.get('scanned_count', 0) or 0),
                    'imported_count': int(result.get('imported_count', 0) or 0),
                    'skipped_count': int(result.get('skipped_count', 0) or 0),
                }
                query_results.append(query_result)
                scanned_count += query_result['scanned_count']
                imported_count += query_result['imported_count']
                skipped_count += query_result['skipped_count']
                processed_count += 1
                if normalized_batch_size and processed_count % normalized_batch_size == 0:
                    self._emit_refresh_progress(
                        progress_callback,
                        started_at,
                        show_browser,
                        keywords,
                        query_results,
                        scanned_count,
                        imported_count,
                        skipped_count,
                        processed_count,
                        completed=False,
                    )

        payload = {
            'started_at': started_at,
            'completed_at': self._current_timestamp(),
            'show_browser': bool(show_browser),
            'query_count': len(keywords),
            'processed_count': processed_count,
            'scanned_count': scanned_count,
            'imported_count': imported_count,
            'skipped_count': skipped_count,
            'queries': query_results,
            'log_path': str(self.crawl_log_path),
            'keywords': self.list_keywords(),
            'queens': self.list_queens(),
        }
        self._append_crawl_log(payload)
        if callable(progress_callback):
            progress_callback({
                **payload,
                'total_count': len(keywords),
                'completed': True,
            })
        return payload

    def build_refresh_keywords(self):
        candidates = []
        for row in self.list_keywords():
            keyword = str((row or {}).get('keyword', '') or '').strip()
            if keyword:
                candidates.append(keyword)
        for row in self.list_queens():
            queen_name = str((row or {}).get('queen_name', '') or '').strip()
            if queen_name:
                candidates.append(f'{QUEEN_RECORD_PREFIX}{queen_name}')
        return self._dedupe_keep_order(candidates)

    def _search_and_import_keyword(self, keyword, show_browser=True, page=None):
        normalized_keyword = str(keyword or '').strip()
        if not normalized_keyword:
            raise ValueError('\u7f3a\u5c11\u5173\u952e\u8bcd')

        if page is None:
            scraped = dict(self.scraper.search(normalized_keyword, show_browser=show_browser) or {})
        else:
            scraped = dict(self.scraper.search(normalized_keyword, show_browser=show_browser, page=page) or {})
        source_url = str(scraped.get('source_url', '') or '').strip()
        records = list(scraped.get('records', []) or [])
        imported_count = 0
        skipped_count = 0

        with self._connect() as conn:
            cursor = conn.cursor()
            keyword_id = self._get_or_create_keyword_id(cursor, normalized_keyword)
            for record in records:
                raw_title, detail_url = self._normalize_scraped_record(record)
                parsed = self.parse_record_title(raw_title)
                if parsed is None:
                    skipped_count += 1
                    continue
                try:
                    cursor.execute(
                        '''
                        INSERT INTO queen_videos(keyword_id, raw_title, queen_name, video_title, source_url, detail_url)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            keyword_id,
                            parsed['raw_title'],
                            parsed['queen_name'],
                            parsed['video_title'],
                            source_url,
                            detail_url,
                        ),
                    )
                    imported_count += 1
                except sqlite3.IntegrityError:
                    if detail_url:
                        cursor.execute(
                            '''
                            UPDATE queen_videos
                            SET detail_url = ?
                            WHERE queen_name = ? AND video_title = ? AND COALESCE(detail_url, '') = ''
                            ''',
                            (detail_url, parsed['queen_name'], parsed['video_title']),
                        )
                    skipped_count += 1
            cursor.execute(
                '''
                INSERT INTO queen_import_logs(keyword_id, source_url, scanned_count, imported_count, skipped_count)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (keyword_id, source_url, len(records), imported_count, skipped_count),
            )
            conn.commit()

        return {
            'keyword': normalized_keyword,
            'source_url': source_url,
            'scanned_count': len(records),
            'imported_count': imported_count,
            'skipped_count': skipped_count,
        }

    def list_keywords(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT id, keyword, created_at
                FROM queen_keywords
                ORDER BY created_at DESC, id DESC
                '''
            ).fetchall()
        return [dict(row) for row in rows]

    def list_queens(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT
                    videos.queen_name,
                    COUNT(*) AS video_count,
                    MAX(videos.created_at) AS last_created_at,
                    COALESCE(profiles.profile_confirmed, 0) AS profile_confirmed
                FROM queen_videos AS videos
                LEFT JOIN queen_profiles AS profiles ON profiles.queen_name = videos.queen_name
                GROUP BY videos.queen_name
                ORDER BY videos.queen_name COLLATE NOCASE ASC
                '''
            ).fetchall()
        return [dict(row) for row in rows]

    def get_queen_detail(self, queen_name):
        normalized_name = str(queen_name or '').strip()
        if not normalized_name:
            raise ValueError('\u7f3a\u5c11\u5973\u738b\u540d\u79f0')
        with self._connect() as conn:
            profile = self._get_profile_from_connection(conn, normalized_name)
            rows = conn.execute(
                '''
                SELECT id, raw_title, queen_name, video_title, source_url, detail_url,
                       content_type, content_level, created_at
                FROM queen_videos
                WHERE queen_name = ?
                ORDER BY created_at DESC, id DESC
                ''',
                (normalized_name,),
            ).fetchall()
        return {
            'queen_name': normalized_name,
            'profile': profile,
            'videos': [dict(row) for row in rows],
        }

    def save_queen_profile(self, queen_name, profile):
        normalized_name = str(queen_name or '').strip()
        if not normalized_name:
            raise ValueError('\u7f3a\u5c11\u5973\u738b\u540d\u79f0')
        normalized_profile = self._normalize_profile_payload(profile)
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO queen_profiles(
                    queen_name, body_type, style, face, age_group, like_level, profile_confirmed, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(queen_name) DO UPDATE SET
                    body_type = excluded.body_type,
                    style = excluded.style,
                    face = excluded.face,
                    age_group = excluded.age_group,
                    like_level = excluded.like_level,
                    profile_confirmed = 1,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    normalized_name,
                    normalized_profile['body_type'],
                    normalized_profile['style'],
                    normalized_profile['face'],
                    normalized_profile['age_group'],
                    normalized_profile['like_level'],
                ),
            )
            conn.commit()
            return self._get_profile_from_connection(conn, normalized_name)

    def update_queen_video_metadata(self, record_id, content_type='', content_level=''):
        normalized_id = int(record_id or 0)
        if normalized_id <= 0:
            raise ValueError('\u7f3a\u5c11\u8bb0\u5f55\u7f16\u53f7')
        normalized_content_type = str(content_type or '').strip()
        normalized_content_level = str(content_level or '').strip()
        if normalized_content_type and normalized_content_type not in QUEEN_VIDEO_CONTENT_TYPES:
            raise ValueError('\u5185\u5bb9\u8bf7\u9009\u62e9\u6709\u6548\u9009\u9879')
        if normalized_content_level and normalized_content_level not in QUEEN_VIDEO_CONTENT_LEVELS:
            raise ValueError('\u7b49\u7ea7\u8bf7\u9009\u62e9\u6709\u6548\u9009\u9879')
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE queen_videos
                SET content_type = ?, content_level = ?
                WHERE id = ?
                ''',
                (normalized_content_type, normalized_content_level, normalized_id),
            )
            if int(cursor.rowcount or 0) <= 0:
                raise ValueError('\u8bb0\u5f55\u4e0d\u5b58\u5728')
            conn.commit()
            row = conn.execute(
                '''
                SELECT id, raw_title, queen_name, video_title, source_url, detail_url,
                       content_type, content_level, created_at
                FROM queen_videos
                WHERE id = ?
                ''',
                (normalized_id,),
            ).fetchone()
        return dict(row or {})

    def delete_queen_video(self, record_id):
        normalized_id = int(record_id or 0)
        if normalized_id <= 0:
            raise ValueError('\u7f3a\u5c11\u8bb0\u5f55\u7f16\u53f7')
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM queen_videos WHERE id = ?', (normalized_id,))
            deleted_count = int(cursor.rowcount or 0)
            conn.commit()
        return deleted_count

    def delete_queen(self, queen_name):
        normalized_name = str(queen_name or '').strip()
        if not normalized_name:
            raise ValueError('\u7f3a\u5c11\u5973\u738b\u540d\u79f0')
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM queen_profiles WHERE queen_name = ?', (normalized_name,))
            cursor.execute('DELETE FROM queen_videos WHERE queen_name = ?', (normalized_name,))
            deleted_count = int(cursor.rowcount or 0)
            conn.commit()
        return deleted_count

    def delete_keyword(self, keyword):
        normalized_keyword = str(keyword or '').strip()
        if not normalized_keyword:
            raise ValueError('\u7f3a\u5c11\u5173\u952e\u8bcd')
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM queen_keywords WHERE keyword = ?', (normalized_keyword,))
            row = cursor.fetchone()
            if row is None:
                return 0
            keyword_id = int(row['id'] or 0)
            cursor.execute('DELETE FROM queen_import_logs WHERE keyword_id = ?', (keyword_id,))
            cursor.execute('DELETE FROM queen_videos WHERE keyword_id = ?', (keyword_id,))
            cursor.execute('DELETE FROM queen_keywords WHERE id = ?', (keyword_id,))
            deleted_count = int(cursor.rowcount or 0)
            conn.commit()
        return deleted_count

    @staticmethod
    def _normalize_batch_size(batch_size):
        try:
            normalized = int(batch_size or 0)
        except (TypeError, ValueError):
            return 0
        return normalized if normalized > 0 else 0

    @staticmethod
    def _emit_refresh_progress(
        progress_callback,
        started_at,
        show_browser,
        keywords,
        query_results,
        scanned_count,
        imported_count,
        skipped_count,
        processed_count,
        completed=False,
    ):
        if not callable(progress_callback):
            return
        progress_callback({
            'started_at': started_at,
            'show_browser': bool(show_browser),
            'query_count': len(keywords),
            'total_count': len(keywords),
            'processed_count': int(processed_count or 0),
            'scanned_count': int(scanned_count or 0),
            'imported_count': int(imported_count or 0),
            'skipped_count': int(skipped_count or 0),
            'queries': list(query_results or []),
            'completed': bool(completed),
        })

    @staticmethod
    def _ensure_column(cursor, table_name, column_name, column_sql):
        columns = {
            str(row[1] or '')
            for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()
        }
        if column_name not in columns:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}')

    @staticmethod
    def _normalize_scraped_record(record):
        if isinstance(record, dict):
            raw_title = str(record.get('raw_title', record.get('title', '')) or '').strip()
            detail_url = str(record.get('detail_url', record.get('href', '')) or '').strip()
            return raw_title, detail_url
        return str(record or '').strip(), ''

    @staticmethod
    def parse_record_title(raw_title):
        normalized_title = str(raw_title or '').strip()
        if not normalized_title or QUEEN_RECORD_PREFIX not in normalized_title:
            return None
        if not normalized_title.startswith(QUEEN_RECORD_PREFIX):
            return None
        title_without_prefix = normalized_title[len(QUEEN_RECORD_PREFIX) :].strip()
        segments = [segment.strip() for segment in title_without_prefix.split('_') if str(segment or '').strip()]
        if len(segments) < 2:
            return None
        queen_name = segments[0]
        title_segments = segments[1:]
        if not title_segments:
            return None
        last_segment = str(title_segments[-1] or '').strip()
        stem, suffix = os.path.splitext(last_segment)
        if stem and suffix.lower() in MEDIA_SUFFIXES:
            title_segments[-1] = stem
        video_title = '_'.join(title_segments).strip()
        if not queen_name or not video_title:
            return None
        return {
            'raw_title': normalized_title,
            'queen_name': queen_name,
            'video_title': video_title,
        }

    @staticmethod
    def _get_or_create_keyword_id(cursor, keyword):
        cursor.execute('SELECT id FROM queen_keywords WHERE keyword = ?', (keyword,))
        row = cursor.fetchone()
        if row is not None:
            return int(row['id'] if isinstance(row, sqlite3.Row) else row[0])
        cursor.execute('INSERT INTO queen_keywords(keyword) VALUES (?)', (keyword,))
        return int(cursor.lastrowid or 0)

    @staticmethod
    def _dedupe_keep_order(values):
        seen = set()
        deduped = []
        for value in values:
            normalized = str(value or '').strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _current_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _append_crawl_log(self, payload):
        try:
            target = Path(self.crawl_log_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(dict(payload or {}), ensure_ascii=False) + '\n')
        except OSError:
            return

    @staticmethod
    def _empty_profile(queen_name):
        return {
            'queen_name': str(queen_name or '').strip(),
            'body_type': '',
            'style': '',
            'face': '',
            'age_group': '',
            'like_level': '',
            'profile_confirmed': False,
        }

    @classmethod
    def _normalize_profile_payload(cls, profile):
        payload = dict(profile or {})
        normalized = {}
        for field_key, (label, choices) in QUEEN_PROFILE_FIELDS.items():
            value = str(payload.get(field_key, '') or '').strip()
            if value not in choices:
                raise ValueError(f'{label}请选择有效选项')
            normalized[field_key] = value
        return normalized

    @classmethod
    def _get_profile_from_connection(cls, conn, queen_name):
        normalized_name = str(queen_name or '').strip()
        row = conn.execute(
            '''
            SELECT queen_name, body_type, style, face, age_group, like_level, profile_confirmed
            FROM queen_profiles
            WHERE queen_name = ?
            ''',
            (normalized_name,),
        ).fetchone()
        if row is None:
            return cls._empty_profile(normalized_name)
        profile = dict(row)
        profile['profile_confirmed'] = bool(profile.get('profile_confirmed', 0))
        return profile
