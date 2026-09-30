import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter

from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.project_paths import STANDARD_REFERENCE_DB_FILE


MAX_STANDARD_REFERENCE_PAGES = 99999
PRICE_SUFFIX_PATTERN = re.compile(
    r'\s*[-–—]?\s*\[\s*售价\s*\**\s*\d+(?:\.\d+)?\s*\**\s*彩币\s*\]\s*$',
    re.IGNORECASE,
)
BRACKET_PATTERN = re.compile(r'【([^ 】][^】]*)】')


def parse_forum_thread_title(raw_title):
    normalized_title = re.sub(r'\s+', ' ', str(raw_title or '')).strip()
    bracket_values = [value.strip() for value in BRACKET_PATTERN.findall(normalized_title)]
    if len(bracket_values) < 2 or not bracket_values[1]:
        return None
    video_title = PRICE_SUFFIX_PATTERN.sub('', normalized_title)
    video_title = BRACKET_PATTERN.sub('', video_title, count=2).strip(' -–—\t')
    if not video_title:
        return None
    return {
        'author_name': bracket_values[1],
        'video_title': video_title,
        'raw_title': normalized_title,
    }


class StandardReferenceLibraryService:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else STANDARD_REFERENCE_DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    @contextmanager
    def _connect(self):
        try:
            timeout = get_operation_timeout_seconds('database_wait')
        except Exception:
            timeout = 60
        connection = sqlite3.connect(self.db_path, timeout=timeout)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode = WAL')
        connection.execute(f'PRAGMA busy_timeout = {max(1, int(timeout * 1000))}')
        try:
            yield connection
        finally:
            connection.close()

    def _initialize_database(self):
        with self._connect() as connection:
            connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS standard_reference_authors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS standard_reference_videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author_id INTEGER NOT NULL,
                    video_title TEXT NOT NULL,
                    raw_title TEXT NOT NULL,
                    thread_url TEXT NOT NULL UNIQUE,
                    page_number INTEGER NOT NULL,
                    crawled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    first_crawled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_crawled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(author_id) REFERENCES standard_reference_authors(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_standard_reference_videos_author
                    ON standard_reference_videos(author_id, id DESC);
                CREATE TABLE IF NOT EXISTS standard_reference_thread_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_run_id TEXT NOT NULL DEFAULT '',
                    UNIQUE(video_id, page_number),
                    FOREIGN KEY(video_id) REFERENCES standard_reference_videos(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_standard_reference_thread_pages_video
                    ON standard_reference_thread_pages(video_id, page_number);
                '''
            )
            self._ensure_video_timestamp_columns(connection)
            connection.execute(
                '''
                INSERT OR IGNORE INTO standard_reference_thread_pages(
                    video_id, page_number, first_seen_at, last_seen_at
                )
                SELECT id, page_number,
                       COALESCE(NULLIF(crawled_at, ''), CURRENT_TIMESTAMP),
                       COALESCE(NULLIF(crawled_at, ''), CURRENT_TIMESTAMP)
                FROM standard_reference_videos
                '''
            )
            connection.commit()

    @staticmethod
    def _ensure_video_timestamp_columns(connection):
        columns = {
            str(row['name'])
            for row in connection.execute('PRAGMA table_info(standard_reference_videos)')
        }
        for column in ('first_crawled_at', 'last_crawled_at', 'updated_at'):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE standard_reference_videos ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        connection.execute(
            '''
            UPDATE standard_reference_videos
            SET first_crawled_at = COALESCE(NULLIF(first_crawled_at, ''), NULLIF(crawled_at, ''), CURRENT_TIMESTAMP),
                last_crawled_at = COALESCE(NULLIF(last_crawled_at, ''), NULLIF(crawled_at, ''), CURRENT_TIMESTAMP),
                updated_at = COALESCE(NULLIF(updated_at, ''), NULLIF(crawled_at, ''), CURRENT_TIMESTAMP)
            '''
        )

    @staticmethod
    def validate_page_count(page_count):
        try:
            normalized = int(page_count)
        except (TypeError, ValueError) as exc:
            raise ValueError('抓取页数必须是整数') from exc
        if normalized < 1 or normalized > MAX_STANDARD_REFERENCE_PAGES:
            raise ValueError(f'抓取页数必须在 1 到 {MAX_STANDARD_REFERENCE_PAGES} 之间')
        return normalized

    @classmethod
    def validate_page_range(cls, start_page, end_page):
        normalized_start = cls.validate_page_count(start_page)
        normalized_end = cls.validate_page_count(end_page)
        if normalized_end < normalized_start:
            raise ValueError('终止页不能小于起始页')
        return normalized_start, normalized_end

    def save_page_records(self, records, run_id=''):
        normalized_run_id = str(run_id or '').strip()
        normalized_records = []
        for raw_record in records or []:
            row = dict(raw_record or {})
            author_name = str(row.get('author_name') or '').strip()
            video_title = str(row.get('video_title') or '').strip()
            raw_title = str(row.get('raw_title') or '').strip()
            thread_url = str(row.get('thread_url') or '').strip()
            if not (author_name and video_title and raw_title and thread_url):
                continue
            page_number = self.validate_page_count(row.get('page_number', 1))
            normalized_records.append((author_name, video_title, raw_title, thread_url, page_number))

        inserted_count = 0
        with self._connect() as connection:
            cursor = connection.cursor()
            for author_name, video_title, raw_title, thread_url, page_number in normalized_records:
                cursor.execute(
                    'INSERT OR IGNORE INTO standard_reference_authors(author_name) VALUES (?)',
                    (author_name,),
                )
                author = cursor.execute(
                    'SELECT id FROM standard_reference_authors WHERE author_name = ? COLLATE NOCASE',
                    (author_name,),
                ).fetchone()
                video_exists = cursor.execute(
                    'SELECT 1 FROM standard_reference_videos WHERE thread_url = ?',
                    (thread_url,),
                ).fetchone() is not None
                cursor.execute(
                    '''
                    INSERT INTO standard_reference_videos(
                        author_id, video_title, raw_title, thread_url, page_number,
                        crawled_at, first_crawled_at, last_crawled_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(thread_url) DO UPDATE SET
                        author_id = excluded.author_id,
                        video_title = excluded.video_title,
                        raw_title = excluded.raw_title,
                        crawled_at = CURRENT_TIMESTAMP,
                        last_crawled_at = CURRENT_TIMESTAMP,
                        updated_at = CASE
                            WHEN standard_reference_videos.author_id <> excluded.author_id
                              OR standard_reference_videos.video_title <> excluded.video_title
                              OR standard_reference_videos.raw_title <> excluded.raw_title
                            THEN CURRENT_TIMESTAMP
                            ELSE standard_reference_videos.updated_at
                        END
                    ''',
                    (int(author['id']), video_title, raw_title, thread_url, page_number),
                )
                inserted_count += int(not video_exists)
                video = cursor.execute(
                    'SELECT id FROM standard_reference_videos WHERE thread_url = ?',
                    (thread_url,),
                ).fetchone()
                page_exists = cursor.execute(
                    '''
                    SELECT 1
                    FROM standard_reference_thread_pages
                    WHERE video_id = ? AND page_number = ?
                    ''',
                    (int(video['id']), page_number),
                ).fetchone() is not None
                cursor.execute(
                    '''
                    INSERT INTO standard_reference_thread_pages(
                        video_id, page_number, first_seen_at, last_seen_at, last_run_id
                    ) VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                    ON CONFLICT(video_id, page_number) DO UPDATE SET
                        last_seen_at = CURRENT_TIMESTAMP,
                        last_run_id = CASE
                            WHEN excluded.last_run_id <> '' THEN excluded.last_run_id
                            ELSE standard_reference_thread_pages.last_run_id
                        END
                    ''',
                    (int(video['id']), page_number, normalized_run_id),
                )
                if not page_exists:
                    cursor.execute(
                        'UPDATE standard_reference_videos SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                        (int(video['id']),),
                    )
            connection.commit()
        return inserted_count

    def list_authors(self):
        with self._connect() as connection:
            rows = connection.execute(
                '''
                SELECT authors.author_name, COUNT(videos.id) AS video_count
                FROM standard_reference_authors AS authors
                JOIN standard_reference_videos AS videos ON videos.author_id = authors.id
                GROUP BY authors.id
                ORDER BY authors.author_name COLLATE NOCASE, authors.id
                '''
            ).fetchall()
        return [dict(row) for row in rows]

    def get_author_detail(self, author_name):
        normalized_name = str(author_name or '').strip()
        if not normalized_name:
            raise ValueError('博主名称不能为空')
        with self._connect() as connection:
            author = connection.execute(
                'SELECT id, author_name FROM standard_reference_authors WHERE author_name = ? COLLATE NOCASE',
                (normalized_name,),
            ).fetchone()
            if author is None:
                raise FileNotFoundError(f'标准对照库中不存在博主：{normalized_name}')
            videos = connection.execute(
                '''
                SELECT video_title, raw_title, thread_url, page_number, crawled_at,
                       first_crawled_at, last_crawled_at, updated_at,
                       (SELECT GROUP_CONCAT(page_number, ',')
                        FROM (
                            SELECT page_number
                            FROM standard_reference_thread_pages
                            WHERE video_id = standard_reference_videos.id
                            ORDER BY page_number
                        )) AS page_list
                FROM standard_reference_videos
                WHERE author_id = ?
                ORDER BY id DESC
                ''',
                (int(author['id']),),
            ).fetchall()
        video_rows = []
        for row in videos:
            item = dict(row)
            item['page_numbers'] = [
                int(value)
                for value in str(item.pop('page_list') or item['page_number']).split(',')
                if value
            ]
            video_rows.append(item)
        return {'author_name': author['author_name'], 'videos': video_rows}

    def crawl_pages(
        self,
        scraper,
        start_page,
        end_page,
        progress_callback=None,
        should_stop=None,
        run_id='',
    ):
        normalized_start_page, normalized_end_page = self.validate_page_range(start_page, end_page)
        normalized_run_id = str(run_id or '').strip()
        total_pages = normalized_end_page - normalized_start_page + 1
        pages_completed = 0
        records_seen = 0
        inserted_count = 0
        stopped = False
        with scraper.session() as page:
            if callable(progress_callback):
                progress_callback({'event': 'session_started'})
            for page_number in range(normalized_start_page, normalized_end_page + 1):
                if callable(should_stop) and should_stop():
                    stopped = True
                    break
                page_started_at = perf_counter()
                if callable(progress_callback):
                    progress_callback({
                        'event': 'page_started',
                        'page_number': page_number,
                        'total_pages': total_pages,
                    })
                page_records_seen = 0
                try:
                    records = scraper.fetch_page(page, page_number, should_stop=should_stop)
                    page_records_seen = len(records)
                    records_seen += len(records)
                    records_added_before_page = inserted_count
                    inserted_count += self.save_page_records(records, run_id=normalized_run_id)
                except Exception as exc:
                    if callable(progress_callback):
                        progress_callback({
                            'event': 'page_failed',
                            'page_number': page_number,
                            'page_records_seen': page_records_seen,
                            'page_elapsed_seconds': round(perf_counter() - page_started_at, 3),
                            'error_type': type(exc).__name__,
                        })
                    raise
                pages_completed += 1
                if callable(progress_callback):
                    progress_callback({
                        'event': 'page_completed',
                        'page_number': page_number,
                        'page_records_seen': len(records),
                        'page_records_added': inserted_count - records_added_before_page,
                        'page_records_not_added': len(records) - (inserted_count - records_added_before_page),
                        'page_elapsed_seconds': round(perf_counter() - page_started_at, 3),
                        'pages_completed': pages_completed,
                        'total_pages': total_pages,
                        'records_seen': records_seen,
                        'records_added': inserted_count,
                    })
                if callable(should_stop) and should_stop():
                    stopped = True
                    break
        return {
            'pages_completed': pages_completed,
            'total_pages': total_pages,
            'records_seen': records_seen,
            'records_added': inserted_count,
            'stopped': stopped,
            'run_id': normalized_run_id,
            'authors': self.list_authors(),
        }
