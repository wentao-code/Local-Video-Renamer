import os
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.app_logging import append_jsonl_log
from app.core.project_paths import QUEEN_LIBRARY_CRAWL_LOG_FILE, QUEEN_LIBRARY_DB_FILE
from app.queen_library.domain import (
    QUEEN_CRAWL_SOURCE_AUTO_GENERATED,
    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY,
    QUEEN_PROFILE_FIELD_OPTIONS,
    QUEEN_RECORD_PREFIX,
    QUEEN_VIDEO_CONTENT_LEVELS,
    QUEEN_VIDEO_CONTENT_TYPES,
    normalize_queen_crawl_source,
    normalize_queen_profile_value,
    normalize_queen_video_content_level,
    normalize_queen_video_content_type,
)
from app.queen_library.scraper import QueenSearchScraper, QueenSearchTransientError


MEDIA_SUFFIXES = {'.mp4', '.mkv', '.avi', '.wmv', '.mov'}
QUEEN_CRAWL_STATUS_OK = 'ok'
QUEEN_PROFILE_FIELDS = QUEEN_PROFILE_FIELD_OPTIONS

class QueenLibraryService:
    def __init__(self, db_path=None, scraper=None, crawl_log_path=None):
        self.db_path = Path(db_path) if db_path else QUEEN_LIBRARY_DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.scraper = scraper or QueenSearchScraper(headless=False)
        self.crawl_log_path = Path(crawl_log_path) if crawl_log_path else QUEEN_LIBRARY_CRAWL_LOG_FILE
        self._init_db()

    @contextmanager
    def _connect(self):
        try:
            timeout_seconds = get_operation_timeout_seconds('database_wait')
        except Exception:
            timeout_seconds = 60
        conn = sqlite3.connect(self.db_path, timeout=timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute(f'PRAGMA busy_timeout = {max(1, int(timeout_seconds * 1000))}')
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
                CREATE TABLE IF NOT EXISTS queen_name_aliases (
                    alias_name TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS queen_crawl_queue_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    source TEXT DEFAULT 'keyword_library',
                    scanned_count INTEGER DEFAULT 0,
                    imported_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            self._ensure_column(cursor, 'queen_crawl_queue_log', 'status', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'queen_crawl_queue_log', 'hand_mark', 'INTEGER DEFAULT 0')
            self._migrate_legacy_domain_values(conn)
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
        marked_rows = self._list_hand_marked_crawl_queue_rows()
        marked_keywords = {
            str(row.get('keyword', '') or '').strip()
            for row in marked_rows
            if str(row.get('keyword', '') or '').strip()
        }
        keywords = [
            keyword
            for keyword in self.build_refresh_keywords()
            if str(keyword or '').strip() and str(keyword or '').strip() not in marked_keywords
        ]
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

        configure_visibility = getattr(self.scraper, 'configure_browser_visibility', None)
        if callable(configure_visibility):
            configure_visibility(show_browser)
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
                source = (
                    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY
                    if keyword in manual_keywords
                    else QUEEN_CRAWL_SOURCE_AUTO_GENERATED
                )
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
                candidates.append(queen_name)
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

        configure_visibility = getattr(self.scraper, 'configure_browser_visibility', None)
        if callable(configure_visibility):
            configure_visibility(show_browser)
        session_factory = getattr(self.scraper, 'session', None)
        session_context = session_factory() if callable(session_factory) else nullcontext(None)
        with session_context as page:
            for keyword in keywords:
                try:
                    result = self._search_and_import_keyword(
                        keyword,
                        show_browser=show_browser,
                        page=page,
                        save_keyword=False,
                    )
                    transient_error = ''
                except QueenSearchTransientError as exc:
                    result = {
                        'keyword': keyword,
                        'source_url': '',
                        'scanned_count': 0,
                        'imported_count': 0,
                        'skipped_count': 1,
                    }
                    transient_error = str(exc)
                query_result = {
                    'keyword': keyword,
                    'source_url': result.get('source_url', ''),
                    'scanned_count': int(result.get('scanned_count', 0) or 0),
                    'imported_count': int(result.get('imported_count', 0) or 0),
                    'skipped_count': int(result.get('skipped_count', 0) or 0),
                }
                if transient_error:
                    query_result['error'] = transient_error
                query_results.append(query_result)
                scanned_count += query_result['scanned_count']
                imported_count += query_result['imported_count']
                skipped_count += query_result['skipped_count']
                processed_count += 1
                remaining_count = max(0, len(keywords) - processed_count)
                source = (
                    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY
                    if keyword in manual_keywords
                    else QUEEN_CRAWL_SOURCE_AUTO_GENERATED
                )
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
                parsed['queen_name'] = self._resolve_queen_alias_from_connection(conn, parsed['queen_name'])
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
                    COALESCE(profiles.like_level, '') AS like_level,
                    COALESCE(profiles.profile_confirmed, 0) AS profile_confirmed
                FROM queen_videos AS videos
                LEFT JOIN queen_profiles AS profiles ON profiles.queen_name = videos.queen_name
                GROUP BY videos.queen_name
                ORDER BY videos.queen_name COLLATE NOCASE ASC
                '''
            ).fetchall()
        return [dict(row) for row in rows]

    def get_library_stats(self):
        with self._connect() as conn:
            queen_count = int(
                conn.execute(
                    '''
                    SELECT COUNT(*)
                    FROM (
                        SELECT queen_name
                        FROM queen_videos
                        GROUP BY queen_name
                    )
                    '''
                ).fetchone()[0]
                or 0
            )
            video_count = int(conn.execute('SELECT COUNT(*) FROM queen_videos').fetchone()[0] or 0)
            like_rows = conn.execute(
                '''
                SELECT COALESCE(NULLIF(profiles.like_level, ''), '') AS level, COUNT(*) AS count
                FROM (
                    SELECT queen_name
                    FROM queen_videos
                    GROUP BY queen_name
                ) AS queens
                LEFT JOIN queen_profiles AS profiles ON profiles.queen_name = queens.queen_name
                GROUP BY COALESCE(NULLIF(profiles.like_level, ''), '')
                '''
            ).fetchall()
            video_level_rows = conn.execute(
                '''
                SELECT COALESCE(NULLIF(content_level, ''), '') AS level, COUNT(*) AS count
                FROM queen_videos
                GROUP BY COALESCE(NULLIF(content_level, ''), '')
                '''
            ).fetchall()
        return {
            'queen_count': queen_count,
            'video_count': video_count,
            'like_level_distribution': self._build_level_distribution(like_rows, ('A', 'B', 'C', 'D')),
            'video_level_distribution': self._build_level_distribution(video_level_rows, ('S', 'A', 'B', 'C')),
        }

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
            'videos': [self._normalize_queen_video_row(row) for row in rows],
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
            self._upsert_queen_alias(conn, normalized_name, normalized_new_name)
            self._retarget_queen_aliases(conn, normalized_name, normalized_new_name)
            cursor.execute('DELETE FROM queen_profiles WHERE queen_name = ?', (normalized_name,))
            conn.commit()
        return self.get_queen_detail(normalized_new_name)

    def update_queen_video_metadata(self, record_id, content_type='', content_level=''):
        normalized_id = int(record_id or 0)
        if normalized_id <= 0:
            raise ValueError('\u7f3a\u5c11\u8bb0\u5f55\u7f16\u53f7')
        normalized_content_type = normalize_queen_video_content_type(content_type)
        normalized_content_level = normalize_queen_video_content_level(content_level)
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

    @classmethod
    def _migrate_legacy_domain_values(cls, conn):
        cls._normalize_table_column(
            conn,
            'queen_crawl_queue_log',
            'source',
            normalize_queen_crawl_source,
        )
        for field_key in QUEEN_PROFILE_FIELDS:
            cls._normalize_table_column(
                conn,
                'queen_profiles',
                field_key,
                lambda value, key=field_key: normalize_queen_profile_value(key, value),
            )
        cls._normalize_table_column(
            conn,
            'queen_videos',
            'content_type',
            normalize_queen_video_content_type,
        )
        cls._normalize_table_column(
            conn,
            'queen_videos',
            'content_level',
            normalize_queen_video_content_level,
        )

    @staticmethod
    def _normalize_table_column(conn, table_name, column_name, normalizer):
        rows = conn.execute(
            f'SELECT rowid AS _rowid, {column_name} FROM {table_name} WHERE COALESCE({column_name}, "") <> ""'
        ).fetchall()
        updates = []
        for row in rows:
            row_id = int(row['_rowid'] if isinstance(row, sqlite3.Row) else row[0])
            current = row[column_name] if isinstance(row, sqlite3.Row) else row[1]
            normalized = normalizer(current)
            if normalized != str(current or '').strip():
                updates.append((normalized, row_id))
        if updates:
            conn.executemany(
                f'UPDATE {table_name} SET {column_name} = ? WHERE rowid = ?',
                updates,
            )

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
            conn.execute('DELETE FROM queen_crawl_queue_log WHERE COALESCE(hand_mark, 0) = 0')
            conn.commit()

    def _insert_crawl_queue_log(self, keyword, source, scanned_count, imported_count, skipped_count):
        normalized_source = normalize_queen_crawl_source(source)
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO queen_crawl_queue_log(keyword, source, scanned_count, imported_count, skipped_count, hand_mark)
                VALUES (?, ?, ?, ?, ?, 0)
                ''',
                (keyword, normalized_source, scanned_count, imported_count, skipped_count),
            )
            conn.commit()

    def _upsert_crawl_queue_log(self, keyword, source, scanned_count, imported_count, skipped_count):
        normalized_source = normalize_queen_crawl_source(source)
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
                (normalized_source, scanned_count, imported_count, skipped_count, keyword),
            )
            if int(cursor.rowcount or 0) <= 0:
                cursor.execute(
                    '''
                    INSERT INTO queen_crawl_queue_log(keyword, source, status, scanned_count, imported_count, skipped_count, hand_mark)
                    VALUES (?, ?, '', ?, ?, ?, 0)
                    ''',
                    (keyword, normalized_source, scanned_count, imported_count, skipped_count),
                )
            conn.commit()

    def _replace_crawl_queue_log(self, queue_rows):
        rows = [dict(row or {}) for row in queue_rows or []]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM queen_crawl_queue_log')
            cursor.executemany(
                '''
                INSERT INTO queen_crawl_queue_log(keyword, source, status, scanned_count, imported_count, skipped_count, hand_mark)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        str(row.get('keyword', '') or '').strip(),
                        normalize_queen_crawl_source(row.get('source', '')),
                        str(row.get('status', '') or '').strip(),
                        int(row.get('scanned_count', 0) or 0),
                        int(row.get('imported_count', 0) or 0),
                        int(row.get('skipped_count', 0) or 0),
                        1 if int(row.get('hand_mark', 0) or 0) else 0,
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

        marked_rows = self._list_hand_marked_crawl_queue_rows()
        marked_keywords = {
            str(row.get('keyword', '') or '').strip()
            for row in marked_rows
            if str(row.get('keyword', '') or '').strip()
        }
        keywords = [
            keyword
            for keyword in self.build_refresh_keywords()
            if str(keyword or '').strip() and str(keyword or '').strip() not in marked_keywords
        ]
        queue_rows = list(marked_rows)
        queue_rows.extend(
            {
                'keyword': keyword,
                'source': (
                    QUEEN_CRAWL_SOURCE_KEYWORD_LIBRARY
                    if keyword in manual_keywords
                    else QUEEN_CRAWL_SOURCE_AUTO_GENERATED
                ),
                'status': '',
                'scanned_count': 0,
                'imported_count': 0,
                'skipped_count': 0,
                'hand_mark': 0,
            }
            for keyword in keywords
        )
        self._replace_crawl_queue_log(queue_rows)
        return keywords

    def _list_pending_crawl_queue_rows(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT id, keyword, source, status, scanned_count, imported_count, skipped_count, created_at, hand_mark
                FROM queen_crawl_queue_log
                WHERE COALESCE(status, '') <> ? AND COALESCE(hand_mark, 0) = 0
                ORDER BY id ASC
                ''',
                (QUEEN_CRAWL_STATUS_OK,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_hand_marked_crawl_queue_rows(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT id, keyword, source, status, scanned_count, imported_count, skipped_count, created_at, hand_mark
                FROM queen_crawl_queue_log
                WHERE COALESCE(hand_mark, 0) = 1
                ORDER BY id ASC
                '''
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
    def _build_level_distribution(rows, ordered_levels):
        count_by_level = {}
        for row in rows or []:
            if isinstance(row, dict):
                level = row.get('level', '')
                count = row.get('count', 0)
            elif isinstance(row, sqlite3.Row):
                level = row['level']
                count = row['count']
            else:
                level = row[0]
                count = row[1]
            count_by_level[str(level or '').strip()] = int(count or 0)
        return [
            *[
                {'level': level, 'count': int(count_by_level.get(level, 0) or 0)}
                for level in ordered_levels
            ],
            {'level': '', 'count': int(count_by_level.get('', 0) or 0)},
        ]

    @staticmethod
    def _current_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _append_crawl_log(self, payload):
        append_jsonl_log(self.crawl_log_path, payload)

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
        for field_key, choices in QUEEN_PROFILE_FIELDS.items():
            value = normalize_queen_profile_value(field_key, payload.get(field_key, ''))
            if value not in choices:
                raise ValueError(f'{field_key} must be one of: {", ".join(choices)}')
            normalized[field_key] = value
        return normalized

    @classmethod
    def _normalize_optional_profile_payload(cls, profile):
        payload = dict(profile or {})
        normalized = {}
        for field_key, choices in QUEEN_PROFILE_FIELDS.items():
            value = normalize_queen_profile_value(field_key, payload.get(field_key, ''))
            if value and value not in choices:
                raise ValueError(f'{field_key} must be one of: {", ".join(choices)}')
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
            'content_type': normalize_queen_video_content_type(_pick('content_type')),
            'content_level': normalize_queen_video_content_level(_pick('content_level')),
        }

    @staticmethod
    def _normalize_queen_video_row(row):
        payload = dict(row or {})
        payload['content_type'] = normalize_queen_video_content_type(payload.get('content_type', ''))
        payload['content_level'] = normalize_queen_video_content_level(payload.get('content_level', ''))
        return payload

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

    @classmethod
    def _resolve_queen_alias_from_connection(cls, conn, queen_name):
        current_name = str(queen_name or '').strip()
        seen_names = set()
        while current_name and current_name not in seen_names:
            seen_names.add(current_name)
            row = conn.execute(
                '''
                SELECT canonical_name
                FROM queen_name_aliases
                WHERE alias_name = ?
                ''',
                (current_name,),
            ).fetchone()
            if row is None:
                break
            raw_canonical_name = row['canonical_name'] if isinstance(row, sqlite3.Row) else row[0]
            canonical_name = str(raw_canonical_name or '').strip()
            if not canonical_name:
                break
            current_name = canonical_name
        return current_name

    @staticmethod
    def _upsert_queen_alias(conn, alias_name, canonical_name):
        normalized_alias = str(alias_name or '').strip()
        normalized_canonical = str(canonical_name or '').strip()
        if not normalized_alias or not normalized_canonical or normalized_alias == normalized_canonical:
            return
        conn.execute(
            '''
            INSERT INTO queen_name_aliases(alias_name, canonical_name, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(alias_name) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (normalized_alias, normalized_canonical),
        )

    @staticmethod
    def _retarget_queen_aliases(conn, old_canonical_name, new_canonical_name):
        normalized_old = str(old_canonical_name or '').strip()
        normalized_new = str(new_canonical_name or '').strip()
        if not normalized_old or not normalized_new or normalized_old == normalized_new:
            return
        conn.execute(
            '''
            UPDATE queen_name_aliases
            SET canonical_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE canonical_name = ?
            ''',
            (normalized_new, normalized_old),
        )

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
        for field_key in QUEEN_PROFILE_FIELDS:
            profile[field_key] = normalize_queen_profile_value(field_key, profile.get(field_key, ''))
        profile['profile_confirmed'] = bool(profile.get('profile_confirmed', 0))
        return profile
