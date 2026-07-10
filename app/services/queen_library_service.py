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
QUEEN_CRAWL_STATUS_OK = 'ok'
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
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_crawl_queue_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    source TEXT DEFAULT '关键词库',
                    scanned_count INTEGER DEFAULT 0,
                    imported_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            self._ensure_column(cursor, 'queen_crawl_queue_log', 'status', "TEXT DEFAULT ''")
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

    def refresh_all(self, show_browser=True, batch_size=None, progress_callback=None, should_stop=None):
        return self._refresh_all_with_resume(
            show_browser=show_browser,
            batch_size=batch_size,
            progress_callback=progress_callback,
            should_stop=should_stop,
        )
        started_at = self._current_timestamp()
        keywords = self.build_refresh_keywords()
        manual_keywords = {
            str((row or {}).get('keyword', '') or '').strip()
            for row in self.list_keywords()
            if str((row or {}).get('keyword', '') or '').strip()
        }
        query_results = []
        scanned_count = 0
        imported_count = 0
        skipped_count = 0
        processed_count = 0
        normalized_batch_size = self._normalize_batch_size(batch_size)

        self._clear_crawl_queue_log()

        session_factory = getattr(self.scraper, 'session', None)
        session_context = session_factory() if callable(session_factory) else nullcontext(None)
        # Keep one browser page alive for the whole refresh batch so each
        # keyword search only navigates to a new URL instead of reopening Chrome.
        with session_context as page:
            for keyword in keywords:
                result = self._search_and_import_keyword(keyword, show_browser=show_browser, page=page, save_keyword=False)
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
                source = '关键词库' if keyword in manual_keywords else '自动生成'
                self._insert_crawl_queue_log(
                    keyword,
                    source,
                    query_result['scanned_count'],
                    query_result['imported_count'],
                    query_result['skipped_count'],
                )
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
        if callable(progress_callback) and not stopped:
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

    def _refresh_all_with_resume(self, show_browser=True, batch_size=None, progress_callback=None, should_stop=None):
        started_at = self._current_timestamp()
        manual_keywords = {
            str((row or {}).get('keyword', '') or '').strip()
            for row in self.list_keywords()
            if str((row or {}).get('keyword', '') or '').strip()
        }
        keywords = self._prepare_refresh_queue(manual_keywords)
        query_results = []
        scanned_count = 0
        imported_count = 0
        skipped_count = 0
        processed_count = 0
        remaining_count = len(keywords)
        stopped = False
        normalized_batch_size = self._normalize_batch_size(batch_size)
        completed_batch_keywords = []

        session_factory = getattr(self.scraper, 'session', None)
        session_context = session_factory() if callable(session_factory) else nullcontext(None)
        with session_context as page:
            for keyword in keywords:
                result = self._search_and_import_keyword(
                    keyword,
                    show_browser=show_browser,
                    page=page,
                    save_keyword=False,
                )
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
                remaining_count = max(0, len(keywords) - processed_count)
                source = '鍏抽敭璇嶅簱' if keyword in manual_keywords else '鑷姩鐢熸垚'
                self._upsert_crawl_queue_log(
                    keyword,
                    source,
                    query_result['scanned_count'],
                    query_result['imported_count'],
                    query_result['skipped_count'],
                )
                completed_batch_keywords.append(keyword)

                reached_batch_boundary = bool(normalized_batch_size and processed_count % normalized_batch_size == 0)
                reached_final_keyword = processed_count == len(keywords)
                if reached_batch_boundary or reached_final_keyword:
                    self._mark_crawl_queue_keywords_status(completed_batch_keywords, QUEEN_CRAWL_STATUS_OK)
                    completed_batch_keywords = []
                    self._emit_refresh_progress_with_remaining(
                        progress_callback,
                        started_at,
                        show_browser,
                        keywords,
                        query_results,
                        scanned_count,
                        imported_count,
                        skipped_count,
                        processed_count,
                        remaining_count,
                        completed=bool(reached_final_keyword),
                        stopped=False,
                    )
                    if callable(should_stop) and should_stop() and not reached_final_keyword:
                        stopped = True
                        break

        if completed_batch_keywords:
            self._mark_crawl_queue_keywords_status(completed_batch_keywords, QUEEN_CRAWL_STATUS_OK)
        if not stopped and remaining_count == 0:
            self._clear_crawl_queue_log()

        payload = {
            'started_at': started_at,
            'completed_at': self._current_timestamp(),
            'show_browser': bool(show_browser),
            'query_count': len(keywords),
            'processed_count': processed_count,
            'remaining_count': remaining_count,
            'scanned_count': scanned_count,
            'imported_count': imported_count,
            'skipped_count': skipped_count,
            'stopped': stopped,
            'queries': query_results,
            'log_path': str(self.crawl_log_path),
            'keywords': self.list_keywords(),
            'queens': self.list_queens(),
        }
        self._append_crawl_log(payload)
        return payload

    def _search_and_import_keyword(self, keyword, show_browser=True, page=None, save_keyword=True):
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
            keyword_id = self._resolve_keyword_id(cursor, normalized_keyword, save_keyword=save_keyword)
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
            if keyword_id != 0:
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

    def rename_queen(self, queen_name, new_queen_name, profile=None):
        normalized_name = str(queen_name or '').strip()
        normalized_new_name = str(new_queen_name or '').strip()
        if not normalized_name:
            raise ValueError('\u7f3a\u5c11\u5973\u738b\u540d\u79f0')
        if not normalized_new_name:
            raise ValueError('\u7f3a\u5c11\u65b0\u7684\u5973\u738b\u540d\u79f0')

        with self._connect() as conn:
            source_videos = self._load_queen_videos_from_connection(conn, normalized_name)
            if not source_videos:
                raise ValueError('\u5973\u738b\u4e0d\u5b58\u5728')

            edited_profile = self._normalize_optional_profile_payload(profile)
            source_profile = self._get_profile_from_connection(conn, normalized_name)
            if normalized_name == normalized_new_name:
                merged_profile = self._merge_queen_profiles(
                    normalized_new_name,
                    edited_profile,
                    source_profile,
                )
                self._upsert_queen_profile(conn, normalized_new_name, merged_profile)
                conn.commit()
                return self.get_queen_detail(normalized_new_name)

            target_videos = self._load_queen_videos_from_connection(conn, normalized_new_name)
            target_profile = self._get_profile_from_connection(conn, normalized_new_name)
            merged_profile = self._merge_queen_profiles(
                normalized_new_name,
                edited_profile,
                source_profile,
                target_profile,
            )
            cursor = conn.cursor()
            source_videos_by_title = {
                str((row or {}).get('video_title', '') or '').strip(): dict(row or {})
                for row in source_videos
                if str((row or {}).get('video_title', '') or '').strip()
            }
            target_videos_by_title = {
                str((row or {}).get('video_title', '') or '').strip(): dict(row or {})
                for row in target_videos
                if str((row or {}).get('video_title', '') or '').strip()
            }

            for video_title in sorted(set(source_videos_by_title) | set(target_videos_by_title)):
                source_row = source_videos_by_title.get(video_title)
                target_row = target_videos_by_title.get(video_title)
                if source_row is None:
                    continue
                rows = [source_row]
                if target_row is not None:
                    rows.append(target_row)
                keeper = self._select_preferred_queen_video_row(rows)
                merged_video = self._build_merged_queen_video_row(rows, normalized_new_name, video_title)
                keeper_id = int(keeper.get('id', 0) or 0)

                for row in rows:
                    row_id = int((row or {}).get('id', 0) or 0)
                    if row_id > 0 and row_id != keeper_id:
                        cursor.execute('DELETE FROM queen_videos WHERE id = ?', (row_id,))

                cursor.execute(
                    '''
                    UPDATE queen_videos
                    SET queen_name = ?, raw_title = ?, video_title = ?, source_url = ?, detail_url = ?,
                        content_type = ?, content_level = ?
                    WHERE id = ?
                    ''',
                    (
                        merged_video['queen_name'],
                        merged_video['raw_title'],
                        merged_video['video_title'],
                        merged_video['source_url'],
                        merged_video['detail_url'],
                        merged_video['content_type'],
                        merged_video['content_level'],
                        keeper_id,
                    ),
                )

            self._upsert_queen_profile(conn, normalized_new_name, merged_profile)
            cursor.execute('DELETE FROM queen_profiles WHERE queen_name = ?', (normalized_name,))
            conn.commit()
        return self.get_queen_detail(normalized_new_name)

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
    def _emit_refresh_progress_with_remaining(
        progress_callback,
        started_at,
        show_browser,
        keywords,
        query_results,
        scanned_count,
        imported_count,
        skipped_count,
        processed_count,
        remaining_count,
        completed=False,
        stopped=False,
    ):
        if not callable(progress_callback):
            return
        progress_callback({
            'started_at': started_at,
            'show_browser': bool(show_browser),
            'query_count': len(keywords),
            'total_count': len(keywords),
            'processed_count': int(processed_count or 0),
            'remaining_count': int(remaining_count or 0),
            'scanned_count': int(scanned_count or 0),
            'imported_count': int(imported_count or 0),
            'skipped_count': int(skipped_count or 0),
            'queries': list(query_results or []),
            'completed': bool(completed),
            'stopped': bool(stopped),
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

    @classmethod
    def _resolve_keyword_id(cls, cursor, keyword, save_keyword=True):
        if save_keyword:
            return cls._get_or_create_keyword_id(cursor, keyword)
        cursor.execute('SELECT id FROM queen_keywords WHERE keyword = ?', (keyword,))
        row = cursor.fetchone()
        if row is not None:
            return int(row['id'] if isinstance(row, sqlite3.Row) else row[0])
        return 0

    def _clear_crawl_queue_log(self):
        with self._connect() as conn:
            conn.execute('DELETE FROM queen_crawl_queue_log')
            conn.commit()

    def _insert_crawl_queue_log(self, keyword, source, scanned_count, imported_count, skipped_count):
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO queen_crawl_queue_log(keyword, source, scanned_count, imported_count, skipped_count)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (keyword, source, scanned_count, imported_count, skipped_count),
            )
            conn.commit()

    def _upsert_crawl_queue_log(self, keyword, source, scanned_count, imported_count, skipped_count):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE queen_crawl_queue_log
                SET source = ?,
                    scanned_count = ?,
                    imported_count = ?,
                    skipped_count = ?
                WHERE keyword = ?
                ''',
                (source, scanned_count, imported_count, skipped_count, keyword),
            )
            if int(cursor.rowcount or 0) <= 0:
                cursor.execute(
                    '''
                    INSERT INTO queen_crawl_queue_log(keyword, source, status, scanned_count, imported_count, skipped_count)
                    VALUES (?, ?, '', ?, ?, ?)
                    ''',
                    (keyword, source, scanned_count, imported_count, skipped_count),
                )
            conn.commit()

    def _replace_crawl_queue_log(self, queue_rows):
        rows = [dict(row or {}) for row in queue_rows or []]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM queen_crawl_queue_log')
            cursor.executemany(
                '''
                INSERT INTO queen_crawl_queue_log(keyword, source, status, scanned_count, imported_count, skipped_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        str(row.get('keyword', '') or '').strip(),
                        str(row.get('source', '') or '').strip() or '鍏抽敭璇嶅簱',
                        str(row.get('status', '') or '').strip(),
                        int(row.get('scanned_count', 0) or 0),
                        int(row.get('imported_count', 0) or 0),
                        int(row.get('skipped_count', 0) or 0),
                    )
                    for row in rows
                    if str(row.get('keyword', '') or '').strip()
                ],
            )
            conn.commit()

    def _prepare_refresh_queue(self, manual_keywords):
        pending_rows = self._list_pending_crawl_queue_rows()
        if pending_rows:
            return [
                str(row.get('keyword', '') or '').strip()
                for row in pending_rows
                if str(row.get('keyword', '') or '').strip()
            ]

        keywords = self.build_refresh_keywords()
        self._replace_crawl_queue_log([
            {
                'keyword': keyword,
                'source': '鍏抽敭璇嶅簱' if keyword in manual_keywords else '鑷姩鐢熸垚',
                'status': '',
                'scanned_count': 0,
                'imported_count': 0,
                'skipped_count': 0,
            }
            for keyword in keywords
        ])
        return keywords

    def _list_pending_crawl_queue_rows(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT id, keyword, source, status, scanned_count, imported_count, skipped_count, created_at
                FROM queen_crawl_queue_log
                WHERE COALESCE(status, '') <> ?
                ORDER BY id ASC
                ''',
                (QUEEN_CRAWL_STATUS_OK,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _mark_crawl_queue_keywords_status(self, keywords, status):
        normalized_keywords = [
            str(keyword or '').strip()
            for keyword in keywords or []
            if str(keyword or '').strip()
        ]
        if not normalized_keywords:
            return
        placeholders = ','.join('?' for _ in normalized_keywords)
        with self._connect() as conn:
            conn.execute(
                f'''
                UPDATE queen_crawl_queue_log
                SET status = ?
                WHERE keyword IN ({placeholders})
                ''',
                [str(status or '').strip(), *normalized_keywords],
            )
            conn.commit()

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
    def _normalize_optional_profile_payload(cls, profile):
        payload = dict(profile or {})
        normalized = {}
        for field_key, (label, choices) in QUEEN_PROFILE_FIELDS.items():
            value = str(payload.get(field_key, '') or '').strip()
            if value and value not in choices:
                raise ValueError(f'{label}璇烽€夋嫨鏈夋晥閫夐」')
            normalized[field_key] = value
        return normalized

    @classmethod
    def _is_profile_complete(cls, profile):
        payload = dict(profile or {})
        return all(str(payload.get(field_key, '') or '').strip() for field_key in QUEEN_PROFILE_FIELDS)

    @classmethod
    def _merge_queen_profiles(cls, queen_name, *profiles):
        merged = cls._empty_profile(queen_name)
        confirmed = False
        for profile in reversed(tuple(profiles)):
            current = dict(profile or {})
            confirmed = confirmed or bool(current.get('profile_confirmed'))
            for field_key in QUEEN_PROFILE_FIELDS:
                value = str(current.get(field_key, '') or '').strip()
                if value:
                    merged[field_key] = value
        merged['queen_name'] = str(queen_name or '').strip()
        merged['profile_confirmed'] = bool(confirmed or cls._is_profile_complete(merged))
        return merged

    @staticmethod
    def _queen_video_row_score(row):
        current = dict(row or {})
        return (
            1 if str(current.get('detail_url', '') or '').strip() else 0,
            1 if str(current.get('content_type', '') or '').strip() else 0,
            1 if str(current.get('content_level', '') or '').strip() else 0,
            len(str(current.get('source_url', '') or '').strip()),
            len(str(current.get('raw_title', '') or '').strip()),
            int(current.get('id', 0) or 0),
        )

    @classmethod
    def _select_preferred_queen_video_row(cls, rows):
        normalized_rows = [dict(row or {}) for row in rows if row]
        if not normalized_rows:
            return {}
        return max(normalized_rows, key=cls._queen_video_row_score)

    @classmethod
    def _build_merged_queen_video_row(cls, rows, queen_name, video_title):
        ordered_rows = sorted(
            [dict(row or {}) for row in rows if row],
            key=cls._queen_video_row_score,
            reverse=True,
        )

        def _pick(field_name):
            for row in ordered_rows:
                value = str(row.get(field_name, '') or '').strip()
                if value:
                    return value
            return ''

        return {
            'queen_name': str(queen_name or '').strip(),
            'video_title': str(video_title or '').strip(),
            'raw_title': _pick('raw_title'),
            'source_url': _pick('source_url'),
            'detail_url': _pick('detail_url'),
            'content_type': _pick('content_type'),
            'content_level': _pick('content_level'),
        }

    @staticmethod
    def _load_queen_videos_from_connection(conn, queen_name):
        normalized_name = str(queen_name or '').strip()
        rows = conn.execute(
            '''
            SELECT id, keyword_id, raw_title, queen_name, video_title, source_url, detail_url,
                   content_type, content_level, created_at
            FROM queen_videos
            WHERE queen_name = ?
            ORDER BY created_at DESC, id DESC
            ''',
            (normalized_name,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _upsert_queen_profile(conn, queen_name, profile):
        current = dict(profile or {})
        conn.execute(
            '''
            INSERT INTO queen_profiles(
                queen_name, body_type, style, face, age_group, like_level, profile_confirmed, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(queen_name) DO UPDATE SET
                body_type = excluded.body_type,
                style = excluded.style,
                face = excluded.face,
                age_group = excluded.age_group,
                like_level = excluded.like_level,
                profile_confirmed = excluded.profile_confirmed,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (
                str(queen_name or '').strip(),
                str(current.get('body_type', '') or '').strip(),
                str(current.get('style', '') or '').strip(),
                str(current.get('face', '') or '').strip(),
                str(current.get('age_group', '') or '').strip(),
                str(current.get('like_level', '') or '').strip(),
                1 if bool(current.get('profile_confirmed')) else 0,
            ),
        )

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
