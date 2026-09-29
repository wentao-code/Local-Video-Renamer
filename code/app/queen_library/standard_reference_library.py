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
                    FOREIGN KEY(author_id) REFERENCES standard_reference_authors(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_standard_reference_videos_author
                    ON standard_reference_videos(author_id, id DESC);
                '''
            )
            connection.commit()

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

    def save_page_records(self, records):
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
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO standard_reference_videos(
                        author_id, video_title, raw_title, thread_url, page_number
                    ) VALUES (?, ?, ?, ?, ?)
                    ''',
                    (int(author['id']), video_title, raw_title, thread_url, page_number),
                )
                inserted_count += int(cursor.rowcount or 0)
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
                SELECT video_title, raw_title, thread_url, page_number, crawled_at
                FROM standard_reference_videos
                WHERE author_id = ?
                ORDER BY id DESC
                ''',
                (int(author['id']),),
            ).fetchall()
        return {'author_name': author['author_name'], 'videos': [dict(row) for row in videos]}

    def crawl_pages(self, scraper, start_page, end_page, progress_callback=None, should_stop=None):
        normalized_start_page, normalized_end_page = self.validate_page_range(start_page, end_page)
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
                    inserted_count += self.save_page_records(records)
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
            'authors': self.list_authors(),
        }
