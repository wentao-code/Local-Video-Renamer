import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
)
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BAOMU_ACTOR_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    SUPPLEMENT_TASK_SOURCE,
    build_library_enrichment_status_text,
    build_video_enrichment_status_text,
    is_effective_video_pending_status,
    normalize_source_enrichment_status,
    normalize_video_enrichment_source,
)
from app.core.video_code import standardize_video_code
from app.core.javtxt_video_state import (
    JAVTXT_AUTHOR_MIN_RELEASE_DATE,
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.javtxt_entry_state import (
    JAVTXT_SEARCH_STATE_FAILED,
    JAVTXT_SEARCH_STATE_NO_RESULT,
    classify_search_state,
    is_manual_category_candidate,
    is_resolved_search_state,
    is_retryable_search_state,
    normalize_actor_raw_text,
)
from app.core.supplement_task_state import build_supplement_candidate
from app.core.actor_profile_display import (
    normalize_actor_age_for_display,
    normalize_actor_birthday_for_display,
    normalize_actor_birthday_for_storage,
)
from app.core.second_source_actor_text import is_unpublished_actor_text, normalize_second_source_actor_text
from app.core.project_paths import DATABASE_FILE
from app.core.video_filter_rules import FILTER_FIELD_CO_STAR_CODE, get_filter_keywords, matches_filter_keywords
from app.core.video_filter_settings import load_video_filter_settings
from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_ENTITY_ACTOR,
    normalize_ladder_medal_text,
    split_ladder_medals,
)
from app.core.runtime_config import get_avfan_base_url
from app.data.repositories import (
    ActorRepositoryMixin,
    CodePrefixRepositoryMixin,
    LadderRepositoryMixin,
    MigrationMixin,
    PathRepositoryMixin,
)
from app.services.detail.update_frequency_service import calculate_update_frequency
from app.services.detail.update_status_service import resolve_update_status
from app.services.identity import IGNORED_ACTOR_NAMES, is_ignored_actor_name, split_actor_names
from app.services.library import extract_code_prefix


JAVTXT_INELIGIBLE_ERROR = 'JAVTXT 页面不满足补全条件'
from app.services.video import (
    MANUAL_CATEGORY_TIER_FIRST,
    MANUAL_CATEGORY_TIER_SECOND,
    MANUAL_CATEGORY_TIER_THIRD,
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_OPTIONS,
    VIDEO_CATEGORY_SINGLE,
    classify_manual_category_tier,
    count_video_actors,
    detect_video_category,
    normalize_video_category,
)


def join_values(value):
    if isinstance(value, (list, tuple)):
        return ' '.join(str(item) for item in value if str(item).strip())
    return str(value or '')


def sanitize_actor_text(value):
    return normalize_second_source_actor_text(value)


STARTUP_MAINTENANCE_META_KEY = 'startup_maintenance_version'
STARTUP_MAINTENANCE_VERSION = '2026-06-30-1'
MASTERPIECE_SOURCE_PRIORITY = ('video_library', 'code_prefix_library', 'actor_library')
MASTERPIECE_DATE_RE = re.compile(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})')


class VideoDatabase(
    MigrationMixin,
    PathRepositoryMixin,
    ActorRepositoryMixin,
    CodePrefixRepositoryMixin,
    LadderRepositoryMixin,
):
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DATABASE_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._startup_maintenance_completed = False
        self._startup_maintenance_lock = Lock()
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA busy_timeout = 60000')
        conn.execute('PRAGMA synchronous = NORMAL')
        conn.create_function('effective_actor_birthday_sql', 3, self._sql_effective_actor_birthday)
        conn.create_function('sortable_actor_birthday_sql', 3, self._sql_sortable_actor_birthday)
        conn.create_function('effective_actor_age_sql', 5, self._sql_effective_actor_age)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """初始化表结构（以 code 为主键实现绝对去重）"""
        with self._connect() as conn:
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
            self._ensure_column(cursor, 'processed_videos', 'avfan_actors', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_tags', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_title', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_actors', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_actors_raw', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_description', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'video_category', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'maker', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'publisher', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enriched_at', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'avfan_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'supplement_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'processed_videos', 'supplement_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'supplement_enriched_at', 'TEXT')
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = '未补全'
                WHERE enrichment_status IS NULL OR enrichment_status = ''
            ''')
            cursor.execute('''
                UPDATE processed_videos
                SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?))
            ''', (UNENRICHED_STATUS,))
            cursor.execute('''
                UPDATE processed_videos
                SET javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?)
            ''', (UNENRICHED_STATUS,))
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actors (
                    name TEXT PRIMARY KEY,
                    birthday TEXT,
                    age TEXT,
                    matched INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS masterpiece_entries (
                    code TEXT PRIMARY KEY,
                    display_title TEXT DEFAULT '',
                    display_author TEXT DEFAULT '',
                    primary_source TEXT DEFAULT '',
                    primary_detail_url TEXT DEFAULT '',
                    medal TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self._ensure_column(cursor, 'masterpiece_entries', 'display_title', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'masterpiece_entries', 'display_author', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'masterpiece_entries', 'primary_source', "TEXT DEFAULT ''")
            self._ensure_column(cursor, 'masterpiece_entries', 'primary_detail_url', "TEXT DEFAULT ''")
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS masterpiece_references (
                    masterpiece_code TEXT NOT NULL,
                    reference_source TEXT NOT NULL,
                    reference_key TEXT NOT NULL,
                    matched_code TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    release_date TEXT DEFAULT '',
                    avfan_movie_id TEXT DEFAULT '',
                    avfan_url TEXT DEFAULT '',
                    javtxt_movie_id TEXT DEFAULT '',
                    javtxt_url TEXT DEFAULT '',
                    detail_url TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (masterpiece_code, reference_source, reference_key, matched_code)
                )
                '''
            )
            self._ensure_index(
                cursor,
                'idx_masterpiece_references_code_source',
                'masterpiece_references',
                'masterpiece_code, reference_source',
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS masterpiece_actor_details (
                    masterpiece_code TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_order INTEGER DEFAULT 0,
                    source_video_code TEXT DEFAULT '',
                    release_date TEXT DEFAULT '',
                    birthday TEXT DEFAULT '',
                    current_age TEXT DEFAULT '',
                    appearance_age TEXT DEFAULT '',
                    height TEXT DEFAULT '',
                    bust TEXT DEFAULT '',
                    waist TEXT DEFAULT '',
                    hip TEXT DEFAULT '',
                    cup TEXT DEFAULT '',
                    measurements_raw TEXT DEFAULT '',
                    actor_exists_in_library INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (masterpiece_code, actor_name)
                )
                '''
            )
            self._ensure_index(
                cursor,
                'idx_masterpiece_actor_details_code_order',
                'masterpiece_actor_details',
                'masterpiece_code, actor_order, actor_name',
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS masterpiece_actor_basic_infos (
                    masterpiece_code TEXT NOT NULL,
                    actor_name TEXT NOT NULL,
                    actor_id TEXT DEFAULT '',
                    binghuo_person_id TEXT DEFAULT '',
                    ladder_tier TEXT DEFAULT '',
                    update_status TEXT DEFAULT '',
                    local_video_count INTEGER DEFAULT 0,
                    web_total_videos INTEGER DEFAULT 0,
                    appearance_code_count INTEGER DEFAULT 0,
                    code_prefix_library_count INTEGER DEFAULT 0,
                    web_update_frequency_text TEXT DEFAULT '',
                    web_enrichment_status TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (masterpiece_code, actor_name)
                )
                '''
            )
            for column_name, column_type in (
                ('actor_id', "TEXT DEFAULT ''"),
                ('binghuo_person_id', "TEXT DEFAULT ''"),
                ('ladder_tier', "TEXT DEFAULT ''"),
                ('update_status', "TEXT DEFAULT ''"),
                ('local_video_count', 'INTEGER DEFAULT 0'),
                ('web_total_videos', 'INTEGER DEFAULT 0'),
                ('appearance_code_count', 'INTEGER DEFAULT 0'),
                ('code_prefix_library_count', 'INTEGER DEFAULT 0'),
                ('web_update_frequency_text', "TEXT DEFAULT ''"),
                ('web_enrichment_status', "TEXT DEFAULT ''"),
            ):
                self._ensure_column(cursor, 'masterpiece_actor_basic_infos', column_name, column_type)
            self._ensure_index(
                cursor,
                'idx_masterpiece_actor_basic_infos_code_actor',
                'masterpiece_actor_basic_infos',
                'masterpiece_code, actor_name',
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS masterpiece_actors (
                    actor_name TEXT PRIMARY KEY,
                    status INTEGER DEFAULT 0,
                    handle_mark INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            self._ensure_column(cursor, 'masterpiece_actors', 'status', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'masterpiece_actors', 'handle_mark', 'INTEGER DEFAULT 0')
            self._ensure_index(
                cursor,
                'idx_masterpiece_actors_status_handle',
                'masterpiece_actors',
                'status, handle_mark, actor_name',
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS global_medals (
                    name TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
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
                CREATE TABLE IF NOT EXISTS usb_video_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    video_code TEXT NOT NULL,
                    file_path TEXT DEFAULT '',
                    file_name TEXT DEFAULT '',
                    size_on_disk TEXT DEFAULT '',
                    size_bytes INTEGER DEFAULT 0,
                    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(folder_path, video_code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usb_video_scan_states (
                    folder_path TEXT PRIMARY KEY,
                    last_total_bytes INTEGER DEFAULT 0,
                    last_used_bytes INTEGER DEFAULT 0,
                    last_free_bytes INTEGER DEFAULT 0,
                    last_scan_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS usb_video_change_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    video_code TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    previous_file_path TEXT DEFAULT '',
                    current_file_path TEXT DEFAULT '',
                    previous_size_on_disk TEXT DEFAULT '',
                    current_size_on_disk TEXT DEFAULT '',
                    previous_free_bytes INTEGER DEFAULT 0,
                    current_free_bytes INTEGER DEFAULT 0,
                    capacity_delta_bytes INTEGER DEFAULT 0,
                    capacity_delta_mb REAL DEFAULT 0,
                    current_capacity_mb REAL DEFAULT 0,
                    message TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                    javtxt_tags TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (prefix, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_enrichments (
                    actor_name TEXT PRIMARY KEY,
                    actor_id TEXT DEFAULT '',
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
                    javtxt_tags TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (actor_name, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hidden_code_prefixes (
                    prefix TEXT PRIMARY KEY
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hidden_actors (
                    name TEXT PRIMARY KEY
                )
            ''')
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS manual_category_staging (
                    code TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS ladder_entries (
                    board_key TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT '',
                    medal TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (board_key, entity_type, entity_name)
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS app_runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
                '''
            )
            self._ensure_column(cursor, 'path_library', 'last_total_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_used_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_free_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_usage_percent', 'REAL DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_volume_type', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'path_library', 'last_checked_at', 'TEXT')
            self._ensure_column(cursor, 'usb_video_inventory', 'size_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'usb_video_change_logs', 'current_capacity_mb', 'REAL DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'page_number', 'INTEGER DEFAULT 1')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'author_raw', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'video_category', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'supplement_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_movies', 'supplement_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'supplement_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'actor_id', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_person_id', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_birthday', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_age', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_height', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_bust', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_cup', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_measurements_raw', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_waist', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'binghuo_hip', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_birthday', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_height', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_bust', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_cup', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_measurements_raw', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_waist', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'baomu_hip', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'page_number', 'INTEGER DEFAULT 1')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'author_raw', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'video_category', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'supplement_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_movies', 'supplement_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'supplement_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'ladder_entries', 'tier', 'TEXT NOT NULL DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'medal', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'ladder_entries', 'updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'global_medals', 'description', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'global_medals', 'created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'global_medals', 'updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_index(cursor, 'idx_processed_videos_manual_category', 'processed_videos', 'javtxt_enrichment_status, video_category, code')
            self._ensure_index(cursor, 'idx_processed_videos_release_date', 'processed_videos', 'release_date, code')
            self._ensure_index(
                cursor,
                'idx_processed_videos_supplement_status',
                'processed_videos',
                'supplement_enrichment_status, javtxt_enrichment_status, code',
            )
            self._ensure_index(
                cursor,
                'idx_processed_videos_avfan_release',
                'processed_videos',
                'avfan_enrichment_status, release_date, code',
            )
            self._ensure_index(
                cursor,
                'idx_processed_videos_javtxt_release',
                'processed_videos',
                'javtxt_enrichment_status, release_date, code',
            )
            self._ensure_index(cursor, 'idx_usb_video_inventory_folder', 'usb_video_inventory', 'folder_path, video_code')
            self._ensure_index(cursor, 'idx_usb_video_change_logs_folder', 'usb_video_change_logs', 'folder_path, created_at')
            self._ensure_index(cursor, 'idx_code_prefix_movies_code', 'code_prefix_movies', 'code')
            self._ensure_index(cursor, 'idx_code_prefix_movies_category_code', 'code_prefix_movies', 'video_category, code')
            self._ensure_index(cursor, 'idx_code_prefix_movies_prefix_release', 'code_prefix_movies', 'prefix, release_date, code')
            self._ensure_index(
                cursor,
                'idx_code_prefix_movies_supplement_status',
                'code_prefix_movies',
                'supplement_enrichment_status, javtxt_enrichment_status, prefix, code',
            )
            self._ensure_index(cursor, 'idx_actor_movies_code', 'actor_movies', 'code')
            self._ensure_index(cursor, 'idx_actor_movies_category_code', 'actor_movies', 'video_category, code')
            self._ensure_index(cursor, 'idx_actor_movies_actor_release', 'actor_movies', 'actor_name, release_date, code')
            self._ensure_index(
                cursor,
                'idx_actor_movies_supplement_status',
                'actor_movies',
                'supplement_enrichment_status, javtxt_enrichment_status, actor_name, code',
            )
            self._ensure_index(
                cursor,
                'idx_actor_enrichments_status',
                'actor_enrichments',
                'avfan_enrichment_status, javtxt_enrichment_status, binghuo_enrichment_status, baomu_enrichment_status, actor_name',
            )
            self._ensure_index(
                cursor,
                'idx_code_prefix_enrichments_status',
                'code_prefix_enrichments',
                'avfan_enrichment_status, javtxt_enrichment_status, prefix',
            )
            self._ensure_index(cursor, 'idx_ladder_entries_board', 'ladder_entries', 'board_key, entity_type, tier, entity_name')
            conn.commit()

    def ensure_startup_maintenance(self):
        if self._startup_maintenance_completed:
            return
        with self._startup_maintenance_lock:
            if self._startup_maintenance_completed:
                return
            with self._connect() as conn:
                cursor = conn.cursor()
                if self._is_startup_maintenance_current(cursor):
                    self._startup_maintenance_completed = True
                    return
                self._run_startup_maintenance(cursor)
                self._set_runtime_meta(cursor, STARTUP_MAINTENANCE_META_KEY, STARTUP_MAINTENANCE_VERSION)
                conn.commit()
            self._startup_maintenance_completed = True

    @staticmethod
    def _get_runtime_meta(cursor, key):
        cursor.execute(
            '''
            SELECT value
            FROM app_runtime_meta
            WHERE key = ?
            ''',
            (str(key or '').strip(),),
        )
        row = cursor.fetchone()
        return str((row or [''])[0] or '').strip()

    @classmethod
    def _is_startup_maintenance_current(cls, cursor):
        return cls._get_runtime_meta(cursor, STARTUP_MAINTENANCE_META_KEY) == STARTUP_MAINTENANCE_VERSION

    @staticmethod
    def _set_runtime_meta(cursor, key, value):
        cursor.execute(
            '''
            INSERT OR REPLACE INTO app_runtime_meta (key, value)
            VALUES (?, ?)
            ''',
            (
                str(key or '').strip(),
                str(value or '').strip(),
            ),
        )

    def _run_startup_maintenance(self, cursor):
        cursor.execute(
            '''
            UPDATE code_prefix_enrichments
            SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?)),
                avfan_last_error = COALESCE(NULLIF(avfan_last_error, ''), COALESCE(NULLIF(last_error, ''), '')),
                avfan_last_enriched_at = COALESCE(NULLIF(avfan_last_enriched_at, ''), last_enriched_at),
                javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?),
                javtxt_total_videos = COALESCE(javtxt_total_videos, 0)
            ''',
            (UNENRICHED_STATUS, UNENRICHED_STATUS),
        )
        cursor.execute(
            '''
            UPDATE actor_enrichments
            SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?)),
                avfan_last_error = COALESCE(NULLIF(avfan_last_error, ''), COALESCE(NULLIF(last_error, ''), '')),
                avfan_last_enriched_at = COALESCE(NULLIF(avfan_last_enriched_at, ''), last_enriched_at),
                javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?),
                javtxt_total_videos = COALESCE(javtxt_total_videos, 0)
            ''',
            (UNENRICHED_STATUS, UNENRICHED_STATUS),
        )
        cursor.execute(
            '''
            UPDATE code_prefix_movies
            SET javtxt_enrichment_status = COALESCE(
                    NULLIF(javtxt_enrichment_status, ''),
                    (
                        SELECT COALESCE(NULLIF(p.javtxt_enrichment_status, ''), ?)
                        FROM processed_videos p
                        WHERE p.code = code_prefix_movies.code
                    ),
                    ?
                ),
                javtxt_movie_id = COALESCE(
                    NULLIF(javtxt_movie_id, ''),
                    (
                        SELECT p.javtxt_movie_id
                        FROM processed_videos p
                        WHERE p.code = code_prefix_movies.code
                    ),
                    ''
                ),
                javtxt_url = COALESCE(
                    NULLIF(javtxt_url, ''),
                    (
                        SELECT p.javtxt_url
                        FROM processed_videos p
                        WHERE p.code = code_prefix_movies.code
                    ),
                    ''
                ),
                javtxt_tags = COALESCE(
                    NULLIF(javtxt_tags, ''),
                    (
                        SELECT p.javtxt_tags
                        FROM processed_videos p
                        WHERE p.code = code_prefix_movies.code
                    ),
                    ''
                ),
                javtxt_release_date = COALESCE(
                    NULLIF(javtxt_release_date, ''),
                    (
                        SELECT p.javtxt_release_date
                        FROM processed_videos p
                        WHERE p.code = code_prefix_movies.code
                    ),
                    ''
                ),
                author_raw = COALESCE(NULLIF(author_raw, ''), NULLIF(author, ''), '')
            ''',
            (UNENRICHED_STATUS, UNENRICHED_STATUS),
        )
        cursor.execute(
            '''
            UPDATE actor_movies
            SET javtxt_enrichment_status = COALESCE(
                    NULLIF(javtxt_enrichment_status, ''),
                    (
                        SELECT COALESCE(NULLIF(p.javtxt_enrichment_status, ''), ?)
                        FROM processed_videos p
                        WHERE p.code = actor_movies.code
                    ),
                    ?
                ),
                javtxt_movie_id = COALESCE(
                    NULLIF(javtxt_movie_id, ''),
                    (
                        SELECT p.javtxt_movie_id
                        FROM processed_videos p
                        WHERE p.code = actor_movies.code
                    ),
                    ''
                ),
                javtxt_url = COALESCE(
                    NULLIF(javtxt_url, ''),
                    (
                        SELECT p.javtxt_url
                        FROM processed_videos p
                        WHERE p.code = actor_movies.code
                    ),
                    ''
                ),
                javtxt_tags = COALESCE(
                    NULLIF(javtxt_tags, ''),
                    (
                        SELECT p.javtxt_tags
                        FROM processed_videos p
                        WHERE p.code = actor_movies.code
                    ),
                    ''
                ),
                javtxt_release_date = COALESCE(
                    NULLIF(javtxt_release_date, ''),
                    (
                        SELECT p.javtxt_release_date
                        FROM processed_videos p
                        WHERE p.code = actor_movies.code
                    ),
                    ''
                ),
                author_raw = COALESCE(NULLIF(author_raw, ''), NULLIF(author, ''), '')
            ''',
            (UNENRICHED_STATUS, UNENRICHED_STATUS),
        )
        cursor.execute(
            '''
            UPDATE processed_videos
            SET javtxt_actors_raw = COALESCE(NULLIF(javtxt_actors_raw, ''), NULLIF(javtxt_actors, ''), '')
            '''
        )
        cursor.executemany(
            'DELETE FROM actors WHERE lower(name) = ?',
            [(name,) for name in IGNORED_ACTOR_NAMES],
        )
        self._backfill_video_categories(cursor)
        self._clear_processed_video_javtxt_state_without_detail_reference(cursor)
        self._clear_ineligible_processed_video_javtxt_state(cursor)
        self._backfill_web_movie_categories(cursor, 'code_prefix_movies')
        self._backfill_web_movie_categories(cursor, 'actor_movies')
        self._normalize_existing_web_movie_codes(cursor)
        self._propagate_existing_web_movie_javtxt_state(cursor)
        self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'code_prefix_movies')
        self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'actor_movies')
        self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'code_prefix_movies')
        self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'actor_movies')
        self._clear_ineligible_web_movie_javtxt_state(cursor, 'code_prefix_movies')
        self._clear_ineligible_web_movie_javtxt_state(cursor, 'actor_movies')
        self._sanitize_legacy_actor_source_status_columns(cursor)
        self._sanitize_ineligible_javtxt_state(cursor)

    def _video_source_columns(self, source_key):
        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_enrichment_error', 'javtxt_enriched_at'
        return 'avfan_enrichment_status', 'avfan_enrichment_error', 'avfan_enriched_at'

    def _library_source_columns(self, source_key):
        normalized_source = normalize_video_enrichment_source(source_key)
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_last_error', 'javtxt_last_enriched_at'
        return 'avfan_enrichment_status', 'avfan_last_error', 'avfan_last_enriched_at'

    def _sanitize_legacy_actor_source_status_columns(self, cursor):
        cursor.execute(
            '''
            SELECT actor_name, avfan_enrichment_status, javtxt_enrichment_status,
                   binghuo_enrichment_status, baomu_enrichment_status
            FROM actor_enrichments
            '''
        )
        rows = cursor.fetchall()
        changed_actor_names = []
        for actor_name, avfan_status, javtxt_status, binghuo_status, baomu_status in rows:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name:
                continue
            cleaned_avfan = normalize_source_enrichment_status(avfan_status, AVFAN_VIDEO_SOURCE)
            cleaned_javtxt = normalize_source_enrichment_status(javtxt_status, JAVTXT_VIDEO_SOURCE)
            cleaned_binghuo = normalize_source_enrichment_status(binghuo_status, BINGHUO_ACTOR_SOURCE)
            cleaned_baomu = normalize_source_enrichment_status(baomu_status, BAOMU_ACTOR_SOURCE)
            current_values = (
                str(avfan_status or '').strip() or UNENRICHED_STATUS,
                str(javtxt_status or '').strip() or UNENRICHED_STATUS,
                str(binghuo_status or '').strip() or UNENRICHED_STATUS,
                str(baomu_status or '').strip() or UNENRICHED_STATUS,
            )
            cleaned_values = (cleaned_avfan, cleaned_javtxt, cleaned_binghuo, cleaned_baomu)
            if cleaned_values == current_values:
                continue
            cursor.execute(
                '''
                UPDATE actor_enrichments
                SET avfan_enrichment_status = ?,
                    javtxt_enrichment_status = ?,
                    binghuo_enrichment_status = ?,
                    baomu_enrichment_status = ?
                WHERE actor_name = ?
                ''',
                (*cleaned_values, normalized_name),
            )
            changed_actor_names.append(normalized_name)
        for actor_name in changed_actor_names:
            self._refresh_actor_combined_status(cursor, actor_name)

    @staticmethod
    def _normalize_video_category_fields(tags_text, actors_text):
        return str(tags_text or '').strip(), sanitize_actor_text(actors_text)

    @staticmethod
    def _load_video_category_filter_settings():
        return load_video_filter_settings()

    def _matches_co_star_code_keyword(self, code, filter_settings=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return False
        active_settings = filter_settings if isinstance(filter_settings, dict) else self._load_video_category_filter_settings()
        return matches_filter_keywords(
            normalized_code,
            get_filter_keywords(active_settings, FILTER_FIELD_CO_STAR_CODE),
        )

    def _determine_auto_video_category(self, code, tags_text, actors_text, filter_settings=None):
        normalized_tags, normalized_actors = self._normalize_video_category_fields(tags_text, actors_text)
        return detect_video_category(
            normalized_tags,
            normalized_actors,
            force_single_or_co_star=self._matches_co_star_code_keyword(code, filter_settings=filter_settings),
        )

    def _resolve_web_movie_category(self, movie, filter_settings=None):
        explicit_category = normalize_video_category((movie or {}).get('video_category', ''))
        if explicit_category:
            return explicit_category

        processed_category = normalize_video_category((movie or {}).get('processed_video_category', ''))
        if processed_category:
            return processed_category

        return self._determine_auto_video_category(
            (movie or {}).get('code', ''),
            (movie or {}).get('javtxt_tags', ''),
            (movie or {}).get('author', ''),
            filter_settings=filter_settings,
        )

    @staticmethod
    def _normalize_actor_raw_text(value):
        return normalize_actor_raw_text(value)

    def _refresh_video_category(self, cursor, code, tags_text=None, actors_text=None, filter_settings=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return

        cursor.execute(
            '''
            SELECT javtxt_tags, javtxt_actors, video_category
            FROM processed_videos
            WHERE code = ?
            ''',
            (normalized_code,),
        )
        row = cursor.fetchone()
        if row is None:
            return

        effective_tags = row[0] if tags_text is None else tags_text
        effective_actors = row[1] if actors_text is None else actors_text
        auto_category = self._determine_auto_video_category(
            normalized_code,
            effective_tags,
            effective_actors,
            filter_settings=filter_settings,
        )
        current_category = normalize_video_category(row[2])
        if auto_category and auto_category != current_category:
            cursor.execute(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, normalized_code),
            )

    def _backfill_video_categories(self, cursor, filter_settings=None):
        cursor.execute(
            '''
            SELECT code, javtxt_tags, javtxt_actors, video_category
            FROM processed_videos
            WHERE COALESCE(video_category, '') = ''
            '''
        )
        rows = cursor.fetchall()
        for row in rows:
            code = standardize_video_code(row[0])
            if not code:
                continue
            auto_category = self._determine_auto_video_category(
                code,
                row[1],
                row[2],
                filter_settings=filter_settings,
            )
            if not auto_category:
                continue
            cursor.execute(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, code),
            )

    def _backfill_web_movie_categories(self, cursor, table_name, filter_settings=None):
        cursor.execute(
            f'''
            SELECT rowid, code, author, javtxt_tags, video_category
            FROM {table_name}
            WHERE COALESCE(video_category, '') = ''
            '''
        )
        rows = cursor.fetchall()
        for rowid, code, author, javtxt_tags, current_category in rows:
            normalized_code = standardize_video_code(code)
            processed_category = ''
            if normalized_code:
                cursor.execute(
                    '''
                    SELECT video_category
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    (normalized_code,),
                )
                processed_row = cursor.fetchone()
                if processed_row is not None:
                    processed_category = normalize_video_category(processed_row[0])
            auto_category = processed_category or self._determine_auto_video_category(
                normalized_code,
                javtxt_tags,
                author,
                filter_settings=filter_settings,
            )
            if not auto_category:
                continue

            cursor.execute(
                f'''
                UPDATE {table_name}
                SET video_category = ?
                WHERE rowid = ?
                ''',
                (auto_category, rowid),
            )

    def _clear_staged_video_categories_for_categorized_codes(self, cursor):
        cursor.execute(
            '''
            DELETE FROM manual_category_staging
            WHERE code IN (
                SELECT code FROM processed_videos WHERE COALESCE(video_category, '') <> ''
                UNION
                SELECT code FROM code_prefix_movies WHERE COALESCE(video_category, '') <> ''
                UNION
                SELECT code FROM actor_movies WHERE COALESCE(video_category, '') <> ''
            )
            '''
        )

    def refresh_video_categories_from_filter_rules(self):
        filter_settings = self._load_video_category_filter_settings()
        if not get_filter_keywords(filter_settings, FILTER_FIELD_CO_STAR_CODE):
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            before_changes = conn.total_changes
            self._backfill_video_categories(cursor, filter_settings=filter_settings)
            self._backfill_web_movie_categories(cursor, 'code_prefix_movies', filter_settings=filter_settings)
            self._backfill_web_movie_categories(cursor, 'actor_movies', filter_settings=filter_settings)
            self._clear_staged_video_categories_for_categorized_codes(cursor)
            conn.commit()
            return int(conn.total_changes - before_changes)

    def _clear_ineligible_web_movie_javtxt_state(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid,
                   code,
                   title,
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date,
                   javtxt_enrichment_status
            FROM {table_name}
            WHERE COALESCE(javtxt_enrichment_status, '') <> ?
               OR COALESCE(javtxt_movie_id, '') <> ''
               OR COALESCE(javtxt_url, '') <> ''
               OR COALESCE(javtxt_tags, '') <> ''
            ''',
            (UNENRICHED_STATUS,),
        )
        rowids_to_mark_no_result = []
        rowids_to_preserve_terminal = []
        for (
            rowid,
            code,
            title,
            release_date,
            javtxt_tags,
            video_category,
            javtxt_release_date,
            javtxt_status,
        ) in cursor.fetchall():
            if self._is_sanitized_javtxt_state_eligible(
                {
                    'code': code,
                    'title': title,
                    'release_date': release_date,
                    'javtxt_release_date': javtxt_release_date,
                    'javtxt_tags': javtxt_tags,
                    'video_category': video_category,
                }
            ):
                continue
            if is_no_result_status(javtxt_status):
                rowids_to_preserve_terminal.append(rowid)
            else:
                rowids_to_mark_no_result.append(rowid)

        for index in range(0, len(rowids_to_preserve_terminal), 500):
            chunk = rowids_to_preserve_terminal[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE rowid IN ({placeholders})
                ''',
                (*chunk,),
            )

        for index in range(0, len(rowids_to_mark_no_result), 500):
            chunk = rowids_to_mark_no_result[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE rowid IN ({placeholders})
                ''',
                (NO_SEARCH_RESULTS_STATUS, *chunk),
            )

    def _clear_web_movie_javtxt_state_without_detail_reference(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid
            FROM {table_name}
            WHERE COALESCE(javtxt_movie_id, '') = ''
              AND COALESCE(javtxt_url, '') = ''
              AND (
                    COALESCE(author, '') <> ''
                 OR COALESCE(author_raw, '') <> ''
                 OR COALESCE(javtxt_enrichment_status, '') = ?
              )
            ''',
            (ENRICHED_STATUS,),
        )
        rowids_to_clear = [row[0] for row in cursor.fetchall() if row and row[0] is not None]
        for index in range(0, len(rowids_to_clear), 500):
            chunk = rowids_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_legacy_web_movie_javtxt_state_without_release_date(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid
            FROM {table_name}
            WHERE COALESCE(javtxt_release_date, '') = ''
              AND COALESCE(javtxt_enrichment_status, '') NOT IN (?, ?)
              AND (
                    COALESCE(javtxt_enrichment_status, '') <> ?
                 OR COALESCE(javtxt_movie_id, '') <> ''
                 OR COALESCE(javtxt_url, '') <> ''
                 OR COALESCE(javtxt_tags, '') <> ''
              )
            ''',
            (NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS, UNENRICHED_STATUS),
        )
        rowids_to_clear = [row[0] for row in cursor.fetchall() if row and row[0] is not None]
        for index in range(0, len(rowids_to_clear), 500):
            chunk = rowids_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_ineligible_processed_video_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date,
                   javtxt_enrichment_status
            FROM processed_videos
            WHERE COALESCE(javtxt_enrichment_status, '') <> ?
               OR COALESCE(javtxt_movie_id, '') <> ''
               OR COALESCE(javtxt_url, '') <> ''
               OR COALESCE(javtxt_tags, '') <> ''
            ''',
            (UNENRICHED_STATUS,),
        )
        codes_to_mark_no_result = []
        codes_to_preserve_terminal = []
        for (
            code,
            title,
            release_date,
            javtxt_tags,
            video_category,
            javtxt_release_date,
            javtxt_status,
        ) in cursor.fetchall():
            if self._is_sanitized_javtxt_state_eligible(
                {
                    'code': code,
                    'title': title,
                    'release_date': release_date,
                    'javtxt_release_date': javtxt_release_date,
                    'javtxt_tags': javtxt_tags,
                    'video_category': video_category,
                }
            ):
                continue
            normalized_code = standardize_video_code(code)
            if normalized_code:
                if is_no_result_status(javtxt_status):
                    codes_to_preserve_terminal.append(normalized_code)
                else:
                    codes_to_mark_no_result.append(normalized_code)

        for index in range(0, len(codes_to_preserve_terminal), 500):
            chunk = codes_to_preserve_terminal[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = ''
                WHERE code IN ({placeholders})
                ''',
                (*chunk,),
            )

        for index in range(0, len(codes_to_mark_no_result), 500):
            chunk = codes_to_mark_no_result[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = CASE
                        WHEN COALESCE(javtxt_enrichment_error, '') = '' THEN ?
                        ELSE javtxt_enrichment_error
                    END
                WHERE code IN ({placeholders})
                ''',
                (NO_SEARCH_RESULTS_STATUS, JAVTXT_INELIGIBLE_ERROR, *chunk),
            )

    def _clear_processed_video_javtxt_state_without_detail_reference(self, cursor):
        cursor.execute(
            '''
            SELECT code
            FROM processed_videos
            WHERE COALESCE(javtxt_movie_id, '') = ''
              AND COALESCE(javtxt_url, '') = ''
              AND (
                    COALESCE(javtxt_actors, '') <> ''
                 OR COALESCE(javtxt_actors_raw, '') <> ''
                 OR COALESCE(javtxt_enrichment_status, '') = ?
              )
            ''',
            (ENRICHED_STATUS,),
        )
        codes_to_clear = [
            standardize_video_code((row or [''])[0])
            for row in cursor.fetchall()
            if standardize_video_code((row or [''])[0])
        ]
        if not codes_to_clear:
            return

        for index in range(0, len(codes_to_clear), 500):
            chunk = codes_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_title = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_tags = '',
                    javtxt_release_date = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = '',
                    javtxt_enriched_at = NULL
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def sanitize_ineligible_javtxt_state(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            prefixes, actor_names = self._sanitize_ineligible_javtxt_state(cursor)
            conn.commit()
        if prefixes:
            self.refresh_code_prefix_javtxt_statuses(prefixes)
        if actor_names:
            self.refresh_actor_javtxt_statuses(actor_names)

    def _sanitize_ineligible_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT prefix FROM code_prefix_movies
            UNION
            SELECT prefix FROM code_prefix_enrichments
            '''
        )
        prefixes = [str((row or [''])[0] or '').strip().upper() for row in cursor.fetchall()]
        cursor.execute(
            '''
            SELECT actor_name FROM actor_movies
            UNION
            SELECT actor_name FROM actor_enrichments
            '''
        )
        actor_names = [str((row or [''])[0] or '').strip() for row in cursor.fetchall()]
        cursor.execute(
            '''
            SELECT code FROM code_prefix_movies
            UNION
            SELECT code FROM actor_movies
            '''
        )
        shared_codes = [
            standardize_video_code((row or [''])[0])
            for row in cursor.fetchall()
            if standardize_video_code((row or [''])[0])
        ]
        self._clear_processed_video_javtxt_state_without_detail_reference(cursor)
        self._clear_ineligible_processed_video_javtxt_state(cursor)
        self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'code_prefix_movies')
        self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'actor_movies')
        self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'code_prefix_movies')
        self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'actor_movies')
        self._clear_ineligible_web_movie_javtxt_state(cursor, 'code_prefix_movies')
        self._clear_ineligible_web_movie_javtxt_state(cursor, 'actor_movies')
        self._propagate_processed_video_javtxt_state_for_codes(cursor, shared_codes)

        return prefixes, actor_names

    def _is_sanitized_javtxt_state_eligible(self, movie):
        if not is_javtxt_eligible_movie(movie):
            return False

        category = normalize_video_category((movie or {}).get('video_category', ''))
        if not category:
            category = detect_video_category((movie or {}).get('javtxt_tags', ''), '')
        return category != VIDEO_CATEGORY_COLLECTION

    def _clear_processed_video_javtxt_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return

        for index in range(0, len(normalized_codes), 500):
            chunk = normalized_codes[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_title = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_tags = '',
                    javtxt_release_date = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = '',
                    javtxt_enriched_at = NULL
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_web_movie_javtxt_rowids(self, cursor, table_name, rowids):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')
        normalized_rowids = []
        seen = set()
        for rowid in rowids or []:
            try:
                normalized_rowid = int(rowid)
            except (TypeError, ValueError):
                continue
            if normalized_rowid <= 0 or normalized_rowid in seen:
                continue
            seen.add(normalized_rowid)
            normalized_rowids.append(normalized_rowid)
        if not normalized_rowids:
            return

        for index in range(0, len(normalized_rowids), 500):
            chunk = normalized_rowids[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _normalize_existing_web_movie_codes(self, cursor):
        self._normalize_processed_video_codes(cursor)
        self._normalize_code_prefix_movie_codes(cursor)
        self._normalize_actor_movie_codes(cursor)
        self._normalize_manual_category_staging_codes(cursor)

    def _normalize_processed_video_codes(self, cursor):
        cursor.execute('SELECT code FROM processed_videos')
        for (code,) in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute('SELECT 1 FROM processed_videos WHERE code = ?', (normalized_code,))
            if cursor.fetchone():
                cursor.execute('DELETE FROM processed_videos WHERE code = ?', (code,))
            else:
                cursor.execute('UPDATE processed_videos SET code = ? WHERE code = ?', (normalized_code, code))

    def _normalize_code_prefix_movie_codes(self, cursor):
        cursor.execute('SELECT prefix, code FROM code_prefix_movies')
        for prefix, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            normalized_prefix = self._extract_standard_code_prefix(normalized_code)
            if not normalized_code or not normalized_prefix:
                continue
            if normalized_code == code and normalized_prefix == prefix:
                continue
            cursor.execute(
                'SELECT 1 FROM code_prefix_movies WHERE prefix = ? AND code = ?',
                (normalized_prefix, normalized_code),
            )
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM code_prefix_movies WHERE prefix = ? AND code = ?',
                    (prefix, code),
                )
            else:
                cursor.execute(
                    '''
                    UPDATE code_prefix_movies
                    SET prefix = ?, code = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    (normalized_prefix, normalized_code, prefix, code),
                )

    def _normalize_actor_movie_codes(self, cursor):
        cursor.execute('SELECT actor_name, code FROM actor_movies')
        for actor_name, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute(
                'SELECT 1 FROM actor_movies WHERE actor_name = ? AND code = ?',
                (actor_name, normalized_code),
            )
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM actor_movies WHERE actor_name = ? AND code = ?',
                    (actor_name, code),
                )
            else:
                cursor.execute(
                    'UPDATE actor_movies SET code = ? WHERE actor_name = ? AND code = ?',
                    (normalized_code, actor_name, code),
                )

    def _normalize_manual_category_staging_codes(self, cursor):
        cursor.execute('SELECT code, category FROM manual_category_staging')
        for code, category in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute('DELETE FROM manual_category_staging WHERE code = ?', (code,))
            cursor.execute(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (normalized_code, category),
            )

    @staticmethod
    def _extract_standard_code_prefix(code):
        match = re.match(r'^([A-Z]+)', str(code or '').strip().upper())
        return match.group(1) if match else ''

    def _normalize_web_movie_javtxt_fields(self, movie, processed_record=None, filter_settings=None):
        processed_record = processed_record or {}
        tags = self._first_nonblank_text((movie or {}).get('javtxt_tags', ''), processed_record.get('javtxt_tags', ''))
        merged_status = self._first_nonblank_text(
            (movie or {}).get('javtxt_enrichment_status', ''),
            processed_record.get('javtxt_enrichment_status', ''),
        ) or UNENRICHED_STATUS
        javtxt_release_date = self._first_nonblank_text(
            (movie or {}).get('javtxt_release_date', ''),
            processed_record.get('javtxt_release_date', ''),
        )
        effective_release_date = javtxt_release_date or self._first_nonblank_text(
            (movie or {}).get('release_date', ''),
            processed_record.get('release_date', ''),
        )
        category = self._resolve_web_movie_category(
            {
                **dict(movie or {}),
                'javtxt_tags': tags,
                'processed_video_category': processed_record.get('video_category', ''),
            },
            filter_settings=filter_settings,
        )
        candidate = {
            **dict(movie or {}),
            'javtxt_tags': tags,
            'javtxt_release_date': javtxt_release_date,
            'release_date': effective_release_date,
            'video_category': category,
        }
        if not is_javtxt_eligible_movie(candidate):
            if is_no_result_status(merged_status):
                return merged_status, '', '', tags, javtxt_release_date, category
            return UNENRICHED_STATUS, '', '', '', javtxt_release_date, category

        return (
            merged_status,
            self._first_nonblank_text((movie or {}).get('javtxt_movie_id', ''), processed_record.get('javtxt_movie_id', '')),
            self._first_nonblank_text((movie or {}).get('javtxt_url', ''), processed_record.get('javtxt_url', '')),
            tags,
            javtxt_release_date,
            category,
        )

    @staticmethod
    def _first_nonblank_text(*values):
        for value in values:
            text = str(value or '').strip()
            if text:
                return text
        return ''

    @staticmethod
    def _has_javtxt_detail_reference(movie):
        current = dict(movie or {})
        return bool(
            str(current.get('javtxt_movie_id', '') or '').strip()
            or str(current.get('javtxt_url', '') or '').strip()
        )

    def _normalize_web_movie_actor_fields(self, movie, javtxt_movie_id='', javtxt_url=''):
        sanitized_author = sanitize_actor_text((movie or {}).get('author', ''))
        author_raw = self._normalize_actor_raw_text((movie or {}).get('author_raw', (movie or {}).get('author', '')))
        if not self._has_javtxt_detail_reference(
            {
                'javtxt_movie_id': javtxt_movie_id,
                'javtxt_url': javtxt_url,
            }
        ):
            return '', ''
        return sanitized_author, author_raw

    def _load_web_movie_javtxt_state_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        rows = []
        with self._connect() as conn:
            cursor = conn.cursor()
            for table_name in ('code_prefix_movies', 'actor_movies'):
                cursor.execute(
                    f'''
                    SELECT code, title, author, release_date, javtxt_enrichment_status,
                           javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                           author_raw, video_category
                    FROM {table_name}
                    WHERE code IN ({placeholders})
                    ''',
                    normalized_codes,
                )
                rows.extend(cursor.fetchall())

        best_rows = {}
        for row in rows:
            candidate = {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'release_date': row[3] or '',
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_tags': row[7] or '',
                'javtxt_release_date': row[8] or '',
                'author_raw': self._normalize_actor_raw_text(row[9] or row[2] or ''),
                'video_category': normalize_video_category(row[10]),
            }
            normalized_code = standardize_video_code(candidate['code'])
            if not normalized_code:
                continue
            current = best_rows.get(normalized_code)
            if current is None or self._web_movie_javtxt_state_score(candidate) > self._web_movie_javtxt_state_score(current):
                best_rows[normalized_code] = candidate
        return best_rows

    @staticmethod
    def _web_movie_javtxt_state_score(record):
        current = dict(record or {})
        has_detail = 1 if (
            str(current.get('javtxt_movie_id', '') or '').strip()
            or str(current.get('javtxt_url', '') or '').strip()
        ) else 0
        search_state = classify_search_state(current, cached_row=current)
        state_score = {
            'resolved': 4,
            'no_result': 3,
            'failed': 2,
            'unsearched': 1,
        }.get(search_state, 0)
        return (
            has_detail,
            state_score,
            len(str(current.get('author', '') or '').strip()),
            len(str(current.get('javtxt_tags', '') or '').strip()),
        )

    @staticmethod
    def _merge_javtxt_state_records(primary=None, fallback=None):
        primary = dict(primary or {})
        fallback = dict(fallback or {})
        if not fallback:
            return primary
        merged = dict(primary)
        for field_name in (
            'javtxt_enrichment_status',
            'javtxt_movie_id',
            'javtxt_url',
            'javtxt_tags',
            'javtxt_release_date',
            'release_date',
            'video_category',
        ):
            if not str(merged.get(field_name, '') or '').strip() and str(fallback.get(field_name, '') or '').strip():
                merged[field_name] = fallback.get(field_name, '')
        return merged

    @staticmethod
    def _merge_web_movie_actor_source(movie=None, fallback=None):
        merged = dict(movie or {})
        fallback = dict(fallback or {})
        for field_name in ('author', 'author_raw'):
            if not str(merged.get(field_name, '') or '').strip() and str(fallback.get(field_name, '') or '').strip():
                merged[field_name] = fallback.get(field_name, '')
        return merged

    def _propagate_web_movie_javtxt_state_for_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return 0

        placeholders = ','.join('?' for _ in normalized_codes)
        candidates = []
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.execute(
                f'''
                SELECT code, title, author, release_date, javtxt_enrichment_status,
                       javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                       author_raw, video_category
                FROM {table_name}
                WHERE code IN ({placeholders})
                  AND (COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> '')
                ''',
                normalized_codes,
            )
            candidates.extend(cursor.fetchall())

        best_by_code = {}
        for row in candidates:
            candidate = {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'release_date': row[3] or '',
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_tags': row[7] or '',
                'javtxt_release_date': row[8] or '',
                'author_raw': self._normalize_actor_raw_text(row[9] or row[2] or ''),
                'video_category': normalize_video_category(row[10]),
            }
            normalized_code = standardize_video_code(candidate['code'])
            if not normalized_code:
                continue
            current = best_by_code.get(normalized_code)
            if current is None or self._web_movie_javtxt_state_score(candidate) > self._web_movie_javtxt_state_score(current):
                best_by_code[normalized_code] = candidate

        if not best_by_code:
            return 0

        updates = [
            (
                state['author'],
                state['author_raw'],
                state['javtxt_enrichment_status'],
                state['javtxt_movie_id'],
                state['javtxt_url'],
                state['javtxt_tags'],
                state['javtxt_release_date'],
                state['javtxt_release_date'] or state['release_date'],
                state['video_category'],
                code,
            )
            for code, state in best_by_code.items()
        ]
        updated_count = 0
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.executemany(
                f'''
                UPDATE {table_name}
                SET author = ?,
                    author_raw = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    video_category = COALESCE(NULLIF(?, ''), video_category)
                WHERE code = ?
                ''',
                updates,
            )
            updated_count += int(cursor.rowcount or 0)
        return updated_count

    def _propagate_existing_web_movie_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT code
            FROM code_prefix_movies
            WHERE COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> ''
            UNION
            SELECT code
            FROM actor_movies
            WHERE COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> ''
            '''
        )
        codes = [
            standardize_video_code((row or [''])[0])
            for row in cursor.fetchall()
            if standardize_video_code((row or [''])[0])
        ]
        for index in range(0, len(codes), 500):
            self._propagate_web_movie_javtxt_state_for_codes(cursor, codes[index:index + 500])

    def _load_processed_video_javtxt_state_by_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        cursor.execute(
            f'''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_enrichment_status,
                   javtxt_movie_id,
                   javtxt_url,
                   javtxt_actors,
                   javtxt_actors_raw
            FROM processed_videos
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        return {
            standardize_video_code(row[0]): {
                'code': row[0] or '',
                'title': row[1] or '',
                'release_date': row[2] or '',
                'javtxt_release_date': row[3] or '',
                'javtxt_tags': row[4] or '',
                'video_category': normalize_video_category(row[5]),
                'javtxt_enrichment_status': row[6] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[7] or '',
                'javtxt_url': row[8] or '',
                'author': sanitize_actor_text(row[9] or ''),
                'author_raw': self._normalize_actor_raw_text(row[10] or row[9] or ''),
            }
            for row in cursor.fetchall()
            if standardize_video_code(row[0])
        }

    def _propagate_processed_video_javtxt_state_for_codes(self, cursor, codes):
        processed_rows = self._load_processed_video_javtxt_state_by_codes(cursor, codes)
        if not processed_rows:
            return 0

        updates = []
        for code, row in processed_rows.items():
            candidate = {
                'code': code,
                'title': row.get('title', ''),
                'release_date': row.get('release_date', ''),
                'javtxt_release_date': row.get('javtxt_release_date', ''),
                'javtxt_tags': row.get('javtxt_tags', ''),
                'video_category': row.get('video_category', ''),
            }
            if is_javtxt_eligible_movie(candidate):
                javtxt_status = str(row.get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
                javtxt_movie_id = str(row.get('javtxt_movie_id', '') or '').strip()
                javtxt_url = str(row.get('javtxt_url', '') or '').strip()
                javtxt_tags = str(row.get('javtxt_tags', '') or '').strip()
                javtxt_release_date = str(row.get('javtxt_release_date', '') or '').strip()
                release_date = str(row.get('release_date', '') or '').strip()
                video_category = normalize_video_category(row.get('video_category', ''))
                has_detail_reference = self._has_javtxt_detail_reference(
                    {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                )
                if javtxt_status == ENRICHED_STATUS and not has_detail_reference:
                    javtxt_status = UNENRICHED_STATUS
                author = sanitize_actor_text(row.get('author', '')) if has_detail_reference else ''
                author_raw = self._normalize_actor_raw_text(row.get('author_raw', '')) if has_detail_reference else ''
            else:
                javtxt_status = str(row.get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
                if not is_no_result_status(javtxt_status):
                    javtxt_status = UNENRICHED_STATUS
                javtxt_movie_id = ''
                javtxt_url = ''
                javtxt_tags = str(row.get('javtxt_tags', '') or '').strip() if is_no_result_status(javtxt_status) else ''
                javtxt_release_date = str(row.get('javtxt_release_date', '') or '').strip()
                release_date = str(row.get('release_date', '') or '').strip()
                video_category = normalize_video_category(row.get('video_category', ''))
                author = ''
                author_raw = ''

            updates.append(
                (
                    author,
                    author_raw,
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_tags,
                    javtxt_release_date,
                    release_date,
                    video_category,
                    code,
                )
            )

        updated_count = 0
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.executemany(
                f'''
                UPDATE {table_name}
                SET author = ?,
                    author_raw = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    video_category = COALESCE(NULLIF(?, ''), video_category)
                WHERE code = ?
                ''',
                updates,
            )
            updated_count += int(cursor.rowcount or 0)
        return updated_count

    def _list_web_movie_parent_keys_for_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return set(), set()

        placeholders = ','.join('?' for _ in normalized_codes)
        cursor.execute(
            f'''
            SELECT DISTINCT prefix
            FROM code_prefix_movies
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        prefixes = {
            str((row or [''])[0] or '').strip().upper()
            for row in cursor.fetchall()
            if str((row or [''])[0] or '').strip()
        }
        cursor.execute(
            f'''
            SELECT DISTINCT actor_name
            FROM actor_movies
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        actor_names = {
            str((row or [''])[0] or '').strip()
            for row in cursor.fetchall()
            if str((row or [''])[0] or '').strip()
        }
        return prefixes, actor_names

    def _refresh_web_movie_parent_javtxt_statuses_for_codes(self, codes):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
        ]
        if not normalized_codes:
            return

        with self._connect() as conn:
            cursor = conn.cursor()
            prefixes, actor_names = self._list_web_movie_parent_keys_for_codes(cursor, normalized_codes)

        if prefixes:
            self.refresh_code_prefix_javtxt_statuses(sorted(prefixes))
        if actor_names:
            self.refresh_actor_javtxt_statuses(sorted(actor_names))

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with self._connect() as conn:
            cursor = conn.cursor()
            for plan in plans:
                normalized_code = standardize_video_code(plan.metadata.code)
                if not normalized_code:
                    continue
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
                    normalized_code,
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
        with self._connect() as conn:
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

    @staticmethod
    def _sql_effective_actor_birthday(primary_birthday, binghuo_birthday, baomu_birthday):
        normalized_primary = normalize_second_source_actor_text(primary_birthday)
        if normalized_primary:
            return normalize_actor_birthday_for_storage(normalized_primary)
        for value in (binghuo_birthday, baomu_birthday):
            normalized_value = normalize_second_source_actor_text(value)
            if normalized_value:
                return normalize_actor_birthday_for_storage(normalized_value)
        return str(primary_birthday or '').strip()

    @staticmethod
    def _sql_sortable_actor_birthday(primary_birthday, binghuo_birthday, baomu_birthday):
        for value in (primary_birthday, binghuo_birthday, baomu_birthday):
            normalized_value = normalize_second_source_actor_text(value)
            if normalized_value:
                return normalize_actor_birthday_for_storage(normalized_value)
        return ''

    @classmethod
    def _sql_effective_actor_age(cls, primary_age, binghuo_age, primary_birthday, binghuo_birthday, baomu_birthday):
        for value in (primary_age, binghuo_age):
            normalized_value = normalize_second_source_actor_text(value)
            if normalized_value and normalized_value.isdigit():
                return str(int(normalized_value))
        birthday = cls._sql_effective_actor_birthday(primary_birthday, binghuo_birthday, baomu_birthday)
        if not birthday:
            return ''
        try:
            birthday_date = date.fromisoformat(birthday)
        except ValueError:
            return ''
        today = date.today()
        age = today.year - birthday_date.year
        if (today.month, today.day) < (birthday_date.month, birthday_date.day):
            age -= 1
        return str(max(age, 0))

    @classmethod
    def _actor_order_by_sql(cls, sort_field='name', sort_order='asc'):
        direction = cls._normalize_list_sort_order(sort_order)
        order_sql_map = {
            'name': f'UPPER(a.name) {direction}',
            'birthday': (
                "sortable_actor_birthday_sql(a.birthday, e.binghuo_birthday, e.baomu_birthday) "
                f"{direction}, UPPER(a.name) {direction}"
            ),
            'age': (
                "CAST(effective_actor_age_sql(a.age, e.binghuo_age, a.birthday, e.binghuo_birthday, e.baomu_birthday) AS INTEGER) "
                f"{direction}, UPPER(a.name) {direction}"
            ),
        }
        return order_sql_map.get(str(sort_field or '').strip(), order_sql_map['name'])

    @staticmethod
    def _actor_search_where_sql(search_text=''):
        normalized_search = str(search_text or '').strip()
        ignored_names = [str(name or '').strip() for name in IGNORED_ACTOR_NAMES if str(name or '').strip()]
        clauses = []
        params = []
        if ignored_names:
            clauses.append('a.name NOT IN ({})'.format(','.join('?' for _ in ignored_names)))
            params.extend(ignored_names)
        if normalized_search:
            like_value = f'%{normalized_search}%'
            clauses.append(
                '''
                (
                    a.name LIKE ?
                    OR effective_actor_birthday_sql(a.birthday, e.binghuo_birthday, e.baomu_birthday) LIKE ?
                    OR effective_actor_age_sql(a.age, e.binghuo_age, a.birthday, e.binghuo_birthday, e.baomu_birthday) LIKE ?
                    OR COALESCE(e.actor_id, '') LIKE ?
                    OR COALESCE(e.enrichment_status, ?) LIKE ?
                )
                '''
            )
            params.extend([like_value, like_value, like_value, like_value, UNENRICHED_STATUS, like_value])
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        return where_sql, tuple(params)

    @staticmethod
    def _build_actor_list_row(row):
        actor_name = row[0] or ''
        display_birthday = normalize_actor_birthday_for_display(row[1] or '')
        avfan_enrichment_status = normalize_source_enrichment_status(row[5] or UNENRICHED_STATUS, AVFAN_VIDEO_SOURCE)
        javtxt_enrichment_status = normalize_source_enrichment_status(row[6] or UNENRICHED_STATUS, JAVTXT_VIDEO_SOURCE)
        binghuo_enrichment_status = normalize_source_enrichment_status(row[7] or UNENRICHED_STATUS, BINGHUO_ACTOR_SOURCE)
        baomu_enrichment_status = normalize_source_enrichment_status(row[8] or UNENRICHED_STATUS, BAOMU_ACTOR_SOURCE)
        enrichment_status = build_library_enrichment_status_text(
            avfan_enrichment_status,
            javtxt_enrichment_status,
            binghuo_enrichment_status,
            baomu_enrichment_status,
        )
        return {
            'name': actor_name,
            'birthday': display_birthday,
            'raw_age': row[2] or '',
            'age': normalize_actor_age_for_display(row[2] or '', display_birthday),
            'matched': bool(row[3]),
            'actor_id': row[4] or '',
            'avfan_enrichment_status': avfan_enrichment_status,
            'javtxt_enrichment_status': javtxt_enrichment_status,
            'binghuo_enrichment_status': binghuo_enrichment_status,
            'baomu_enrichment_status': baomu_enrichment_status,
            'binghuo_person_id': row[9] or '',
            'binghuo_birthday': row[10] or '',
            'binghuo_age': row[11] or '',
            'binghuo_height': row[12] or '',
            'binghuo_bust': row[13] or '',
            'binghuo_waist': row[14] or '',
            'binghuo_hip': row[15] or '',
            'baomu_birthday': row[16] or '',
            'enrichment_status': enrichment_status or UNENRICHED_STATUS,
        }

    def list_actors(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        """读取演员库，必要时按演员/生日/年龄/补全状态筛选。"""
        where_sql, parameters = self._actor_search_where_sql(search_text)
        order_by_sql = self._actor_order_by_sql(sort_field, sort_order)
        normalized_limit, normalized_offset = self._normalize_limit_offset(limit, offset)
        limit_sql = ''
        query_parameters = list(parameters)
        if normalized_limit is not None:
            limit_sql = ' LIMIT ? OFFSET ?'
            query_parameters.extend([normalized_limit, normalized_offset])

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT a.name,
                       effective_actor_birthday_sql(a.birthday, e.binghuo_birthday, e.baomu_birthday) AS merged_birthday,
                       effective_actor_age_sql(a.age, e.binghuo_age, a.birthday, e.binghuo_birthday, e.baomu_birthday) AS merged_age,
                       a.matched,
                       COALESCE(e.actor_id, '') AS actor_id,
                       COALESCE(e.avfan_enrichment_status, ?) AS avfan_enrichment_status,
                       COALESCE(e.javtxt_enrichment_status, ?) AS javtxt_enrichment_status,
                       COALESCE(e.binghuo_enrichment_status, ?) AS binghuo_enrichment_status,
                       COALESCE(e.baomu_enrichment_status, ?) AS baomu_enrichment_status,
                       COALESCE(e.binghuo_person_id, '') AS binghuo_person_id,
                       COALESCE(e.binghuo_birthday, '') AS binghuo_birthday,
                       COALESCE(e.binghuo_age, '') AS binghuo_age,
                       COALESCE(e.binghuo_height, '') AS binghuo_height,
                       COALESCE(e.binghuo_bust, '') AS binghuo_bust,
                       COALESCE(e.binghuo_waist, '') AS binghuo_waist,
                       COALESCE(e.binghuo_hip, '') AS binghuo_hip,
                       COALESCE(e.baomu_birthday, '') AS baomu_birthday
                FROM actors a
                LEFT JOIN actor_enrichments e ON e.actor_name = a.name
                {where_sql}
                ORDER BY {order_by_sql}
                {limit_sql}
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS, UNENRICHED_STATUS, UNENRICHED_STATUS, *query_parameters),
            )
            rows = cursor.fetchall()

        return [self._build_actor_list_row(row) for row in rows if not is_ignored_actor_name(row[0] or '')]

    def count_actors(self, search_text=''):
        where_sql, parameters = self._actor_search_where_sql(search_text)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM actors a
                LEFT JOIN actor_enrichments e ON e.actor_name = a.name
                {where_sql}
                ''',
                tuple(parameters),
            )
            row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    @staticmethod
    def _code_prefix_expression_sql(code_field='code'):
        return (
            "UPPER(CASE WHEN instr({field}, '-') > 0 "
            "THEN substr({field}, 1, instr({field}, '-') - 1) "
            "ELSE {field} END)"
        ).format(field=code_field)

    @classmethod
    def _code_prefix_order_by_sql(cls, sort_field='prefix', sort_order='asc'):
        direction = cls._normalize_list_sort_order(sort_order)
        order_sql_map = {
            'prefix': f'combined.prefix {direction}',
            'video_count': f'COALESCE(local.video_count, 0) {direction}, combined.prefix {direction}',
            'avfan_total_videos': (
                f'COALESCE(enrich.avfan_total_videos, 0) {direction}, '
                f'COALESCE(local.video_count, 0) {direction}, combined.prefix {direction}'
            ),
            'earliest_release_date': (
                f"COALESCE(NULLIF(web.earliest_release_date, ''), '') {direction}, combined.prefix {direction}"
            ),
            'latest_release_date': (
                f"COALESCE(NULLIF(web.latest_release_date, ''), '') {direction}, combined.prefix {direction}"
            ),
        }
        return order_sql_map.get(str(sort_field or '').strip(), order_sql_map['prefix'])

    @staticmethod
    def _code_prefix_search_where_sql(search_text=''):
        normalized_search = str(search_text or '').strip().upper()
        if not normalized_search:
            return 'WHERE hidden.prefix IS NULL', ()
        return 'WHERE hidden.prefix IS NULL AND combined.prefix LIKE ?', (f'%{normalized_search}%',)

    def list_code_prefix_summaries(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        prefix_sql = self._code_prefix_expression_sql('code')
        where_sql, parameters = self._code_prefix_search_where_sql(search_text)
        order_by_sql = self._code_prefix_order_by_sql(sort_field, sort_order)
        normalized_limit, normalized_offset = self._normalize_limit_offset(limit, offset)
        limit_sql = ''
        query_parameters = list(parameters)
        if normalized_limit is not None:
            limit_sql = ' LIMIT ? OFFSET ?'
            query_parameters.extend([normalized_limit, normalized_offset])

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                WITH local AS (
                    SELECT
                        {prefix_sql} AS prefix,
                        COUNT(*) AS video_count
                    FROM processed_videos
                    WHERE TRIM(COALESCE(code, '')) <> ''
                      AND {prefix_sql} GLOB '*[A-Z]*'
                    GROUP BY {prefix_sql}
                ),
                enrich AS (
                    SELECT
                        UPPER(prefix) AS prefix,
                        COALESCE(avfan_enrichment_status, ?) AS avfan_enrichment_status,
                        COALESCE(javtxt_enrichment_status, ?) AS javtxt_enrichment_status,
                        COALESCE(avfan_total_pages, 0) AS avfan_total_pages,
                        COALESCE(avfan_total_videos, 0) AS avfan_total_videos,
                        COALESCE(last_enriched_at, '') AS last_enriched_at
                    FROM code_prefix_enrichments
                    WHERE TRIM(COALESCE(prefix, '')) <> ''
                ),
                web AS (
                    SELECT
                        UPPER(prefix) AS prefix,
                        MIN(CASE WHEN TRIM(COALESCE(release_date, '')) <> '' THEN release_date END) AS earliest_release_date,
                        MAX(CASE WHEN TRIM(COALESCE(release_date, '')) <> '' THEN release_date END) AS latest_release_date
                    FROM code_prefix_movies
                    WHERE TRIM(COALESCE(prefix, '')) <> ''
                    GROUP BY UPPER(prefix)
                ),
                combined AS (
                    SELECT prefix FROM local
                    UNION
                    SELECT prefix FROM enrich
                )
                SELECT
                    combined.prefix,
                    COALESCE(local.video_count, 0) AS video_count,
                    COALESCE(enrich.avfan_enrichment_status, ?) AS avfan_enrichment_status,
                    COALESCE(enrich.javtxt_enrichment_status, ?) AS javtxt_enrichment_status,
                    COALESCE(enrich.avfan_total_pages, 0) AS avfan_total_pages,
                    COALESCE(enrich.avfan_total_videos, 0) AS avfan_total_videos,
                    COALESCE(web.earliest_release_date, '') AS earliest_release_date,
                    COALESCE(web.latest_release_date, '') AS latest_release_date,
                    COALESCE(enrich.last_enriched_at, '') AS last_enriched_at
                FROM combined
                LEFT JOIN local ON local.prefix = combined.prefix
                LEFT JOIN enrich ON enrich.prefix = combined.prefix
                LEFT JOIN web ON web.prefix = combined.prefix
                LEFT JOIN hidden_code_prefixes hidden ON UPPER(hidden.prefix) = combined.prefix
                {where_sql}
                ORDER BY {order_by_sql}
                {limit_sql}
                ''',
                (
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    *query_parameters,
                ),
            )
            rows = cursor.fetchall()

        return [
            {
                'prefix': row[0] or '',
                'video_count': int(row[1] or 0),
                'avfan_enrichment_status': row[2] or UNENRICHED_STATUS,
                'javtxt_enrichment_status': row[3] or UNENRICHED_STATUS,
                'avfan_total_pages': int(row[4] or 0),
                'avfan_total_videos': int(row[5] or 0),
                'earliest_release_date': row[6] or '',
                'latest_release_date': row[7] or '',
                'last_enriched_at': row[8] or '',
            }
            for row in rows
            if row[0]
        ]

    def count_code_prefixes(self, search_text=''):
        prefix_sql = self._code_prefix_expression_sql('code')
        where_sql, parameters = self._code_prefix_search_where_sql(search_text)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                WITH local AS (
                    SELECT {prefix_sql} AS prefix
                    FROM processed_videos
                    WHERE TRIM(COALESCE(code, '')) <> ''
                      AND {prefix_sql} GLOB '*[A-Z]*'
                    GROUP BY {prefix_sql}
                ),
                enrich AS (
                    SELECT UPPER(prefix) AS prefix
                    FROM code_prefix_enrichments
                    WHERE TRIM(COALESCE(prefix, '')) <> ''
                ),
                combined AS (
                    SELECT prefix FROM local
                    UNION
                    SELECT prefix FROM enrich
                )
                SELECT COUNT(*)
                FROM combined
                LEFT JOIN hidden_code_prefixes hidden ON UPPER(hidden.prefix) = combined.prefix
                {where_sql}
                ''',
                tuple(parameters),
            )
            row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    def add_actor(self, actor_name, birthday='', age=''):
        normalized_name = str(actor_name or '').strip()
        normalized_birthday = normalize_actor_birthday_for_storage(birthday)
        normalized_age = str(age or '').strip()
        if not normalized_name:
            raise ValueError('演员名称不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM actors WHERE name = ?', (normalized_name,))
            if cursor.fetchone():
                raise ValueError(f'演员 {normalized_name} 已存在')

            cursor.execute('SELECT 1 FROM hidden_actors WHERE name = ?', (normalized_name,))
            if cursor.fetchone():
                raise ValueError(f'演员 {normalized_name} 已被删除，请避免重复添加')

            cursor.execute(
                '''
                INSERT INTO actors (name, birthday, age, matched)
                VALUES (?, ?, ?, 0)
                ''',
                (normalized_name, normalized_birthday, normalized_age),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def hide_actor(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            raise ValueError('婕斿憳鍚嶇О涓嶈兘涓虹┖')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO hidden_actors (name) VALUES (?)',
                (normalized_name,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def _refresh_code_prefix_combined_status(self, cursor, prefix):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status,
                   avfan_last_error, javtxt_last_error,
                   avfan_last_enriched_at, javtxt_last_enriched_at
            FROM code_prefix_enrichments
            WHERE prefix = ?
            ''',
            (prefix,),
        )
        row = cursor.fetchone() or (
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            '',
            '',
            '',
            '',
        )
        avfan_status, javtxt_status, avfan_error, javtxt_error, avfan_at, javtxt_at = row
        combined_status = build_library_enrichment_status_text(avfan_status, javtxt_status)
        latest_error = str(javtxt_error or avfan_error or '')
        latest_at = str(javtxt_at or avfan_at or '')
        cursor.execute(
            '''
            UPDATE code_prefix_enrichments
            SET enrichment_status = ?,
                last_error = ?,
                last_enriched_at = ?
            WHERE prefix = ?
            ''',
            (combined_status, latest_error, latest_at, prefix),
        )

    def _refresh_actor_combined_status(self, cursor, actor_name):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status, binghuo_enrichment_status, baomu_enrichment_status,
                   avfan_last_error, javtxt_last_error, binghuo_last_error, baomu_last_error,
                   avfan_last_enriched_at, javtxt_last_enriched_at, binghuo_last_enriched_at, baomu_last_enriched_at
            FROM actor_enrichments
            WHERE actor_name = ?
            ''',
            (actor_name,),
        )
        row = cursor.fetchone() or (
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
        )
        (
            avfan_status,
            javtxt_status,
            binghuo_status,
            baomu_status,
            avfan_error,
            javtxt_error,
            binghuo_error,
            baomu_error,
            avfan_at,
            javtxt_at,
            binghuo_at,
            baomu_at,
        ) = row
        combined_status = build_library_enrichment_status_text(avfan_status, javtxt_status, binghuo_status, baomu_status)
        latest_error = str(baomu_error or binghuo_error or javtxt_error or avfan_error or '')
        latest_at = str(baomu_at or binghuo_at or javtxt_at or avfan_at or '')
        cursor.execute(
            '''
            UPDATE actor_enrichments
            SET enrichment_status = ?,
                last_error = ?,
                last_enriched_at = ?
            WHERE actor_name = ?
            ''',
            (combined_status, latest_error, latest_at, actor_name),
        )

    def _build_live_actor_enrichment_status(self, enrichment, movies, cache_rows=None):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '') or '').strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        if cache_rows is None:
            cache_rows = self.get_javtxt_actor_cache_by_codes(
                [standardize_video_code((movie or {}).get('code', '')) for movie in (movies or [])]
            )
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(movies, cache_rows=cache_rows)
        binghuo_status = str((enrichment or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        return build_library_enrichment_status_text(avfan_status, javtxt_status, binghuo_status)

    @staticmethod
    def _has_javtxt_author(movie):
        return bool(normalize_second_source_actor_text((movie or {}).get('author', '')))

    def list_code_prefix_enrichment_records(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at, avfan_enrichment_status, avfan_last_error,
                       avfan_last_enriched_at, javtxt_enrichment_status, javtxt_total_videos,
                       javtxt_last_error, javtxt_last_enriched_at
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
                    'avfan_enrichment_status': row[6] or UNENRICHED_STATUS,
                    'avfan_last_error': row[7] or '',
                    'avfan_last_enriched_at': row[8] or '',
                    'javtxt_enrichment_status': row[9] or UNENRICHED_STATUS,
                    'javtxt_total_videos': int(row[10] or 0),
                    'javtxt_last_error': row[11] or '',
                    'javtxt_last_enriched_at': row[12] or '',
                }
                for row in cursor.fetchall()
                if row[0]
            }

    def add_code_prefix(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            raise ValueError('番号前缀不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT 1 FROM code_prefix_enrichments WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已存在')

            cursor.execute('SELECT 1 FROM code_prefix_movies WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已存在网页作品记录')

            cursor.execute('SELECT 1 FROM hidden_code_prefixes WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已被删除，请避免重复添加')

            cursor.execute('SELECT code FROM processed_videos')
            for row in cursor.fetchall():
                if extract_code_prefix(row[0] or '') == normalized_prefix:
                    raise ValueError(f'番号前缀 {normalized_prefix} 已存在')

            cursor.execute(
                '''
                INSERT INTO code_prefix_enrichments (
                    prefix,
                    enrichment_status,
                    avfan_enrichment_status,
                    javtxt_enrichment_status
                )
                VALUES (?, ?, ?, ?)
                ''',
                (
                    normalized_prefix,
                    build_library_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                ),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_code_prefix_enrichment(self, prefix, status, total_pages=0, total_videos=0, error='', source_key=AVFAN_VIDEO_SOURCE):
        normalized_prefix = str(prefix or '').strip().upper()
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, error_column, at_column = self._library_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO code_prefix_enrichments (prefix)
                VALUES (?)
                ''',
                (normalized_prefix,),
            )
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_prefix,
                    ),
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        avfan_total_pages = ?,
                        avfan_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(total_pages or 0),
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_prefix,
                    ),
                )
            self._refresh_code_prefix_combined_status(cursor, normalized_prefix)
            conn.commit()

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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (prefix,))
            if normalized_movies:
                values = []
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
                    values.append(
                        (
                            prefix,
                            normalized_code,
                            movie.get('title', ''),
                            author,
                            javtxt_release_date or movie.get('release_date', ''),
                            movie.get('avfan_url', ''),
                            int(movie.get('page_number', 1) or 1),
                            javtxt_status,
                            javtxt_movie_id,
                            javtxt_url,
                            javtxt_tags,
                            javtxt_release_date,
                            author_raw,
                            video_category,
                            str(existing_movie.get('supplement_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                            str(existing_movie.get('supplement_enrichment_error', '') or '').strip(),
                            str(existing_movie.get('supplement_enriched_at', '') or '').strip(),
                        )
                    )
                cursor.executemany('''
                    INSERT OR REPLACE INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category,
                        supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values)
                self._propagate_web_movie_javtxt_state_for_codes(
                    cursor,
                    [movie['code'] for movie in normalized_movies],
                )
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses([prefix])

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
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'avfan_last_error': '',
            'avfan_last_enriched_at': '',
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'javtxt_total_videos': 0,
            'javtxt_last_error': '',
            'javtxt_last_enriched_at': '',
        })

    def list_code_prefix_movies(self, prefix):
        prefix = str(prefix or '').strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM code_prefix_movies
                WHERE prefix = ?
                ORDER BY release_date DESC, code DESC
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

    def list_all_code_prefix_movies(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM code_prefix_movies
                ORDER BY prefix, release_date DESC, code DESC
                '''
            )

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

    def list_code_prefix_movies_by_prefixes(self, prefixes):
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM code_prefix_movies
                WHERE prefix IN ({placeholders})
                ORDER BY prefix, release_date DESC, code DESC
                ''',
                normalized_prefixes,
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

        return results

    def list_actor_enrichment_records(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, actor_id, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at, avfan_enrichment_status, avfan_last_error,
                       avfan_last_enriched_at, javtxt_enrichment_status, javtxt_total_videos,
                       javtxt_last_error, javtxt_last_enriched_at, binghuo_person_id,
                       binghuo_enrichment_status, binghuo_last_error, binghuo_last_enriched_at,
                       binghuo_birthday, binghuo_age, binghuo_height, binghuo_bust,
                       binghuo_cup, binghuo_measurements_raw, binghuo_waist, binghuo_hip, baomu_enrichment_status, baomu_last_error,
                       baomu_last_enriched_at, baomu_birthday, baomu_height, baomu_bust,
                       baomu_cup, baomu_measurements_raw, baomu_waist, baomu_hip
                FROM actor_enrichments
            ''')

            records = {}
            for row in cursor.fetchall():
                if not row[0]:
                    continue
                avfan_status = normalize_source_enrichment_status(row[7] or UNENRICHED_STATUS, AVFAN_VIDEO_SOURCE)
                javtxt_status = normalize_source_enrichment_status(row[10] or UNENRICHED_STATUS, JAVTXT_VIDEO_SOURCE)
                binghuo_status = normalize_source_enrichment_status(row[15] or UNENRICHED_STATUS, BINGHUO_ACTOR_SOURCE)
                baomu_status = normalize_source_enrichment_status(row[26] or UNENRICHED_STATUS, BAOMU_ACTOR_SOURCE)
                records[row[0] or ''] = {
                    'actor_name': row[0] or '',
                    'actor_id': row[1] or '',
                    'enrichment_status': row[2] or '',
                    'avfan_total_pages': int(row[3] or 0),
                    'avfan_total_videos': int(row[4] or 0),
                    'last_error': row[5] or '',
                    'last_enriched_at': row[6] or '',
                    'avfan_enrichment_status': avfan_status,
                    'avfan_last_error': row[8] or '',
                    'avfan_last_enriched_at': row[9] or '',
                    'javtxt_enrichment_status': javtxt_status,
                    'javtxt_total_videos': int(row[11] or 0),
                    'javtxt_last_error': row[12] or '',
                    'javtxt_last_enriched_at': row[13] or '',
                    'binghuo_person_id': row[14] or '',
                    'binghuo_enrichment_status': binghuo_status,
                    'binghuo_last_error': row[16] or '',
                    'binghuo_last_enriched_at': row[17] or '',
                    'binghuo_birthday': row[18] or '',
                    'binghuo_age': row[19] or '',
                    'binghuo_height': row[20] or '',
                    'binghuo_bust': row[21] or '',
                    'binghuo_cup': row[22] or '',
                    'binghuo_measurements_raw': row[23] or '',
                    'binghuo_waist': row[24] or '',
                    'binghuo_hip': row[25] or '',
                    'baomu_enrichment_status': baomu_status,
                    'baomu_last_error': row[27] or '',
                    'baomu_last_enriched_at': row[28] or '',
                    'baomu_birthday': row[29] or '',
                    'baomu_height': row[30] or '',
                    'baomu_bust': row[31] or '',
                    'baomu_cup': row[32] or '',
                    'baomu_measurements_raw': row[33] or '',
                    'baomu_waist': row[34] or '',
                    'baomu_hip': row[35] or '',
                }
            return records

    def save_actor_enrichment(self, actor_name, status, total_pages=0, total_videos=0, error='', actor_id='', source_key=AVFAN_VIDEO_SOURCE):
        normalized_name = str(actor_name or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key)
        if normalized_source == BINGHUO_ACTOR_SOURCE:
            raise ValueError('Use save_binghuo_actor_profile for Binghuo actor data')
        status_column, error_column, at_column = self._library_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO actor_enrichments (actor_name, actor_id)
                VALUES (?, ?)
                ''',
                (normalized_name, str(actor_id or '').strip()),
            )
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        status,
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_name,
                    ),
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET actor_id = COALESCE(NULLIF(?, ''), actor_id),
                        {status_column} = ?,
                        avfan_total_pages = ?,
                        avfan_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        str(actor_id or '').strip(),
                        status,
                        int(total_pages or 0),
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_name,
                    ),
                )
            self._refresh_actor_combined_status(cursor, normalized_name)
            conn.commit()

    def save_binghuo_actor_profile(
        self,
        actor_name,
        status,
        person_id='',
        birthday='',
        age='',
        height='',
        bust='',
        cup='',
        measurements_raw='',
        waist='',
        hip='',
        error='',
    ):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return 0

        normalized_person_id = str(person_id or '').strip()
        normalized_birthday = normalize_actor_birthday_for_storage(birthday)
        normalized_age = str(age or '').strip()
        normalized_height = str(height or '').strip()
        normalized_bust = str(bust or '').strip()
        normalized_cup = str(cup or '').strip().upper()
        normalized_measurements_raw = str(measurements_raw or '').strip()
        normalized_waist = str(waist or '').strip()
        normalized_hip = str(hip or '').strip()
        normalized_error = str(error or '').strip()
        normalized_status = str(status or '').strip() or UNENRICHED_STATUS

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO actor_enrichments (actor_name)
                VALUES (?)
                ''',
                (normalized_name,),
            )
            cursor.execute(
                '''
                UPDATE actor_enrichments
                SET binghuo_person_id = COALESCE(NULLIF(?, ''), binghuo_person_id),
                    binghuo_enrichment_status = ?,
                    binghuo_last_error = ?,
                    binghuo_last_enriched_at = CURRENT_TIMESTAMP,
                    binghuo_birthday = COALESCE(NULLIF(?, ''), binghuo_birthday),
                    binghuo_age = COALESCE(NULLIF(?, ''), binghuo_age),
                    binghuo_height = COALESCE(NULLIF(?, ''), binghuo_height),
                    binghuo_bust = COALESCE(NULLIF(?, ''), binghuo_bust),
                    binghuo_cup = COALESCE(NULLIF(?, ''), binghuo_cup),
                    binghuo_measurements_raw = COALESCE(NULLIF(?, ''), binghuo_measurements_raw),
                    binghuo_waist = COALESCE(NULLIF(?, ''), binghuo_waist),
                    binghuo_hip = COALESCE(NULLIF(?, ''), binghuo_hip)
                WHERE actor_name = ?
                ''',
                (
                    normalized_person_id,
                    normalized_status,
                    normalized_error,
                    normalized_birthday,
                    normalized_age,
                    normalized_height,
                    normalized_bust,
                    normalized_cup,
                    normalized_measurements_raw,
                    normalized_waist,
                    normalized_hip,
                    normalized_name,
                ),
            )
            cursor.execute(
                '''
                UPDATE actors
                SET birthday = COALESCE(NULLIF(?, ''), birthday),
                    age = COALESCE(NULLIF(?, ''), age)
                WHERE name = ?
                ''',
                (
                    normalized_birthday,
                    normalized_age,
                    normalized_name,
                ),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def save_baomu_actor_profile(
        self,
        actor_name,
        status,
        birthday='',
        height='',
        bust='',
        cup='',
        measurements_raw='',
        waist='',
        hip='',
        error='',
    ):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return 0

        normalized_birthday = normalize_actor_birthday_for_storage(birthday)
        normalized_height = str(height or '').strip()
        normalized_bust = str(bust or '').strip()
        normalized_cup = str(cup or '').strip().upper()
        normalized_measurements_raw = str(measurements_raw or '').strip()
        normalized_waist = str(waist or '').strip()
        normalized_hip = str(hip or '').strip()
        normalized_error = str(error or '').strip()
        normalized_status = str(status or '').strip() or UNENRICHED_STATUS

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO actor_enrichments (actor_name)
                VALUES (?)
                ''',
                (normalized_name,),
            )
            cursor.execute(
                '''
                UPDATE actor_enrichments
                SET baomu_enrichment_status = ?,
                    baomu_last_error = ?,
                    baomu_last_enriched_at = CURRENT_TIMESTAMP,
                    baomu_birthday = COALESCE(NULLIF(?, ''), baomu_birthday),
                    baomu_height = COALESCE(NULLIF(?, ''), baomu_height),
                    baomu_bust = COALESCE(NULLIF(?, ''), baomu_bust),
                    baomu_cup = COALESCE(NULLIF(?, ''), baomu_cup),
                    baomu_measurements_raw = COALESCE(NULLIF(?, ''), baomu_measurements_raw),
                    baomu_waist = COALESCE(NULLIF(?, ''), baomu_waist),
                    baomu_hip = COALESCE(NULLIF(?, ''), baomu_hip)
                WHERE actor_name = ?
                ''',
                (
                    normalized_status,
                    normalized_error,
                    normalized_birthday,
                    normalized_height,
                    normalized_bust,
                    normalized_cup,
                    normalized_measurements_raw,
                    normalized_waist,
                    normalized_hip,
                    normalized_name,
                ),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            if normalized_movies:
                values = []
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
                    values.append(
                        (
                            normalized_name,
                            normalized_code,
                            movie.get('title', ''),
                            author,
                            javtxt_release_date or movie.get('release_date', ''),
                            movie.get('avfan_url', ''),
                            int(movie.get('page_number', 1) or 1),
                            javtxt_status,
                            javtxt_movie_id,
                            javtxt_url,
                            javtxt_tags,
                            javtxt_release_date,
                            author_raw,
                            video_category,
                            str(existing_movie.get('supplement_enrichment_status', '') or '').strip() or UNENRICHED_STATUS,
                            str(existing_movie.get('supplement_enrichment_error', '') or '').strip(),
                            str(existing_movie.get('supplement_enriched_at', '') or '').strip(),
                        )
                    )
                cursor.executemany('''
                    INSERT OR REPLACE INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category,
                        supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values)
                self._propagate_web_movie_javtxt_state_for_codes(
                    cursor,
                    [movie['code'] for movie in normalized_movies],
                )
            conn.commit()
        self.refresh_actor_javtxt_statuses([normalized_name])

    def get_actor_enrichment_record(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        records = self.list_actor_enrichment_records()
        return records.get(normalized_name, {
            'actor_name': normalized_name,
            'actor_id': '',
            'enrichment_status': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'last_error': '',
            'last_enriched_at': '',
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'avfan_last_error': '',
            'avfan_last_enriched_at': '',
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'javtxt_total_videos': 0,
            'javtxt_last_error': '',
            'javtxt_last_enriched_at': '',
            'binghuo_person_id': '',
            'binghuo_enrichment_status': UNENRICHED_STATUS,
            'binghuo_last_error': '',
            'binghuo_last_enriched_at': '',
            'binghuo_birthday': '',
            'binghuo_age': '',
            'binghuo_height': '',
            'binghuo_bust': '',
            'binghuo_cup': '',
            'binghuo_measurements_raw': '',
            'binghuo_waist': '',
            'binghuo_hip': '',
            'baomu_enrichment_status': UNENRICHED_STATUS,
            'baomu_last_error': '',
            'baomu_last_enriched_at': '',
            'baomu_birthday': '',
            'baomu_height': '',
            'baomu_bust': '',
            'baomu_cup': '',
            'baomu_measurements_raw': '',
            'baomu_waist': '',
            'baomu_hip': '',
        })

    def list_actor_movies(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM actor_movies
                WHERE actor_name = ?
                ORDER BY release_date DESC, code DESC
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

    def list_all_actor_movies(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM actor_movies
                ORDER BY actor_name, release_date DESC, code DESC
                '''
            )

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

    def list_actor_movies_by_names(self, actor_names):
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category, supplement_enrichment_status
                FROM actor_movies
                WHERE actor_name IN ({placeholders})
                ORDER BY actor_name, release_date DESC, code DESC
                ''',
                normalized_names,
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

        return results

    def list_latest_actor_movie_release_dates_by_names(self, actor_names, filter_settings=None):
        normalized_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_names.append(normalized_name)

        if not normalized_names:
            return {}

        placeholders = ','.join('?' for _ in normalized_names)
        release_date_sql = "COALESCE(NULLIF(javtxt_release_date, ''), NULLIF(release_date, ''), '')"
        tracked_categories = (VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_CO_STAR)
        filter_sql, filter_params = self._actor_movie_update_status_filter_sql(filter_settings)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT actor_name, MAX({release_date_sql}) AS latest_release_date
                FROM actor_movies
                WHERE actor_name IN ({placeholders})
                  AND code LIKE '%-%'
                  AND video_category IN (?, ?)
                  AND {release_date_sql} >= ?
                  {filter_sql}
                GROUP BY actor_name
                ''',
                [
                    *normalized_names,
                    *tracked_categories,
                    JAVTXT_AUTHOR_MIN_RELEASE_DATE.isoformat(),
                    *filter_params,
                ],
            )
            return {
                str(row[0] or '').strip(): str(row[1] or '').strip()
                for row in cursor.fetchall()
                if str(row[0] or '').strip() and str(row[1] or '').strip()
            }

    @classmethod
    def _actor_movie_update_status_filter_sql(cls, filter_settings=None):
        if not isinstance(filter_settings, dict):
            return '', []
        rules = filter_settings.get('rules', filter_settings)
        if not isinstance(rules, dict):
            return '', []

        clauses = []
        params = []
        prefix_expression = cls._code_prefix_expression_sql('code')
        for field_name in ('code', 'co_star_code'):
            for prefix in cls._normalized_filter_values(rules.get(field_name, [])):
                clauses.append(f'{prefix_expression} != ?')
                params.append(prefix.upper())

        for field_name, column_name in (('title', 'title'), ('javtxt_tags', 'javtxt_tags')):
            for keyword in cls._normalized_filter_values(rules.get(field_name, [])):
                clauses.append(f"COALESCE({column_name}, '') NOT LIKE ?")
                params.append(f'%{keyword}%')

        if not clauses:
            return '', []
        return 'AND ' + ' AND '.join(clauses), params

    @staticmethod
    def _normalized_filter_values(values):
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple, set)):
            return []
        normalized_values = []
        seen = set()
        for value in values:
            normalized_value = str(value or '').strip()
            lowered_value = normalized_value.lower()
            if not normalized_value or lowered_value in seen:
                continue
            seen.add(lowered_value)
            normalized_values.append(normalized_value)
        return normalized_values

    def reset_video_enrichments(self, codes):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
        ]
        if not normalized_codes:
            return 0

        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE processed_videos
                SET avfan_movie_id = '',
                    release_date = '',
                    maker = '',
                    publisher = '',
                    enrichment_status = ?,
                    enrichment_error = '',
                    enriched_at = NULL
                WHERE code IN ({placeholders})
            ''', [UNENRICHED_STATUS, *normalized_codes])
            conn.commit()
            return int(cursor.rowcount or 0)

    def reset_actor_enrichments(self, actor_names, source_key=None):
        normalized_names = [
            str(actor_name or '').strip()
            for actor_name in (actor_names or [])
            if str(actor_name or '').strip()
        ]
        if not normalized_names:
            return 0

        normalized_source = normalize_video_enrichment_source(source_key)
        placeholders = ','.join('?' for _ in normalized_names)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                status_column, error_column, at_column = self._library_source_columns(normalized_source)
                cursor.execute(
                    f'''
                    UPDATE actor_movies
                    SET author = '',
                        author_raw = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL,
                        javtxt_enrichment_status = ?,
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_tags = '',
                        video_category = ''
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, UNENRICHED_STATUS, *normalized_names],
                )
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = 0,
                        {error_column} = '',
                        {at_column} = NULL
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
                for actor_name in normalized_names:
                    self._refresh_actor_combined_status(cursor, actor_name)
            elif normalized_source == BINGHUO_ACTOR_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET binghuo_person_id = '',
                        binghuo_enrichment_status = ?,
                        binghuo_last_error = '',
                        binghuo_last_enriched_at = NULL,
                        binghuo_birthday = '',
                        binghuo_age = '',
                        binghuo_height = '',
                        binghuo_bust = '',
                        binghuo_cup = '',
                        binghuo_measurements_raw = '',
                        binghuo_waist = '',
                        binghuo_hip = ''
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
                for actor_name in normalized_names:
                    self._refresh_actor_combined_status(cursor, actor_name)
            elif normalized_source == BAOMU_ACTOR_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET baomu_enrichment_status = ?,
                        baomu_last_error = '',
                        baomu_last_enriched_at = NULL
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
                for actor_name in normalized_names:
                    self._refresh_actor_combined_status(cursor, actor_name)
            elif normalized_source == SUPPLEMENT_TASK_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE actor_movies
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
            else:
                cursor.execute(f'''
                    DELETE FROM actor_movies
                    WHERE actor_name IN ({placeholders})
                ''', normalized_names)
                cursor.execute(f'''
                    DELETE FROM actor_enrichments
                    WHERE actor_name IN ({placeholders})
                ''', normalized_names)
            conn.commit()
            return len(normalized_names)

    def rename_actor(self, old_name, new_name, birthday='', age='', author_updates=None):
        normalized_old_name = str(old_name or '').strip()
        normalized_new_name = str(new_name or '').strip()
        normalized_birthday = str(birthday or '').strip()
        normalized_age = str(age or '').strip()
        updates = list(author_updates or [])
        if not normalized_old_name or not normalized_new_name:
            raise ValueError('演员名称不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM actors WHERE name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 已存在')

            cursor.execute('SELECT 1 FROM actor_enrichments WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的补全记录已存在')

            cursor.execute('SELECT 1 FROM actor_movies WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的作品记录已存在')

            cursor.execute(
                'UPDATE actors SET name = ?, birthday = ?, age = ? WHERE name = ?',
                (normalized_new_name, normalized_birthday, normalized_age, normalized_old_name),
            )
            updated_actor_count = int(cursor.rowcount or 0)

            cursor.execute(
                'UPDATE actor_enrichments SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )
            cursor.execute(
                'UPDATE actor_movies SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )

            for update in updates:
                code = standardize_video_code(update.get('code', ''))
                author = str(update.get('author', '')).strip()
                if not code:
                    continue
                cursor.execute(
                    'UPDATE processed_videos SET author = ? WHERE code = ?',
                    (author, code),
                )

            conn.commit()
            return updated_actor_count

    def delete_actor(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            raise ValueError('演员名称不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            cursor.execute('DELETE FROM actor_enrichments WHERE actor_name = ?', (normalized_name,))
            cursor.execute('DELETE FROM actors WHERE name = ?', (normalized_name,))
            cursor.execute(
                'INSERT OR IGNORE INTO hidden_actors (name) VALUES (?)',
                (normalized_name,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        normalized_prefixes = [
            str(prefix or '').strip().upper()
            for prefix in (prefixes or [])
            if str(prefix or '').strip()
        ]
        if not normalized_prefixes:
            return 0

        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        placeholders = ','.join('?' for _ in normalized_prefixes)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                status_column, error_column, at_column = self._library_source_columns(normalized_source)
                cursor.execute(
                    f'''
                    UPDATE code_prefix_movies
                    SET author = '',
                        author_raw = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL,
                        javtxt_enrichment_status = ?,
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_tags = '',
                        video_category = ''
                    WHERE prefix IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, UNENRICHED_STATUS, *normalized_prefixes],
                )
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = 0,
                        {error_column} = '',
                        {at_column} = NULL
                    WHERE prefix IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_prefixes],
                )
                for prefix in normalized_prefixes:
                    self._refresh_code_prefix_combined_status(cursor, prefix)
            elif normalized_source == SUPPLEMENT_TASK_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE code_prefix_movies
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL
                    WHERE prefix IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_prefixes],
                )
            else:
                cursor.execute(f'''
                    DELETE FROM code_prefix_movies
                    WHERE prefix IN ({placeholders})
                ''', normalized_prefixes)
                cursor.execute(f'''
                    DELETE FROM code_prefix_enrichments
                    WHERE prefix IN ({placeholders})
                ''', normalized_prefixes)
            conn.commit()
            return len(normalized_prefixes)

    def rename_code_prefix(self, old_prefix, new_prefix, code_updates=None, web_movie_updates=None):
        normalized_old_prefix = str(old_prefix or '').strip().upper()
        normalized_new_prefix = str(new_prefix or '').strip().upper()
        normalized_code_updates = [
            (
                standardize_video_code(old_code),
                standardize_video_code(new_code),
            )
            for old_code, new_code in (code_updates or [])
            if standardize_video_code(old_code) and standardize_video_code(new_code)
        ]
        normalized_web_movie_updates = [
            (
                standardize_video_code(old_code),
                standardize_video_code(new_code),
            )
            for old_code, new_code in (web_movie_updates or [])
            if standardize_video_code(old_code) and standardize_video_code(new_code)
        ]

        if not normalized_old_prefix or not normalized_new_prefix:
            raise ValueError('番号前缀不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()

            if normalized_old_prefix != normalized_new_prefix:
                cursor.execute('SELECT 1 FROM code_prefix_enrichments WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在补全记录')

                cursor.execute('SELECT 1 FROM code_prefix_movies WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在网页作品记录')

                cursor.execute('SELECT 1 FROM hidden_code_prefixes WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已被删除，请换一个前缀名称')

            if normalized_code_updates:
                old_codes = [item[0] for item in normalized_code_updates]
                new_codes = [item[1] for item in normalized_code_updates]
                if len(set(new_codes)) != len(new_codes):
                    raise ValueError('新番号中存在重复值，无法修改前缀')

                new_placeholders = ','.join('?' for _ in new_codes)
                old_placeholders = ','.join('?' for _ in old_codes)
                cursor.execute(
                    f'''
                    SELECT code
                    FROM processed_videos
                    WHERE code IN ({new_placeholders})
                      AND code NOT IN ({old_placeholders})
                    ''',
                    [*new_codes, *old_codes],
                )
                collision_rows = [row[0] for row in cursor.fetchall() if row[0]]
                if collision_rows:
                    raise ValueError(f'目标番号已存在：{collision_rows[0]}')

            for old_code, new_code in normalized_code_updates:
                cursor.execute(
                    'UPDATE processed_videos SET code = ? WHERE code = ?',
                    (new_code, old_code),
                )

            for old_code, new_code in normalized_web_movie_updates:
                cursor.execute(
                    '''
                    UPDATE code_prefix_movies
                    SET prefix = ?, code = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                )

            if not normalized_web_movie_updates:
                cursor.execute(
                    'UPDATE code_prefix_movies SET prefix = ? WHERE prefix = ?',
                    (normalized_new_prefix, normalized_old_prefix),
                )

            cursor.execute(
                'UPDATE code_prefix_enrichments SET prefix = ? WHERE prefix = ?',
                (normalized_new_prefix, normalized_old_prefix),
            )
            cursor.execute(
                'UPDATE hidden_code_prefixes SET prefix = ? WHERE prefix = ?',
                (normalized_new_prefix, normalized_old_prefix),
            )
            conn.commit()
            return len(normalized_code_updates)

    def delete_code_prefix(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            raise ValueError('番号前缀不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO hidden_code_prefixes (prefix) VALUES (?)',
                (normalized_prefix,),
            )
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (normalized_prefix,))
            cursor.execute('DELETE FROM code_prefix_enrichments WHERE prefix = ?', (normalized_prefix,))
            conn.commit()
            return 1

    def get_path_by_value(self, folder_path):
        with self._connect() as conn:
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

    def sync_usb_video_inventory(self, folder_path, scanned_videos, storage_info=None):
        normalized_path = str(Path(folder_path).expanduser())
        storage_info = storage_info or {}
        current_total_bytes = int(storage_info.get('total_bytes') or 0)
        current_used_bytes = int(storage_info.get('used_bytes') or 0)
        current_free_bytes = int(storage_info.get('free_bytes') or 0)
        current_capacity_mb = round(current_free_bytes / (1024 * 1024), 2) if current_free_bytes else 0

        current_rows = {}
        for video in scanned_videos or []:
            code = standardize_video_code((video or {}).get('code', ''))
            if not code:
                continue
            file_path = str((video or {}).get('file_path', '') or '')
            current_rows[code] = {
                'video_code': code,
                'file_path': file_path,
                'file_name': Path(file_path).name if file_path else '',
                'size_on_disk': str((video or {}).get('size_on_disk', '') or ''),
                'size_bytes': int((video or {}).get('size_bytes', 0) or 0),
            }

        with self._connect() as conn:
            cursor = conn.cursor()
            previous_rows = self._load_usb_video_inventory_rows(cursor, normalized_path)
            previous_state = self._load_usb_video_scan_state(cursor, normalized_path)
            previous_free_bytes = int((previous_state or {}).get('last_free_bytes') or 0)
            capacity_delta_bytes = current_free_bytes - previous_free_bytes if previous_state else 0
            capacity_delta_mb = round(capacity_delta_bytes / (1024 * 1024), 2)
            is_first_scan = previous_state is None and not previous_rows

            change_logs = []
            if not is_first_scan:
                previous_codes = set(previous_rows)
                current_codes = set(current_rows)

                for code in sorted(previous_codes - current_codes):
                    previous = previous_rows[code]
                    change_logs.append(
                        self._build_usb_video_change_log(
                            normalized_path,
                            code,
                            'deleted',
                            previous,
                            {},
                            previous_free_bytes,
                            current_free_bytes,
                            capacity_delta_bytes,
                            capacity_delta_mb,
                            current_capacity_mb,
                        )
                    )

                for code in sorted(current_codes - previous_codes):
                    current = current_rows[code]
                    change_logs.append(
                        self._build_usb_video_change_log(
                            normalized_path,
                            code,
                            'added',
                            {},
                            current,
                            previous_free_bytes,
                            current_free_bytes,
                            capacity_delta_bytes,
                            capacity_delta_mb,
                            current_capacity_mb,
                        )
                    )

                for code in sorted(previous_codes & current_codes):
                    previous = previous_rows[code]
                    current = current_rows[code]
                    if previous.get('file_path') != current.get('file_path') or previous.get('size_on_disk') != current.get('size_on_disk'):
                        change_logs.append(
                            self._build_usb_video_change_log(
                                normalized_path,
                                code,
                                'updated',
                                previous,
                                current,
                                previous_free_bytes,
                                current_free_bytes,
                                capacity_delta_bytes,
                                capacity_delta_mb,
                                current_capacity_mb,
                            )
                        )

            self._replace_usb_video_inventory(cursor, normalized_path, current_rows.values())
            self._upsert_usb_video_scan_state(
                cursor,
                normalized_path,
                current_total_bytes,
                current_used_bytes,
                current_free_bytes,
            )
            self._insert_usb_video_change_logs(cursor, change_logs)
            conn.commit()

        return {
            'folder_path': normalized_path,
            'inventory_count': len(current_rows),
            'change_count': len(change_logs),
            'capacity_delta_mb': capacity_delta_mb,
            'current_capacity_mb': current_capacity_mb,
        }

    def get_usb_video_inventory(self, folder_path):
        normalized_path = str(Path(folder_path).expanduser())
        with self._connect() as conn:
            return list(self._load_usb_video_inventory_rows(conn.cursor(), normalized_path).values())

    def list_usb_video_change_logs(self, folder_path=None, limit=200):
        normalized_path = str(Path(folder_path).expanduser()) if folder_path else ''
        normalized_limit = max(1, int(limit or 200))
        with self._connect() as conn:
            cursor = conn.cursor()
            params = []
            where_sql = ''
            if normalized_path:
                where_sql = 'WHERE folder_path = ?'
                params.append(normalized_path)
            params.append(normalized_limit)
            cursor.execute(
                f'''
                SELECT id, folder_path, video_code, change_type, previous_file_path,
                       current_file_path, previous_size_on_disk, current_size_on_disk,
                       previous_free_bytes, current_free_bytes, capacity_delta_bytes,
                       capacity_delta_mb, current_capacity_mb, message, created_at
                FROM usb_video_change_logs
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                ''',
                params,
            )
            return [
                {
                    'id': row[0],
                    'folder_path': row[1] or '',
                    'video_code': row[2] or '',
                    'change_type': row[3] or '',
                    'previous_file_path': row[4] or '',
                    'current_file_path': row[5] or '',
                    'previous_size_on_disk': row[6] or '',
                    'current_size_on_disk': row[7] or '',
                    'previous_free_bytes': row[8] or 0,
                    'current_free_bytes': row[9] or 0,
                    'capacity_delta_bytes': row[10] or 0,
                    'capacity_delta_mb': row[11] or 0,
                    'current_capacity_mb': row[12] or 0,
                    'message': row[13] or '',
                    'created_at': row[14] or '',
                }
                for row in cursor.fetchall()
            ]

    @staticmethod
    def _load_usb_video_inventory_rows(cursor, folder_path):
        cursor.execute(
            '''
            SELECT video_code, file_path, file_name, size_on_disk, size_bytes
            FROM usb_video_inventory
            WHERE folder_path = ?
            ''',
            (folder_path,),
        )
        return {
            row[0]: {
                'video_code': row[0] or '',
                'file_path': row[1] or '',
                'file_name': row[2] or '',
                'size_on_disk': row[3] or '',
                'size_bytes': row[4] or 0,
            }
            for row in cursor.fetchall()
            if row[0]
        }

    @staticmethod
    def _load_usb_video_scan_state(cursor, folder_path):
        cursor.execute(
            '''
            SELECT last_total_bytes, last_used_bytes, last_free_bytes, last_scan_at
            FROM usb_video_scan_states
            WHERE folder_path = ?
            ''',
            (folder_path,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'last_total_bytes': row[0] or 0,
            'last_used_bytes': row[1] or 0,
            'last_free_bytes': row[2] or 0,
            'last_scan_at': row[3] or '',
        }

    @staticmethod
    def _replace_usb_video_inventory(cursor, folder_path, rows):
        cursor.execute('DELETE FROM usb_video_inventory WHERE folder_path = ?', (folder_path,))
        cursor.executemany(
            '''
            INSERT INTO usb_video_inventory (
                folder_path, video_code, file_path, file_name, size_on_disk, size_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            [
                (
                    folder_path,
                    row.get('video_code', ''),
                    row.get('file_path', ''),
                    row.get('file_name', ''),
                    row.get('size_on_disk', ''),
                    row.get('size_bytes', 0),
                )
                for row in rows
            ],
        )

    @staticmethod
    def _upsert_usb_video_scan_state(cursor, folder_path, total_bytes, used_bytes, free_bytes):
        cursor.execute(
            '''
            INSERT INTO usb_video_scan_states (
                folder_path, last_total_bytes, last_used_bytes, last_free_bytes, last_scan_at
            )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(folder_path) DO UPDATE SET
                last_total_bytes = excluded.last_total_bytes,
                last_used_bytes = excluded.last_used_bytes,
                last_free_bytes = excluded.last_free_bytes,
                last_scan_at = CURRENT_TIMESTAMP
            ''',
            (folder_path, total_bytes, used_bytes, free_bytes),
        )

    @classmethod
    def _build_usb_video_change_log(
        cls,
        folder_path,
        code,
        change_type,
        previous,
        current,
        previous_free_bytes,
        current_free_bytes,
        capacity_delta_bytes,
        capacity_delta_mb,
        current_capacity_mb,
    ):
        return {
            'folder_path': folder_path,
            'video_code': code,
            'change_type': change_type,
            'previous_file_path': previous.get('file_path', ''),
            'current_file_path': current.get('file_path', ''),
            'previous_size_on_disk': previous.get('size_on_disk', ''),
            'current_size_on_disk': current.get('size_on_disk', ''),
            'previous_free_bytes': previous_free_bytes,
            'current_free_bytes': current_free_bytes,
            'capacity_delta_bytes': capacity_delta_bytes,
            'capacity_delta_mb': capacity_delta_mb,
            'current_capacity_mb': current_capacity_mb,
            'message': cls._format_usb_video_change_message(code, change_type, capacity_delta_mb, current_capacity_mb),
        }

    @staticmethod
    def _format_usb_video_change_message(code, change_type, capacity_delta_mb, current_capacity_mb):
        action_text = {
            'added': '新增',
            'deleted': '删除',
            'updated': '更新',
        }.get(change_type, change_type)
        delta_text = '增加' if capacity_delta_mb >= 0 else '减少'
        return f'视频编号{code}{action_text}，U盘容量{delta_text}{abs(capacity_delta_mb):.0f}MB，当前可用容量为{current_capacity_mb:.0f}MB'

    @staticmethod
    def _insert_usb_video_change_logs(cursor, logs):
        cursor.executemany(
            '''
            INSERT INTO usb_video_change_logs (
                folder_path, video_code, change_type, previous_file_path, current_file_path,
                previous_size_on_disk, current_size_on_disk, previous_free_bytes,
                current_free_bytes, capacity_delta_bytes, capacity_delta_mb,
                current_capacity_mb, message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            [
                (
                    log['folder_path'],
                    log['video_code'],
                    log['change_type'],
                    log['previous_file_path'],
                    log['current_file_path'],
                    log['previous_size_on_disk'],
                    log['current_size_on_disk'],
                    log['previous_free_bytes'],
                    log['current_free_bytes'],
                    log['capacity_delta_bytes'],
                    log['capacity_delta_mb'],
                    log['current_capacity_mb'],
                    log['message'],
                )
                for log in logs
            ],
        )

    @staticmethod
    def _build_processed_video_row(row):
        return {
            'code': row[0] or '',
            'title': row[1] or '',
            'author': sanitize_actor_text(row[2] or ''),
            'duration': row[3] or '',
            'size': row[4] or '',
            'storage_location': row[5] or '',
            'avfan_movie_id': row[6] or '',
            'javtxt_movie_id': row[7] or '',
            'javtxt_url': row[8] or '',
            'javtxt_title': row[9] or '',
            'javtxt_actors': sanitize_actor_text(row[10] or ''),
            'javtxt_tags': row[11] or '',
            'video_category': normalize_video_category(row[12]),
            'release_date': row[13] or '',
            'maker': row[14] or '',
            'publisher': row[15] or '',
            'avfan_enrichment_status': row[16] or UNENRICHED_STATUS,
            'javtxt_enrichment_status': row[17] or UNENRICHED_STATUS,
            'enrichment_status': build_video_enrichment_status_text(row[16], row[17]),
        }

    @staticmethod
    def _normalize_list_sort_order(sort_order):
        return 'DESC' if str(sort_order or '').strip().lower() == 'desc' else 'ASC'

    @classmethod
    def _video_order_by_sql(cls, sort_field='code', sort_order='asc'):
        direction = cls._normalize_list_sort_order(sort_order)
        code_prefix_sql = "UPPER(CASE WHEN instr(code, '-') > 0 THEN substr(code, 1, instr(code, '-') - 1) ELSE code END)"
        code_number_sql = "CAST(CASE WHEN instr(code, '-') > 0 THEN substr(code, instr(code, '-') + 1) ELSE '0' END AS INTEGER)"
        duration_seconds_sql = (
            "CASE WHEN duration GLOB '*:*:*' THEN "
            "(CAST(substr(duration, 1, instr(duration, ':') - 1) AS INTEGER) * 3600) + "
            "(CAST(substr(substr(duration, instr(duration, ':') + 1), 1, instr(substr(duration, instr(duration, ':') + 1), ':') - 1) AS INTEGER) * 60) + "
            "(CAST(substr(substr(duration, instr(duration, ':') + 1), instr(substr(duration, instr(duration, ':') + 1), ':') + 1) AS INTEGER)) "
            "ELSE 0 END"
        )
        order_sql_map = {
            'code': f'{code_prefix_sql} {direction}, {code_number_sql} {direction}, UPPER(code) {direction}',
            'video_category': f'UPPER(COALESCE(video_category, \'\')) {direction}, {code_prefix_sql} {direction}, {code_number_sql} {direction}',
            'duration': f'{duration_seconds_sql} {direction}, {code_prefix_sql} {direction}, {code_number_sql} {direction}',
            'size': f'CAST(COALESCE(NULLIF(size, \'\'), \'0\') AS REAL) {direction}, {code_prefix_sql} {direction}, {code_number_sql} {direction}',
            'release_date': f'COALESCE(NULLIF(release_date, \'\'), \'\') {direction}, {code_prefix_sql} {direction}, {code_number_sql} {direction}',
        }
        return order_sql_map.get(str(sort_field or '').strip(), order_sql_map['code'])

    @classmethod
    def _video_search_where_sql(cls, search_text=''):
        normalized_search = str(search_text or '').strip()
        if not normalized_search:
            return '', ()
        like_value = f'%{normalized_search}%'
        return (
            '''
            WHERE code LIKE ? OR title LIKE ? OR author LIKE ? OR storage_location LIKE ?
               OR avfan_movie_id LIKE ? OR javtxt_movie_id LIKE ? OR javtxt_title LIKE ? OR javtxt_actors LIKE ?
               OR video_category LIKE ?
               OR release_date LIKE ? OR maker LIKE ? OR publisher LIKE ?
               OR avfan_enrichment_status LIKE ? OR javtxt_enrichment_status LIKE ?
            ''',
            (
                like_value, like_value, like_value, like_value,
                like_value, like_value, like_value, like_value,
                like_value, like_value, like_value, like_value,
                like_value, like_value,
            ),
        )

    @staticmethod
    def _normalize_limit_offset(limit=None, offset=0):
        normalized_limit = None if limit is None else max(int(limit or 0), 0)
        if normalized_limit == 0:
            normalized_limit = None
        normalized_offset = max(int(offset or 0), 0)
        return normalized_limit, normalized_offset

    def _fetch_processed_video_rows(
        self,
        where_sql='',
        parameters=None,
        order_by_sql='UPPER(code)',
        limit=None,
        offset=0,
        refresh_categories=True,
    ):
        if refresh_categories:
            self.refresh_video_categories_from_filter_rules()
        parameters = tuple(parameters or ())
        normalized_limit, normalized_offset = self._normalize_limit_offset(limit, offset)
        limit_sql = ''
        query_parameters = list(parameters)
        if normalized_limit is not None:
            limit_sql = ' LIMIT ? OFFSET ?'
            query_parameters.extend([normalized_limit, normalized_offset])
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, title, author, duration, size, storage_location,
                       avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_tags,
                       video_category,
                       release_date, maker, publisher,
                       avfan_enrichment_status, javtxt_enrichment_status
                FROM processed_videos
                {where_sql}
                ORDER BY {order_by_sql}
                {limit_sql}
                ''',
                tuple(query_parameters),
            )
            rows = cursor.fetchall()
        return [self._build_processed_video_row(row) for row in rows]

    def list_videos(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        where_sql, parameters = self._video_search_where_sql(search_text)
        return self._fetch_processed_video_rows(
            where_sql,
            parameters,
            order_by_sql=self._video_order_by_sql(sort_field, sort_order),
            limit=limit,
            offset=offset,
            refresh_categories=False,
        )

    def count_videos(self, search_text=''):
        where_sql, parameters = self._video_search_where_sql(search_text)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM processed_videos
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

    def list_video_summary_rows(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT code, title, release_date,
                       avfan_enrichment_status, javtxt_enrichment_status,
                       javtxt_movie_id, javtxt_url, javtxt_title, avfan_movie_id,
                       javtxt_actors, javtxt_actors_raw, javtxt_tags, javtxt_release_date, author,
                       supplement_enrichment_status
                FROM processed_videos
                ORDER BY code
                '''
            )
            rows = cursor.fetchall()

        return [
            {
                'code': row[0] or '',
                'title': row[1] or '',
                'release_date': row[2] or '',
                'avfan_enrichment_status': row[3] or UNENRICHED_STATUS,
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_title': row[7] or '',
                'avfan_movie_id': row[8] or '',
                'author': sanitize_actor_text(row[9] or ''),
                'author_raw': self._normalize_actor_raw_text(row[10] or row[9] or ''),
                'javtxt_tags': row[11] or '',
                'javtxt_release_date': row[12] or '',
                'local_author': sanitize_actor_text(row[13] or ''),
                'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
            }
            for row in rows
        ]

    def list_videos_for_enrichment(self, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE, candidate_filter=None):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                pending_rows = []
                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    candidate = {
                        'code': record['code'],
                        'title': record['title'],
                        'author': record['local_author'] or record['author'],
                    }
                    if candidate_filter is not None and not candidate_filter(candidate):
                        continue
                    if candidate_filter is None:
                        search_state = classify_search_state(record, cached_row=record)
                        if not is_retryable_search_state(search_state):
                            continue
                    pending_rows.append(candidate)
                    if len(pending_rows) >= int(limit):
                        break
                return pending_rows
            else:
                if candidate_filter is not None:
                    where_sql = ''
                    sql_params = []
                    sql_limit = ''
                else:
                    where_sql = f'WHERE COALESCE({status_column}, ?) IN (?, ?)'
                    sql_params = [
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        FAILED_STATUS,
                    ]
                    sql_params.append(int(limit))
                    sql_limit = 'LIMIT ?'
                cursor.execute(
                    f'''
                    SELECT code, title, author
                    FROM processed_videos
                    {where_sql}
                    ORDER BY code
                    {sql_limit}
                    ''',
                    tuple(sql_params),
                )
            rows = [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]
            if candidate_filter is not None:
                rows = [row for row in rows if candidate_filter(row)][: int(limit)]
            return rows

    def list_video_supplement_candidates(self, limit):
        limit = max(int(limit or 0), 0)
        if limit <= 0:
            return []

        candidates = []
        filter_settings = load_video_filter_settings()
        with self._connect() as conn:
            cursor = conn.cursor()
            for record in self._list_processed_video_javtxt_records(cursor):
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
            cursor.execute(
                '''
                UPDATE processed_videos
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP
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
                UPDATE code_prefix_movies
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP
                WHERE prefix = ? AND code = ?
                ''',
                (normalized_status, normalized_error, normalized_prefix, normalized_code),
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
                UPDATE actor_movies
                SET supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = CURRENT_TIMESTAMP
                WHERE actor_name = ? AND code = ?
                ''',
                (normalized_status, normalized_error, normalized_name, normalized_code),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def _list_processed_video_javtxt_records(self, cursor):
        cursor.execute(
            '''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code) AS display_title,
                   author,
                   javtxt_actors,
                   javtxt_actors_raw,
                   javtxt_movie_id,
                   javtxt_url,
                   javtxt_enrichment_status,
                   avfan_movie_id,
                   release_date,
                   video_category,
                   javtxt_tags,
                   javtxt_release_date,
                   supplement_enrichment_status
            FROM processed_videos
            ORDER BY code
            '''
        )
        return [
            {
                'code': str(row[0] or '').strip().upper(),
                'title': row[1] or '',
                'author': sanitize_actor_text(row[3] or ''),
                'author_raw': self._normalize_actor_raw_text(row[4] or row[3] or ''),
                'local_author': sanitize_actor_text(row[2] or ''),
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                'avfan_movie_id': row[8] or '',
                'release_date': row[9] or '',
                'video_category': normalize_video_category(row[10]),
                'javtxt_tags': row[11] or '',
                'javtxt_release_date': row[12] or '',
                'supplement_enrichment_status': row[13] or UNENRICHED_STATUS,
            }
            for row in cursor.fetchall()
            if str(row[0] or '').strip()
        ]

    def _normalize_processed_video_javtxt_payload(self, info, status):
        payload = dict(info or {})
        normalized_status = str(status or ENRICHED_STATUS).strip() or ENRICHED_STATUS
        javtxt_movie_id = str(payload.get('javtxt_movie_id', '') or '').strip()
        javtxt_url = str(payload.get('javtxt_url', '') or '').strip()
        sanitized_author = sanitize_actor_text(payload.get('author', ''))
        sanitized_javtxt_actors = sanitize_actor_text(payload.get('javtxt_actors', ''))
        raw_javtxt_actors = self._normalize_actor_raw_text(
            payload.get('javtxt_actors_raw', payload.get('author_raw', payload.get('javtxt_actors', payload.get('author', ''))))
        )
        if normalized_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(payload):
            normalized_status = UNENRICHED_STATUS
            sanitized_author = ''
            sanitized_javtxt_actors = ''
            raw_javtxt_actors = ''
        return {
            'status': normalized_status,
            'javtxt_movie_id': javtxt_movie_id,
            'javtxt_url': javtxt_url,
            'sanitized_author': sanitized_author,
            'sanitized_javtxt_actors': sanitized_javtxt_actors,
            'raw_javtxt_actors': raw_javtxt_actors,
            'sanitized_javtxt_tags': str(payload.get('javtxt_tags', '') or '').strip(),
            'javtxt_description': str(payload.get('javtxt_description', payload.get('description', '')) or '').strip(),
            'title': str(payload.get('title', '') or '').strip(),
            'javtxt_title': str(payload.get('javtxt_title', '') or '').strip(),
            'release_date': str(payload.get('release_date', '') or '').strip(),
            'maker': join_values(payload.get('maker')),
            'publisher': join_values(payload.get('publisher')),
            'error': str(payload.get('error', '') or '').strip(),
        }

    def update_video_enrichment(self, code, info, status=ENRICHED_STATUS, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        status_column, error_column, at_column = self._video_source_columns(normalized_source)
        normalized_javtxt = self._normalize_processed_video_javtxt_payload(info, status)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                if not self._is_processed_video_javtxt_eligible(cursor, code, info):
                    self._update_processed_video_javtxt_metadata(cursor, code, info)
                    self._refresh_video_category(
                        cursor,
                        code,
                        tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                        actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                    )
                    self._mark_processed_video_javtxt_ineligible(
                        cursor,
                        code,
                        normalized_javtxt['status'],
                        normalized_javtxt['error'],
                    )
                    self._refresh_combined_video_status(
                        cursor,
                        code,
                        normalized_javtxt['error'] or JAVTXT_INELIGIBLE_ERROR,
                    )
                    self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
                    conn.commit()
                    self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])
                    return
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET javtxt_movie_id = ?,
                        javtxt_url = ?,
                        javtxt_title = ?,
                        javtxt_actors = ?,
                        javtxt_actors_raw = ?,
                        javtxt_tags = ?,
                        javtxt_description = ?,
                        title = COALESCE(NULLIF(?, ''), title),
                        author = ?,
                        release_date = COALESCE(NULLIF(?, ''), release_date),
                        javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                        maker = COALESCE(NULLIF(?, ''), maker),
                        publisher = COALESCE(NULLIF(?, ''), publisher),
                        {status_column} = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    (
                        normalized_javtxt['javtxt_movie_id'],
                        normalized_javtxt['javtxt_url'],
                        normalized_javtxt['javtxt_title'],
                        normalized_javtxt['sanitized_javtxt_actors'],
                        normalized_javtxt['raw_javtxt_actors'],
                        normalized_javtxt['sanitized_javtxt_tags'],
                        normalized_javtxt['javtxt_description'],
                        normalized_javtxt['title'],
                        normalized_javtxt['sanitized_author'],
                        normalized_javtxt['release_date'],
                        normalized_javtxt['release_date'],
                        normalized_javtxt['maker'],
                        normalized_javtxt['publisher'],
                        normalized_javtxt['status'],
                        normalized_javtxt['error'],
                        code,
                    ),
                )
                self._refresh_video_category(
                    cursor,
                    code,
                    tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                    actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
            else:
                avfan_title = str(info.get('title', '') or '').strip()
                avfan_author = sanitize_actor_text(' '.join(info.get('actors', []) or []) or info.get('author', ''))
                avfan_duration = str(info.get('duration', '') or '').strip()
                avfan_tags = ' '.join(str(item or '').strip() for item in (info.get('tags', []) or []) if str(item or '').strip())
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET title = COALESCE(NULLIF(?, ''), title),
                        author = COALESCE(NULLIF(?, ''), author),
                        duration = COALESCE(NULLIF(?, ''), duration),
                        javtxt_tags = COALESCE(NULLIF(javtxt_tags, ''), ?),
                        avfan_movie_id = ?,
                        avfan_actors = ?,
                        avfan_tags = ?,
                        release_date = ?,
                        maker = ?,
                        publisher = ?,
                        {status_column} = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    (
                        avfan_title,
                        avfan_author,
                        avfan_duration,
                        avfan_tags,
                        info.get('avfan_movie_id', ''),
                        avfan_author,
                        avfan_tags,
                        info.get('release_date', ''),
                        join_values(info.get('maker')),
                        join_values(info.get('publisher')),
                        status,
                        info.get('error', ''),
                        code,
                    ),
                )

            self._refresh_combined_video_status(cursor, code, normalized_javtxt['error'] if normalized_source == JAVTXT_VIDEO_SOURCE else info.get('error', ''))
            conn.commit()
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])

    def mark_video_no_search_results(
        self,
        code,
        error='未搜索到匹配影片',
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        status=NO_SEARCH_RESULTS_STATUS,
    ):
        self._update_video_source_status(code, source_key, status, error)

    def mark_video_enrichment_failed(self, code, error, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        self._update_video_source_status(code, source_key, FAILED_STATUS, error)

    def _update_video_source_status(self, code, source_key, status, error):
        status_column, error_column, at_column = self._video_source_columns(source_key)
        normalized_source = normalize_video_enrichment_source(source_key)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET {status_column} = ?,
                    {error_column} = ?,
                    {at_column} = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (status, error, code),
            )
            self._refresh_combined_video_status(cursor, code, error)
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
            conn.commit()
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])

    def _refresh_combined_video_status(self, cursor, code, error_message=''):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status
            FROM processed_videos
            WHERE code = ?
            ''',
            (code,),
        )
        row = cursor.fetchone() or (UNENRICHED_STATUS, UNENRICHED_STATUS)
        cursor.execute(
            '''
            UPDATE processed_videos
            SET enrichment_status = ?,
                enrichment_error = ?,
                enriched_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            (build_video_enrichment_status_text(row[0], row[1]), error_message, code),
        )

    def count_videos_by_enrichment_status(self, status, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        status_column, _, _ = self._video_source_columns(source_key)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE({status_column}, ?) = ?
                ''',
                (UNENRICHED_STATUS, status),
            )
            return int(cursor.fetchone()[0] or 0)

    def count_pending_video_enrichments(self, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE, candidate_filter=None):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                pending_count = 0
                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    search_state = classify_search_state(record, cached_row=record)
                    if is_retryable_search_state(search_state):
                        candidate = {
                            'code': record['code'],
                            'title': record['title'],
                            'author': record['local_author'] or record['author'],
                        }
                        if candidate_filter is not None and not candidate_filter(candidate):
                            continue
                        pending_count += 1
                return pending_count
            else:
                cursor.execute(
                    f'''
                    SELECT COUNT(*)
                    FROM processed_videos
                    WHERE COALESCE({status_column}, ?) IN (?, ?)
                    ''',
                    (
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        FAILED_STATUS,
                    ),
                )
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                total_count = 0
                enriched_count = 0
                completed_count = 0
                success_count = 0
                pending_count = 0
                failed_count = 0
                no_search_count = 0
                no_detail_count = 0

                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    total_count += 1
                    search_state = classify_search_state(record, cached_row=record)
                    if search_state == JAVTXT_SEARCH_STATE_NO_RESULT:
                        enriched_count += 1
                        completed_count += 1
                        if str(record.get('javtxt_enrichment_status', '') or '').strip() == NO_VIDEO_DETAIL_STATUS:
                            no_detail_count += 1
                        else:
                            no_search_count += 1
                    elif is_resolved_search_state(search_state):
                        enriched_count += 1
                        completed_count += 1
                        success_count += 1
                    elif search_state == JAVTXT_SEARCH_STATE_FAILED:
                        failed_count += 1
                    else:
                        pending_count += 1

                return {
                    'enriched_count': enriched_count,
                    'completed_count': completed_count,
                    'success_count': success_count,
                    'unenriched_count': pending_count,
                    'pending_count': pending_count,
                    'failed_count': failed_count,
                    'no_search_count': no_search_count,
                    'no_detail_count': no_detail_count,
                    'total_count': total_count,
                }
            else:
                cursor.execute(
                    f'''
                    SELECT
                        COUNT(*) AS total_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS success_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS failed_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS no_search_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS no_detail_count
                    FROM processed_videos
                    ''',
                    (
                        UNENRICHED_STATUS, ENRICHED_STATUS,
                        UNENRICHED_STATUS, FAILED_STATUS,
                        UNENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS,
                        UNENRICHED_STATUS, NO_VIDEO_DETAIL_STATUS,
                    ),
                )
            row = cursor.fetchone() or (0, 0, 0, 0, 0)

        total_count = int(row[0] or 0)
        success_count = int(row[1] or 0)
        failed_count = int(row[2] or 0)
        no_search_count = int(row[3] or 0)
        no_detail_count = int(row[4] or 0)
        enriched_count = success_count + no_search_count + no_detail_count
        unenriched_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'enriched_count': enriched_count,
            'completed_count': enriched_count,
            'success_count': success_count,
            'unenriched_count': unenriched_count,
            'pending_count': unenriched_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'total_count': total_count,
        }

    def reset_video_enrichments(self, codes, source_key=None):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
        ]
        if not normalized_codes:
            return 0

        normalized_source = normalize_video_enrichment_source(source_key)
        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_title = '',
                        javtxt_actors = '',
                        javtxt_tags = '',
                        video_category = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL,
                        javtxt_enrichment_status = ?,
                        javtxt_enrichment_error = '',
                        javtxt_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, UNENRICHED_STATUS, *normalized_codes],
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, normalized_codes)
            elif normalized_source == AVFAN_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET avfan_movie_id = '',
                        avfan_enrichment_status = ?,
                        avfan_enrichment_error = '',
                        avfan_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_codes],
                )
            elif normalized_source == SUPPLEMENT_TASK_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_codes],
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET avfan_movie_id = '',
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_title = '',
                        javtxt_actors = '',
                        javtxt_tags = '',
                        video_category = '',
                        release_date = '',
                        maker = '',
                        publisher = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = NULL,
                        enrichment_status = ?,
                        enrichment_error = '',
                        enriched_at = NULL,
                        avfan_enrichment_status = ?,
                        avfan_enrichment_error = '',
                        avfan_enriched_at = NULL,
                        javtxt_enrichment_status = ?,
                        javtxt_enrichment_error = '',
                        javtxt_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [
                        UNENRICHED_STATUS,
                        build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        *normalized_codes,
                    ],
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, normalized_codes)
            for code in normalized_codes:
                self._refresh_combined_video_status(cursor, code, '')
            conn.commit()
            return int(cursor.rowcount or 0)

    def get_video_count(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM processed_videos')
            return int(cursor.fetchone()[0] or 0)

    def get_actor_count(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM actors')
            return int(cursor.fetchone()[0] or 0)

    def get_videos_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, title, author, duration, size, storage_location, release_date, video_category,
                       javtxt_tags, javtxt_release_date, javtxt_enrichment_status, javtxt_movie_id, javtxt_url,
                       avfan_movie_id, maker, publisher
                FROM processed_videos
                WHERE code IN ({placeholders})
                ''',
                normalized_codes,
            )
            rows = cursor.fetchall()

        return {
            (row[0] or ''): {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'duration': row[3] or '',
                'size': row[4] or '',
                'storage_location': row[5] or '',
                'release_date': row[6] or '',
                'video_category': normalize_video_category(row[7]),
                'javtxt_tags': row[8] or '',
                'javtxt_release_date': row[9] or '',
                'javtxt_enrichment_status': row[10] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[11] or '',
                'javtxt_url': row[12] or '',
                'avfan_movie_id': row[13] or '',
                'maker': row[14] or '',
                'publisher': row[15] or '',
            }
            for row in rows
        }

    def list_masterpiece_entries(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT m.code,
                       COALESCE(NULLIF(m.display_title, ''), NULLIF(p.javtxt_title, ''), NULLIF(p.title, ''), m.code),
                       COALESCE(NULLIF(m.display_author, ''), NULLIF(p.javtxt_actors, ''), NULLIF(p.author, ''), ''),
                       COALESCE(NULLIF(m.primary_source, ''), CASE WHEN p.code IS NOT NULL THEN 'video_library' ELSE '' END),
                       COALESCE(NULLIF(m.primary_detail_url, ''), ''),
                       COALESCE(m.medal, ''),
                       COALESCE(m.created_at, ''),
                       COALESCE(m.updated_at, ''),
                       COALESCE(p.avfan_movie_id, ''),
                       COALESCE(p.javtxt_url, ''),
                       COALESCE(p.avfan_enrichment_status, ''),
                       COALESCE(p.javtxt_enrichment_status, '')
                FROM masterpiece_entries AS m
                LEFT JOIN processed_videos AS p
                    ON p.code = m.code
                ORDER BY COALESCE(m.created_at, '') ASC, UPPER(m.code) ASC
                '''
            )
            rows = cursor.fetchall()

        result = []
        for row in rows:
            medal_text = normalize_ladder_medal_text(row[5] or '')
            result.append(
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': sanitize_actor_text(row[2] or ''),
                    'display_title': row[1] or '',
                    'display_author': sanitize_actor_text(row[2] or ''),
                    'primary_source': row[3] or '',
                    'primary_detail_url': (row[4] or '') or self._build_movie_detail_url(
                        avfan_movie_id=row[8] or '',
                        javtxt_url=row[9] or '',
                    ),
                    'medal': medal_text,
                    'medals': split_ladder_medals(medal_text),
                    'created_at': row[6] or '',
                    'updated_at': row[7] or '',
                    'avfan_enrichment_status': row[10] or '',
                    'javtxt_enrichment_status': row[11] or '',
                }
            )
        return result

    def add_masterpiece_entry(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            raise ValueError('缺少视频编号')

        references = self._collect_masterpiece_references(normalized_code)
        if not references:
            raise ValueError(f'视频不存在: {normalized_code}')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO masterpiece_entries (code, medal)
                VALUES (?, '')
                ''',
                (normalized_code,),
            )
            cursor.execute(
                '''
                UPDATE masterpiece_entries
                SET updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_code,),
            )
            conn.commit()

        return self._get_masterpiece_entry(normalized_code)

    def update_masterpiece_entry_medal(self, code, medal):
        normalized_code = standardize_video_code(code)
        normalized_medal = normalize_ladder_medal_text(medal)
        if not normalized_code:
            raise ValueError('缺少视频编号')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE masterpiece_entries
                SET medal = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (normalized_medal, normalized_code),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f'名作堂条目不存在: {normalized_code}')
            conn.commit()

        return self._get_masterpiece_entry(normalized_code)

    def _get_masterpiece_entry(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return {}
        for row in self.list_masterpiece_entries():
            if str((row or {}).get('code', '') or '').strip() == normalized_code:
                return dict(row or {})
        return {}

    def list_masterpiece_entries(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT m.code,
                       COALESCE(NULLIF(m.display_title, ''), NULLIF(p.javtxt_title, ''), NULLIF(p.title, ''), m.code),
                       COALESCE(NULLIF(m.display_author, ''), NULLIF(p.javtxt_actors, ''), NULLIF(p.author, ''), ''),
                       COALESCE(NULLIF(m.primary_source, ''), CASE WHEN p.code IS NOT NULL THEN 'video_library' ELSE '' END),
                       COALESCE(NULLIF(m.primary_detail_url, ''), ''),
                       COALESCE(m.medal, ''),
                       COALESCE(m.created_at, ''),
                       COALESCE(m.updated_at, ''),
                       COALESCE(p.avfan_movie_id, ''),
                       COALESCE(p.javtxt_url, ''),
                       COALESCE(p.avfan_enrichment_status, ''),
                       COALESCE(p.javtxt_enrichment_status, '')
                FROM masterpiece_entries AS m
                LEFT JOIN processed_videos AS p
                    ON p.code = m.code
                ORDER BY COALESCE(m.created_at, '') ASC, UPPER(m.code) ASC
                '''
            )
            rows = cursor.fetchall()

        result = []
        for row in rows:
            medal_text = normalize_ladder_medal_text(row[5] or '')
            result.append(
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': sanitize_actor_text(row[2] or ''),
                    'display_title': row[1] or '',
                    'display_author': sanitize_actor_text(row[2] or ''),
                    'primary_source': row[3] or '',
                    'primary_detail_url': (row[4] or '') or self._build_movie_detail_url(
                        avfan_movie_id=row[8] or '',
                        javtxt_url=row[9] or '',
                    ),
                    'medal': medal_text,
                    'medals': split_ladder_medals(medal_text),
                    'created_at': row[6] or '',
                    'updated_at': row[7] or '',
                    'avfan_enrichment_status': row[10] or '',
                    'javtxt_enrichment_status': row[11] or '',
                }
            )
        return result

    def add_masterpiece_entry(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            raise ValueError('缂哄皯瑙嗛缂栧彿')

        references = self._collect_masterpiece_references(normalized_code)
        if not references:
            raise ValueError(f'瑙嗛涓嶅瓨鍦? {normalized_code}')
        primary_reference = self._pick_primary_masterpiece_reference(references)
        actor_details = self._collect_masterpiece_actor_details(normalized_code, primary_reference, references)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO masterpiece_entries (
                    code,
                    display_title,
                    display_author,
                    primary_source,
                    primary_detail_url,
                    medal
                )
                VALUES (?, ?, ?, ?, ?, '')
                ON CONFLICT(code) DO UPDATE SET
                    display_title = excluded.display_title,
                    display_author = excluded.display_author,
                    primary_source = excluded.primary_source,
                    primary_detail_url = excluded.primary_detail_url,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    normalized_code,
                    primary_reference.get('title', '') or normalized_code,
                    primary_reference.get('author', ''),
                    primary_reference.get('reference_source', ''),
                    primary_reference.get('detail_url', ''),
                ),
            )
            cursor.execute(
                '''
                DELETE FROM masterpiece_references
                WHERE masterpiece_code = ?
                ''',
                (normalized_code,),
            )
            cursor.execute(
                '''
                DELETE FROM masterpiece_actor_details
                WHERE masterpiece_code = ?
                ''',
                (normalized_code,),
            )
            cursor.execute(
                '''
                DELETE FROM masterpiece_actor_basic_infos
                WHERE masterpiece_code = ?
                ''',
                (normalized_code,),
            )
            cursor.executemany(
                '''
                INSERT INTO masterpiece_references (
                    masterpiece_code,
                    reference_source,
                    reference_key,
                    matched_code,
                    title,
                    author,
                    release_date,
                    avfan_movie_id,
                    avfan_url,
                    javtxt_movie_id,
                    javtxt_url,
                    detail_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        normalized_code,
                        reference.get('reference_source', ''),
                        reference.get('reference_key', ''),
                        reference.get('matched_code', ''),
                        reference.get('title', ''),
                        reference.get('author', ''),
                        reference.get('release_date', ''),
                        reference.get('avfan_movie_id', ''),
                        reference.get('avfan_url', ''),
                        reference.get('javtxt_movie_id', ''),
                        reference.get('javtxt_url', ''),
                        reference.get('detail_url', ''),
                    )
                    for reference in references
                ],
            )
            cursor.executemany(
                '''
                INSERT INTO masterpiece_actor_details (
                    masterpiece_code,
                    actor_name,
                    actor_order,
                    source_video_code,
                    release_date,
                    birthday,
                    current_age,
                    appearance_age,
                    height,
                    bust,
                    waist,
                    hip,
                    cup,
                    measurements_raw,
                    actor_exists_in_library
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        normalized_code,
                        actor_detail.get('actor_name', ''),
                        int(actor_detail.get('actor_order', 0) or 0),
                        actor_detail.get('source_video_code', ''),
                        actor_detail.get('release_date', ''),
                        actor_detail.get('birthday', ''),
                        actor_detail.get('current_age', ''),
                        actor_detail.get('appearance_age', ''),
                        actor_detail.get('height', ''),
                        actor_detail.get('bust', ''),
                        actor_detail.get('waist', ''),
                        actor_detail.get('hip', ''),
                        actor_detail.get('cup', ''),
                        actor_detail.get('measurements_raw', ''),
                        int(actor_detail.get('actor_exists_in_library', 0) or 0),
                    )
                    for actor_detail in actor_details
                ],
            )
            cursor.executemany(
                '''
                INSERT INTO masterpiece_actor_basic_infos (
                    masterpiece_code,
                    actor_name,
                    actor_id,
                    binghuo_person_id,
                    ladder_tier,
                    update_status,
                    local_video_count,
                    web_total_videos,
                    appearance_code_count,
                    code_prefix_library_count,
                    web_update_frequency_text,
                    web_enrichment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        normalized_code,
                        actor_detail.get('actor_name', ''),
                        actor_detail.get('actor_id', ''),
                        actor_detail.get('binghuo_person_id', ''),
                        actor_detail.get('ladder_tier', ''),
                        actor_detail.get('update_status', ''),
                        int(actor_detail.get('local_video_count', 0) or 0),
                        int(actor_detail.get('web_total_videos', 0) or 0),
                        int(actor_detail.get('appearance_code_count', 0) or 0),
                        int(actor_detail.get('code_prefix_library_count', 0) or 0),
                        actor_detail.get('web_update_frequency_text', ''),
                        actor_detail.get('web_enrichment_status', ''),
                    )
                    for actor_detail in actor_details
                ],
            )
            conn.commit()

        return self._get_masterpiece_entry(normalized_code)

    def _get_masterpiece_entry(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return {}
        for row in self.list_masterpiece_entries():
            if str((row or {}).get('code', '') or '').strip() == normalized_code:
                return dict(row or {})
        return {}

    def ensure_masterpiece_enrichment_candidate(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return {}

        processed_detail = self.get_video_detail_record(normalized_code)
        if processed_detail:
            return processed_detail

        entry = self._get_masterpiece_entry(normalized_code)
        references = self._collect_masterpiece_references(normalized_code)
        if not entry and not references:
            return {}

        primary_reference = self._pick_primary_masterpiece_reference(references)
        if not primary_reference:
            primary_reference = {
                'matched_code': normalized_code,
                'title': (entry or {}).get('title', '') or normalized_code,
                'author': (entry or {}).get('author', ''),
                'release_date': '',
                'avfan_movie_id': '',
                'javtxt_movie_id': '',
                'javtxt_url': '',
            }

        title = str(primary_reference.get('title', '') or (entry or {}).get('title', '') or normalized_code).strip()
        author = sanitize_actor_text(primary_reference.get('author', '') or (entry or {}).get('author', ''))
        release_date = str(primary_reference.get('release_date', '') or '').strip()
        javtxt_movie_id = str(primary_reference.get('javtxt_movie_id', '') or '').strip()
        javtxt_url = str(primary_reference.get('javtxt_url', '') or '').strip()
        avfan_movie_id = str(primary_reference.get('avfan_movie_id', '') or '').strip()

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO processed_videos (
                    code,
                    title,
                    author,
                    release_date,
                    avfan_movie_id,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_title,
                    javtxt_actors,
                    javtxt_actors_raw,
                    javtxt_release_date,
                    avfan_enrichment_status,
                    javtxt_enrichment_status,
                    enrichment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    title = COALESCE(NULLIF(processed_videos.title, ''), excluded.title),
                    author = COALESCE(NULLIF(processed_videos.author, ''), excluded.author),
                    release_date = COALESCE(NULLIF(processed_videos.release_date, ''), excluded.release_date),
                    avfan_movie_id = COALESCE(NULLIF(processed_videos.avfan_movie_id, ''), excluded.avfan_movie_id),
                    javtxt_movie_id = COALESCE(NULLIF(processed_videos.javtxt_movie_id, ''), excluded.javtxt_movie_id),
                    javtxt_url = COALESCE(NULLIF(processed_videos.javtxt_url, ''), excluded.javtxt_url),
                    javtxt_title = COALESCE(NULLIF(processed_videos.javtxt_title, ''), excluded.javtxt_title),
                    javtxt_actors = COALESCE(NULLIF(processed_videos.javtxt_actors, ''), excluded.javtxt_actors),
                    javtxt_actors_raw = COALESCE(NULLIF(processed_videos.javtxt_actors_raw, ''), excluded.javtxt_actors_raw),
                    javtxt_release_date = COALESCE(NULLIF(processed_videos.javtxt_release_date, ''), excluded.javtxt_release_date),
                    avfan_enrichment_status = COALESCE(NULLIF(processed_videos.avfan_enrichment_status, ''), excluded.avfan_enrichment_status),
                    javtxt_enrichment_status = COALESCE(NULLIF(processed_videos.javtxt_enrichment_status, ''), excluded.javtxt_enrichment_status),
                    enrichment_status = COALESCE(NULLIF(processed_videos.enrichment_status, ''), excluded.enrichment_status)
                ''',
                (
                    normalized_code,
                    title,
                    author,
                    release_date,
                    avfan_movie_id,
                    javtxt_movie_id,
                    javtxt_url,
                    title,
                    author,
                    author,
                    release_date,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                ),
            )
            conn.commit()
        return self.get_video_detail_record(normalized_code)

    def get_masterpiece_detail_record(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return {}

        entry = self._get_masterpiece_entry(normalized_code)
        if not entry:
            return {}
        processed_detail = self.get_video_detail_record(normalized_code)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT reference_source,
                       reference_key,
                       matched_code,
                       title,
                       author,
                       release_date,
                       avfan_movie_id,
                       avfan_url,
                       javtxt_movie_id,
                       javtxt_url,
                       detail_url
                FROM masterpiece_references
                WHERE masterpiece_code = ?
                ORDER BY CASE reference_source
                    WHEN 'video_library' THEN 0
                    WHEN 'code_prefix_library' THEN 1
                    WHEN 'actor_library' THEN 2
                    ELSE 99
                END, UPPER(reference_key), UPPER(matched_code)
                ''',
                (normalized_code,),
            )
            rows = cursor.fetchall()
            cursor.execute(
                '''
                SELECT actor_name,
                       actor_order,
                       source_video_code,
                       release_date,
                       birthday,
                       current_age,
                       appearance_age,
                       height,
                       bust,
                       waist,
                       hip,
                       cup,
                       measurements_raw,
                       actor_exists_in_library
                FROM masterpiece_actor_details
                WHERE masterpiece_code = ?
                ORDER BY actor_order ASC, UPPER(actor_name) ASC
                ''',
                (normalized_code,),
            )
            actor_rows = cursor.fetchall()
            cursor.execute(
                '''
                SELECT actor_name,
                       actor_id,
                       binghuo_person_id,
                       ladder_tier,
                       update_status,
                       local_video_count,
                       web_total_videos,
                       appearance_code_count,
                       code_prefix_library_count,
                       web_update_frequency_text,
                       web_enrichment_status
                FROM masterpiece_actor_basic_infos
                WHERE masterpiece_code = ?
                ''',
                (normalized_code,),
            )
            actor_basic_rows = cursor.fetchall()

        references = [
            {
                'reference_source': row[0] or '',
                'reference_key': row[1] or '',
                'matched_code': row[2] or '',
                'title': row[3] or '',
                'author': sanitize_actor_text(row[4] or ''),
                'release_date': row[5] or '',
                'avfan_movie_id': row[6] or '',
                'avfan_url': row[7] or '',
                'javtxt_movie_id': row[8] or '',
                'javtxt_url': row[9] or '',
                'detail_url': (row[10] or '') or self._build_movie_detail_url(
                    avfan_url=row[7] or '',
                    avfan_movie_id=row[6] or '',
                    javtxt_url=row[9] or '',
                ),
            }
            for row in rows
        ]

        if not references:
            if processed_detail:
                references = [self._build_processed_masterpiece_reference(processed_detail)]

        actor_basic_by_name = {
            row[0] or '': {
                'actor_id': row[1] or '',
                'binghuo_person_id': row[2] or '',
                'ladder_tier': row[3] or '',
                'update_status': row[4] or '',
                'update_status_text': self._masterpiece_update_status_text(row[4] or ''),
                'local_video_count': int(row[5] or 0),
                'web_total_videos': int(row[6] or 0),
                'appearance_code_count': int(row[7] or 0),
                'code_prefix_library_count': int(row[8] or 0),
                'web_update_frequency_text': row[9] or '',
                'web_enrichment_status': row[10] or '',
            }
            for row in actor_basic_rows
            if row[0]
        }
        actor_details = [
            {
                'actor_name': row[0] or '',
                'actor_order': int(row[1] or 0),
                'source_video_code': row[2] or '',
                'release_date': row[3] or '',
                'birthday': row[4] or '',
                'current_age': row[5] or '',
                'appearance_age': row[6] or '',
                'height': row[7] or '',
                'bust': row[8] or '',
                'waist': row[9] or '',
                'hip': row[10] or '',
                'cup': row[11] or '',
                'measurements_raw': row[12] or '',
                'actor_exists_in_library': int(row[13] or 0),
                'ladder_tier': self._get_masterpiece_actor_ladder_tier(row[0] or ''),
                **actor_basic_by_name.get(row[0] or '', {}),
            }
            for row in actor_rows
        ]
        if not actor_details:
            actor_details = self._collect_masterpiece_actor_details(
                normalized_code,
                self._pick_primary_masterpiece_reference(references),
                references,
            )
        actor_details = self._merge_masterpiece_actor_details_from_source_texts(
            normalized_code,
            actor_details,
            processed_detail,
            self._pick_primary_masterpiece_reference(references),
            references,
        )
        actor_details = self._ensure_masterpiece_actor_basic_snapshots(normalized_code, actor_details)
        actor_details = self._filter_visible_masterpiece_actor_details(actor_details)

        return {
            'code': entry.get('code', normalized_code),
            'title': entry.get('title', ''),
            'author': entry.get('author', ''),
            'display_title': entry.get('display_title', entry.get('title', '')),
            'display_author': entry.get('display_author', entry.get('author', '')),
            'display_tags': (processed_detail or {}).get('javtxt_tags', ''),
            'first_source_title': (processed_detail or {}).get('title', ''),
            'first_source_duration': (processed_detail or {}).get('duration', ''),
            'first_source_tags': (processed_detail or {}).get('avfan_tags', '') or (processed_detail or {}).get('javtxt_tags', ''),
            'first_source_actors': (processed_detail or {}).get('avfan_actors', '') or (processed_detail or {}).get('author', ''),
            'second_source_title': (processed_detail or {}).get('javtxt_title', ''),
            'second_source_actors': (processed_detail or {}).get('javtxt_actors', ''),
            'second_source_tags': (processed_detail or {}).get('javtxt_tags', ''),
            'second_source_description': (processed_detail or {}).get('javtxt_description', ''),
            'primary_source': entry.get('primary_source', ''),
            'primary_detail_url': entry.get('primary_detail_url', ''),
            'medal': entry.get('medal', ''),
            'medals': list(entry.get('medals', []) or []),
            'actor_details': actor_details,
            'collaborator_sections': self._collect_masterpiece_collaborator_sections(actor_details),
            'references': references,
        }

    def _filter_visible_masterpiece_actor_details(self, actor_details):
        hidden_names = self._hidden_masterpiece_actor_names()
        return [
            dict(row or {})
            for row in (actor_details or [])
            if str((row or {}).get('actor_name', '') or '').strip() not in hidden_names
        ]

    def _ensure_masterpiece_actor_basic_snapshots(self, normalized_code, actor_details):
        enriched_details = []
        for actor_detail in actor_details or []:
            row = dict(actor_detail or {})
            actor_name = str(row.get('actor_name', '') or '').strip()
            if not actor_name:
                enriched_details.append(row)
                continue
            self._sync_masterpiece_actor_registration(actor_name)
            snapshot = self._build_masterpiece_actor_basic_snapshot(
                normalized_code,
                actor_name,
                actor_row=self._find_exact_actor_row(actor_name),
                enrichment_record=self.get_actor_enrichment_record(actor_name),
            )
            merged = {**row, **snapshot}
            enriched_details.append(merged)
        self._store_masterpiece_actor_basic_snapshots(normalized_code, enriched_details)
        return enriched_details

    def _store_masterpiece_actor_basic_snapshots(self, normalized_code, actor_details):
        rows = []
        for actor_detail in actor_details or []:
            actor_name = str((actor_detail or {}).get('actor_name', '') or '').strip()
            if not actor_name:
                continue
            rows.append(
                (
                    normalized_code,
                    actor_name,
                    (actor_detail or {}).get('actor_id', ''),
                    (actor_detail or {}).get('binghuo_person_id', ''),
                    (actor_detail or {}).get('ladder_tier', ''),
                    (actor_detail or {}).get('update_status', ''),
                    int((actor_detail or {}).get('local_video_count', 0) or 0),
                    int((actor_detail or {}).get('web_total_videos', 0) or 0),
                    int((actor_detail or {}).get('appearance_code_count', 0) or 0),
                    int((actor_detail or {}).get('code_prefix_library_count', 0) or 0),
                    (actor_detail or {}).get('web_update_frequency_text', ''),
                    (actor_detail or {}).get('web_enrichment_status', ''),
                )
            )
        if not rows:
            return
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT INTO masterpiece_actor_basic_infos (
                    masterpiece_code,
                    actor_name,
                    actor_id,
                    binghuo_person_id,
                    ladder_tier,
                    update_status,
                    local_video_count,
                    web_total_videos,
                    appearance_code_count,
                    code_prefix_library_count,
                    web_update_frequency_text,
                    web_enrichment_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(masterpiece_code, actor_name) DO UPDATE SET
                    actor_id = excluded.actor_id,
                    binghuo_person_id = excluded.binghuo_person_id,
                    ladder_tier = excluded.ladder_tier,
                    update_status = excluded.update_status,
                    local_video_count = excluded.local_video_count,
                    web_total_videos = excluded.web_total_videos,
                    appearance_code_count = excluded.appearance_code_count,
                    code_prefix_library_count = excluded.code_prefix_library_count,
                    web_update_frequency_text = excluded.web_update_frequency_text,
                    web_enrichment_status = excluded.web_enrichment_status,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                rows,
            )
            conn.commit()

    def _build_masterpiece_actor_basic_snapshot(
        self,
        normalized_code,
        actor_name,
        actor_row=None,
        enrichment_record=None,
    ):
        actor_row = dict(actor_row or {})
        enrichment_record = dict(enrichment_record or {})
        try:
            local_rows = self.list_local_videos_by_actor_name(actor_name, refresh_categories=False)
        except TypeError:
            local_rows = self.list_local_videos_by_actor_name(actor_name)
        web_rows = list(self.list_actor_movies(actor_name) or [])
        eligible_web_rows = [row for row in web_rows if is_javtxt_eligible_movie(row)]
        cache_rows = self.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((row or {}).get('code', '')) for row in eligible_web_rows]
        )
        appearance_prefixes = self._collect_masterpiece_unique_prefixes(list(local_rows or []) + eligible_web_rows)
        update_status = resolve_update_status(list(local_rows or []) + eligible_web_rows)
        return {
            'actor_id': str((actor_row or {}).get('actor_id', '') or (enrichment_record or {}).get('actor_id', '') or '').strip(),
            'binghuo_person_id': str((enrichment_record or {}).get('binghuo_person_id', '') or '').strip(),
            'ladder_tier': self._get_masterpiece_actor_ladder_tier(actor_name),
            'update_status': update_status,
            'update_status_text': self._masterpiece_update_status_text(update_status),
            'local_video_count': len(local_rows or []),
            'web_total_videos': int((enrichment_record or {}).get('avfan_total_videos', 0) or 0),
            'appearance_code_count': len(appearance_prefixes),
            'code_prefix_library_count': self._count_prefixes_in_library(appearance_prefixes),
            'web_update_frequency': calculate_update_frequency(eligible_web_rows),
            'web_update_frequency_text': self._format_masterpiece_update_frequency(
                calculate_update_frequency(eligible_web_rows)
            ),
            'web_enrichment_status': self._build_live_masterpiece_actor_enrichment_status(
                enrichment_record,
                eligible_web_rows,
                cache_rows,
            ),
        }

    def _build_live_masterpiece_actor_enrichment_status(self, enrichment, movies, cache_rows):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '')).strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '')).strip() or UNENRICHED_STATUS
        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(
            movies,
            cache_rows=cache_rows,
        )
        binghuo_status = str((enrichment or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        baomu_status = str((enrichment or {}).get('baomu_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        return build_library_enrichment_status_text(avfan_status, javtxt_status, binghuo_status, baomu_status)

    @staticmethod
    def _format_masterpiece_update_frequency(stats):
        rate = dict(stats or {}).get('videos_per_month')
        if rate is None:
            return ''
        return f'{float(rate):.2f} 部/月'

    @staticmethod
    def _masterpiece_update_status_text(update_status):
        normalized_status = str(update_status or '').strip()
        return {
            'active': '正在更新',
            'suspect': '疑似更新',
            'inactive': '断更',
        }.get(normalized_status, '')

    @staticmethod
    def _collect_masterpiece_unique_prefixes(rows):
        return {
            normalized_prefix
            for normalized_prefix in (
                extract_code_prefix(standardize_video_code((row or {}).get('code', '')))
                for row in (rows or [])
            )
            if normalized_prefix
        }

    def _count_prefixes_in_library(self, prefixes):
        available_prefixes = {
            str(prefix or '').strip().upper()
            for prefix in (self.list_code_prefix_enrichment_records() or {}).keys()
            if str(prefix or '').strip()
        }
        return sum(1 for prefix in (prefixes or set()) if str(prefix or '').strip().upper() in available_prefixes)

    def _hidden_masterpiece_actor_names(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT actor_name
                FROM masterpiece_actors
                WHERE COALESCE(handle_mark, 0) = 2
                '''
            )
            rows = cursor.fetchall()
        return {str((row or [''])[0] or '').strip() for row in rows if str((row or [''])[0] or '').strip()}

    def _merge_masterpiece_actor_details_from_source_texts(
        self,
        normalized_code,
        actor_details,
        processed_detail,
        primary_reference,
        references,
    ):
        merged_details = [dict(row or {}) for row in (actor_details or [])]
        hidden_names = self._hidden_masterpiece_actor_names()
        seen = {
            str((row or {}).get('actor_name', '') or '').strip()
            for row in merged_details
            if str((row or {}).get('actor_name', '') or '').strip()
        }
        source_texts = [
            (processed_detail or {}).get('avfan_actors', ''),
            (processed_detail or {}).get('author', ''),
            (processed_detail or {}).get('javtxt_actors', ''),
        ]
        release_date = self._resolve_masterpiece_release_date(primary_reference, references)
        if not release_date:
            release_date = str((processed_detail or {}).get('release_date', '') or '').strip()

        for source_text in source_texts:
            for actor_name in split_actor_names(source_text):
                normalized_name = str(actor_name or '').strip()
                if not normalized_name or normalized_name in seen:
                    continue
                if normalized_name in hidden_names:
                    seen.add(normalized_name)
                    continue
                seen.add(normalized_name)
                self._sync_masterpiece_actor_registration(normalized_name)
                actor_row = self._find_exact_actor_row(normalized_name)
                actor_exists_in_library = 1 if actor_row else 0
                merged_details.append(
                    self._build_masterpiece_actor_detail_row(
                        normalized_code,
                        normalized_name,
                        len(merged_details) + 1,
                        release_date,
                        actor_exists_in_library,
                        actor_row=actor_row,
                        enrichment_record=self.get_actor_enrichment_record(normalized_name),
                    )
                )
        return merged_details

    def _collect_masterpiece_references(self, normalized_code):
        references = []
        processed_detail = self.get_video_detail_record(normalized_code)
        if processed_detail:
            references.append(self._build_processed_masterpiece_reference(processed_detail))

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT prefix,
                       code,
                       COALESCE(title, ''),
                       COALESCE(NULLIF(author, ''), NULLIF(author_raw, ''), ''),
                       COALESCE(release_date, ''),
                       COALESCE(avfan_url, ''),
                       COALESCE(javtxt_movie_id, ''),
                       COALESCE(javtxt_url, '')
                FROM code_prefix_movies
                WHERE code = ?
                ORDER BY release_date DESC, prefix ASC
                ''',
                (normalized_code,),
            )
            for row in cursor.fetchall():
                references.append(
                    self._build_masterpiece_reference(
                        reference_source='code_prefix_library',
                        reference_key=row[0] or '',
                        matched_code=row[1] or normalized_code,
                        title=row[2] or normalized_code,
                        author=row[3] or '',
                        release_date=row[4] or '',
                        avfan_url=row[5] or '',
                        javtxt_movie_id=row[6] or '',
                        javtxt_url=row[7] or '',
                    )
                )

            cursor.execute(
                '''
                SELECT actor_name,
                       code,
                       COALESCE(title, ''),
                       COALESCE(NULLIF(author, ''), NULLIF(author_raw, ''), ''),
                       COALESCE(release_date, ''),
                       COALESCE(avfan_url, ''),
                       COALESCE(javtxt_movie_id, ''),
                       COALESCE(javtxt_url, '')
                FROM actor_movies
                WHERE code = ?
                ORDER BY release_date DESC, actor_name ASC
                ''',
                (normalized_code,),
            )
            for row in cursor.fetchall():
                references.append(
                    self._build_masterpiece_reference(
                        reference_source='actor_library',
                        reference_key=row[0] or '',
                        matched_code=row[1] or normalized_code,
                        title=row[2] or normalized_code,
                        author=row[3] or '',
                        release_date=row[4] or '',
                        avfan_url=row[5] or '',
                        javtxt_movie_id=row[6] or '',
                        javtxt_url=row[7] or '',
                    )
                )
        return references

    @staticmethod
    def _pick_primary_masterpiece_reference(references):
        for source_name in MASTERPIECE_SOURCE_PRIORITY:
            for reference in references:
                if str(reference.get('reference_source', '') or '').strip() == source_name:
                    return dict(reference)
        return dict(references[0] or {}) if references else {}

    def _build_processed_masterpiece_reference(self, detail):
        normalized_code = standardize_video_code(detail.get('code', ''))
        return self._build_masterpiece_reference(
            reference_source='video_library',
            reference_key=normalized_code,
            matched_code=normalized_code,
            title=detail.get('title', '') or normalized_code,
            author=detail.get('author', ''),
            release_date=detail.get('release_date', ''),
            avfan_movie_id=detail.get('avfan_movie_id', ''),
            javtxt_movie_id=detail.get('javtxt_movie_id', ''),
            javtxt_url=detail.get('javtxt_url', ''),
        )

    def _build_masterpiece_reference(
        self,
        reference_source,
        reference_key,
        matched_code,
        title='',
        author='',
        release_date='',
        avfan_movie_id='',
        avfan_url='',
        javtxt_movie_id='',
        javtxt_url='',
    ):
        normalized_source = str(reference_source or '').strip()
        normalized_key = str(reference_key or '').strip()
        normalized_matched_code = standardize_video_code(matched_code)
        normalized_title = str(title or '').strip() or normalized_matched_code
        normalized_author = sanitize_actor_text(author or '')
        normalized_release_date = str(release_date or '').strip()
        normalized_avfan_movie_id = str(avfan_movie_id or '').strip()
        normalized_avfan_url = str(avfan_url or '').strip()
        normalized_javtxt_movie_id = str(javtxt_movie_id or '').strip()
        normalized_javtxt_url = str(javtxt_url or '').strip()
        return {
            'reference_source': normalized_source,
            'reference_key': normalized_key,
            'matched_code': normalized_matched_code,
            'title': normalized_title,
            'author': normalized_author,
            'release_date': normalized_release_date,
            'avfan_movie_id': normalized_avfan_movie_id,
            'avfan_url': normalized_avfan_url,
            'javtxt_movie_id': normalized_javtxt_movie_id,
            'javtxt_url': normalized_javtxt_url,
            'detail_url': self._build_movie_detail_url(
                avfan_url=normalized_avfan_url,
                avfan_movie_id=normalized_avfan_movie_id,
                javtxt_url=normalized_javtxt_url,
            ),
        }

    def _sync_masterpiece_actor_registration(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return {'actor_name': '', 'status': 0, 'handle_mark': 0}

        actor_exists = 1 if self._find_exact_actor_row(normalized_name) else 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO masterpiece_actors (actor_name, status, handle_mark)
                VALUES (?, ?, 0)
                ON CONFLICT(actor_name) DO UPDATE SET
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (normalized_name, actor_exists),
            )
            cursor.execute(
                '''
                SELECT status, handle_mark
                FROM masterpiece_actors
                WHERE actor_name = ?
                ''',
                (normalized_name,),
            )
            row = cursor.fetchone()
            conn.commit()

        status = int((row or [actor_exists, 0])[0] or 0)
        handle_mark = int((row or [0, 0])[1] or 0)
        if status == 0 and handle_mark == 1:
            try:
                self.add_actor(normalized_name, birthday='', age='')
            except ValueError:
                pass
            status = 1 if self._find_exact_actor_row(normalized_name) else 0
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    UPDATE masterpiece_actors
                    SET status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (status, normalized_name),
                )
                conn.commit()

        return {'actor_name': normalized_name, 'status': status, 'handle_mark': handle_mark}

    def _collect_masterpiece_actor_details(self, normalized_code, primary_reference, references):
        actor_names = self._collect_masterpiece_actor_names(primary_reference, references)
        release_date = self._resolve_masterpiece_release_date(primary_reference, references)
        actor_details = []
        for actor_order, actor_name in enumerate(actor_names, start=1):
            self._sync_masterpiece_actor_registration(actor_name)
            actor_row = self._find_exact_actor_row(actor_name)
            actor_exists_in_library = 1 if actor_row else 0
            enrichment_record = self.get_actor_enrichment_record(actor_name)
            actor_details.append(
                self._build_masterpiece_actor_detail_row(
                    normalized_code,
                    actor_name,
                    actor_order,
                    release_date,
                    actor_exists_in_library,
                    actor_row=actor_row,
                    enrichment_record=enrichment_record,
                )
            )
        return actor_details

    def _collect_masterpiece_actor_names(self, primary_reference, references):
        ordered_names = []
        seen = set()

        def push_name(name):
            normalized_name = str(name or '').strip()
            if not normalized_name or normalized_name in seen:
                return
            seen.add(normalized_name)
            ordered_names.append(normalized_name)

        primary_source = str((primary_reference or {}).get('reference_source', '') or '').strip()
        if primary_source == 'actor_library':
            push_name((primary_reference or {}).get('reference_key', ''))
        else:
            for actor_name in split_actor_names((primary_reference or {}).get('author', '')):
                push_name(actor_name)
        for reference in references or []:
            reference_source = str((reference or {}).get('reference_source', '') or '').strip()
            if reference_source == 'actor_library':
                push_name((reference or {}).get('reference_key', ''))
                continue
            for actor_name in split_actor_names((reference or {}).get('author', '')):
                push_name(actor_name)
        return ordered_names

    def _build_masterpiece_actor_detail_row(
        self,
        normalized_code,
        actor_name,
        actor_order,
        release_date,
        actor_exists_in_library,
        actor_row=None,
        enrichment_record=None,
    ):
        actor_row = dict(actor_row or {})
        enrichment_record = dict(enrichment_record or {})
        birthday = self._resolve_masterpiece_actor_birthday(actor_row, enrichment_record)
        basic_snapshot = self._build_masterpiece_actor_basic_snapshot(
            normalized_code,
            actor_name,
            actor_row=actor_row,
            enrichment_record=enrichment_record,
        )
        return {
            'actor_name': actor_name,
            'actor_order': int(actor_order or 0),
            'source_video_code': normalized_code,
            'release_date': str(release_date or '').strip(),
            'birthday': birthday,
            'current_age': self._resolve_masterpiece_actor_current_age(actor_row, birthday),
            'appearance_age': self._calculate_masterpiece_appearance_age(birthday, release_date),
            'height': self._merged_masterpiece_actor_profile_value(enrichment_record, 'binghuo_height', 'baomu_height'),
            'bust': self._merged_masterpiece_actor_profile_value(enrichment_record, 'binghuo_bust', 'baomu_bust'),
            'waist': self._merged_masterpiece_actor_profile_value(enrichment_record, 'binghuo_waist', 'baomu_waist'),
            'hip': self._merged_masterpiece_actor_profile_value(enrichment_record, 'binghuo_hip', 'baomu_hip'),
            'cup': self._merged_masterpiece_actor_profile_value(enrichment_record, 'binghuo_cup', 'baomu_cup'),
            'measurements_raw': self._merged_masterpiece_actor_profile_value(
                enrichment_record,
                'binghuo_measurements_raw',
                'baomu_measurements_raw',
            ),
            'actor_exists_in_library': int(actor_exists_in_library or 0),
            'ladder_tier': self._get_masterpiece_actor_ladder_tier(actor_name),
            **basic_snapshot,
        }

    def _find_exact_actor_row(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return None
        for row in self.list_actors(normalized_name):
            if str((row or {}).get('name', '') or '').strip() == normalized_name:
                return dict(row or {})
        return None

    def _get_masterpiece_actor_ladder_tier(self, actor_name):
        entry = self.get_ladder_entry(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR, actor_name)
        return str((entry or {}).get('tier', '') or '').strip().upper()

    @staticmethod
    def _merged_masterpiece_actor_profile_value(enrichment_record, primary_key, fallback_key):
        return str(
            (enrichment_record or {}).get(primary_key, '')
            or (enrichment_record or {}).get(fallback_key, '')
            or ''
        ).strip()

    def _resolve_masterpiece_actor_birthday(self, actor_row, enrichment_record):
        birthday = (
            str((actor_row or {}).get('birthday', '') or '').strip()
            or normalize_actor_birthday_for_display((enrichment_record or {}).get('binghuo_birthday', ''))
            or normalize_actor_birthday_for_display((enrichment_record or {}).get('baomu_birthday', ''))
        )
        return str(birthday or '').strip()

    @staticmethod
    def _resolve_masterpiece_actor_current_age(actor_row, birthday):
        raw_age = str((actor_row or {}).get('raw_age', '') or '').strip()
        if raw_age:
            return raw_age
        display_age = str((actor_row or {}).get('age', '') or '').strip()
        if birthday and display_age.isdigit():
            return display_age
        return ''

    def _resolve_masterpiece_release_date(self, primary_reference, references):
        for candidate in (
            (primary_reference or {}).get('release_date', ''),
            *[(reference or {}).get('release_date', '') for reference in (references or [])],
        ):
            normalized_candidate = str(candidate or '').strip()
            if normalized_candidate:
                return normalized_candidate
        return ''

    def _collect_masterpiece_collaborator_sections(self, actor_details):
        sections = []
        for actor_detail in actor_details or []:
            ladder_tier = str((actor_detail or {}).get('ladder_tier', '') or '').strip().upper()
            if ladder_tier not in {'S', 'A'}:
                continue
            actor_name = str((actor_detail or {}).get('actor_name', '') or '').strip()
            if not actor_name:
                continue
            sections.append(
                {
                    'actor_name': actor_name,
                    'ladder_tier': ladder_tier,
                    'collaborators': self._collect_masterpiece_collaborators_for_actor(actor_name),
                }
            )
        return sections

    def _collect_masterpiece_collaborators_for_actor(self, actor_name):
        rows_by_code = {}
        try:
            local_rows = self.list_local_videos_by_actor_name(actor_name, refresh_categories=False)
        except TypeError:
            local_rows = self.list_local_videos_by_actor_name(actor_name)
        for row in local_rows or []:
            normalized_code = standardize_video_code((row or {}).get('code', ''))
            if normalized_code:
                rows_by_code[normalized_code] = dict(row or {})

        for row in self.list_actor_movies(actor_name) or []:
            normalized_code = standardize_video_code((row or {}).get('code', ''))
            if not normalized_code:
                continue
            current = dict(rows_by_code.get(normalized_code, {}) or {})
            merged = dict(row or {})
            if current:
                for field_name in ('author', 'release_date', 'video_category', 'title'):
                    if not merged.get(field_name):
                        merged[field_name] = current.get(field_name, '')
            rows_by_code[normalized_code] = merged

        collaborator_counts = {}
        normalized_actor_name = str(actor_name or '').strip()
        for row in rows_by_code.values():
            if normalize_video_category((row or {}).get('video_category', '')) != VIDEO_CATEGORY_CO_STAR:
                continue
            collaborator_names = []
            seen = set()
            for collaborator_name in split_actor_names((row or {}).get('author', '')):
                if collaborator_name == normalized_actor_name or collaborator_name in seen:
                    continue
                seen.add(collaborator_name)
                collaborator_names.append(collaborator_name)
            for collaborator_name in collaborator_names:
                collaborator_counts[collaborator_name] = collaborator_counts.get(collaborator_name, 0) + 1

        return [
            {'actor_name': collaborator_name, 'count': count}
            for collaborator_name, count in sorted(
                collaborator_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    @classmethod
    def _calculate_masterpiece_appearance_age(cls, birthday, release_date):
        birthday_date = cls._parse_masterpiece_date(birthday)
        release_day = cls._parse_masterpiece_date(release_date)
        if birthday_date is None or release_day is None:
            return ''
        age = release_day.year - birthday_date.year
        if (release_day.month, release_day.day) < (birthday_date.month, birthday_date.day):
            age -= 1
        return str(max(age, 0))

    @classmethod
    def _parse_masterpiece_date(cls, value):
        text = str(value or '').strip()
        if not text:
            return None
        match = MASTERPIECE_DATE_RE.search(text)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    def _build_movie_detail_url(self, avfan_url='', avfan_movie_id='', javtxt_url=''):
        normalized_avfan_url = str(avfan_url or '').strip()
        if normalized_avfan_url:
            return normalized_avfan_url

        normalized_avfan_movie_id = str(avfan_movie_id or '').strip()
        if normalized_avfan_movie_id:
            try:
                return f'{get_avfan_base_url()}/movies/{quote(normalized_avfan_movie_id)}'
            except Exception:
                pass

        return str(javtxt_url or '').strip()

    def list_global_medals(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT name,
                       COALESCE(description, ''),
                       COALESCE(created_at, ''),
                       COALESCE(updated_at, '')
                FROM global_medals
                ORDER BY created_at ASC, UPPER(name) ASC
                '''
            )
            rows = cursor.fetchall()

        return [
            {
                'name': row[0] or '',
                'description': row[1] or '',
                'created_at': row[2] or '',
                'updated_at': row[3] or '',
            }
            for row in rows
        ]

    def add_global_medal(self, name, description=''):
        normalized_name = str(name or '').strip()
        normalized_description = str(description or '').strip()
        if not normalized_name:
            raise ValueError('缺少勋章名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM global_medals WHERE name = ?', (normalized_name,))
            if cursor.fetchone():
                raise ValueError(f'勋章已存在: {normalized_name}')
            cursor.execute(
                '''
                INSERT INTO global_medals (name, description)
                VALUES (?, ?)
                ''',
                (normalized_name, normalized_description),
            )
            conn.commit()

        return self._get_global_medal(normalized_name)

    def update_global_medal_description(self, name, description=''):
        normalized_name = str(name or '').strip()
        normalized_description = str(description or '').strip()
        if not normalized_name:
            raise ValueError('缺少勋章名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE global_medals
                SET description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
                ''',
                (normalized_description, normalized_name),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f'勋章不存在: {normalized_name}')
            conn.commit()

        return self._get_global_medal(normalized_name)

    def delete_global_medal(self, name):
        normalized_name = str(name or '').strip()
        if not normalized_name:
            raise ValueError('缺少勋章名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM global_medals WHERE name = ?', (normalized_name,))
            if cursor.rowcount <= 0:
                raise ValueError(f'勋章不存在: {normalized_name}')
            conn.commit()

        return {'name': normalized_name, 'deleted': True}

    def _get_global_medal(self, name):
        normalized_name = str(name or '').strip()
        if not normalized_name:
            return {}
        for row in self.list_global_medals():
            if str((row or {}).get('name', '') or '').strip() == normalized_name:
                return dict(row or {})
        return {}

    def get_video_detail_record(self, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return {}

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT code,
                       title,
                       author,
                       duration,
                       size,
                       storage_location,
                       avfan_movie_id,
                       avfan_actors,
                       avfan_tags,
                       javtxt_movie_id,
                       javtxt_url,
                       javtxt_title,
                       javtxt_actors,
                       javtxt_tags,
                       javtxt_description,
                       video_category,
                       release_date,
                       maker,
                       publisher,
                       avfan_enrichment_status,
                       javtxt_enrichment_status,
                       supplement_enrichment_status,
                       supplement_enrichment_error,
                       supplement_enriched_at
                FROM processed_videos
                WHERE code = ?
                ''',
                (normalized_code,),
            )
            row = cursor.fetchone()

        if not row:
            return {}

        return {
            'code': row[0] or '',
            'title': row[1] or '',
            'author': sanitize_actor_text(row[2] or ''),
            'duration': row[3] or '',
            'size': row[4] or '',
            'storage_location': row[5] or '',
            'avfan_movie_id': row[6] or '',
            'avfan_actors': sanitize_actor_text(row[7] or ''),
            'avfan_tags': row[8] or '',
            'javtxt_movie_id': row[9] or '',
            'javtxt_url': row[10] or '',
            'javtxt_title': row[11] or '',
            'javtxt_actors': sanitize_actor_text(row[12] or ''),
            'javtxt_tags': row[13] or '',
            'javtxt_description': row[14] or '',
            'video_category': normalize_video_category(row[15]),
            'release_date': row[16] or '',
            'maker': row[17] or '',
            'publisher': row[18] or '',
            'avfan_enrichment_status': row[19] or '',
            'javtxt_enrichment_status': row[20] or '',
            'supplement_enrichment_status': row[21] or '',
            'supplement_enrichment_error': row[22] or '',
            'supplement_enriched_at': row[23] or '',
        }

    def bulk_update_processed_videos_for_supplement(self, updates):
        normalized_updates = []
        for row in updates or []:
            code = standardize_video_code((row or {}).get('code', ''))
            if not code:
                continue
            author = sanitize_actor_text((row or {}).get('author', ''))
            author_raw = self._normalize_actor_raw_text((row or {}).get('author_raw', (row or {}).get('author', '')))
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    author,
                    author,
                    author_raw,
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('maker', '') or '').strip(),
                    str((row or {}).get('publisher', '') or '').strip(),
                    str((row or {}).get('avfan_movie_id', '') or '').strip(),
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE processed_videos
                SET title = ?,
                    author = ?,
                    javtxt_actors = ?,
                    javtxt_actors_raw = ?,
                    release_date = ?,
                    maker = ?,
                    publisher = ?,
                    avfan_movie_id = ?,
                    supplement_enrichment_status = ?,
                    supplement_enrichment_error = '',
                    supplement_enriched_at = NULL
                WHERE code = ?
                ''',
                [(*row[:-1], UNENRICHED_STATUS, row[-1]) for row in normalized_updates],
            )
            conn.commit()
        return len(normalized_updates)

    def bulk_update_code_prefix_movies(self, updates):
        normalized_updates = []
        for row in updates or []:
            prefix = str((row or {}).get('prefix', '') or '').strip().upper()
            code = standardize_video_code((row or {}).get('code', ''))
            if not prefix or not code:
                continue
            javtxt_status = str((row or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            javtxt_movie_id = str((row or {}).get('javtxt_movie_id', '') or '').strip()
            javtxt_url = str((row or {}).get('javtxt_url', '') or '').strip()
            author, author_raw = self._normalize_web_movie_actor_fields(
                row,
                javtxt_movie_id=javtxt_movie_id,
                javtxt_url=javtxt_url,
            )
            if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
            ):
                javtxt_status = UNENRICHED_STATUS
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    author,
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    str((row or {}).get('javtxt_tags', '') or '').strip(),
                    str((row or {}).get('javtxt_release_date', '') or '').strip(),
                    author_raw,
                    normalize_video_category((row or {}).get('video_category', '')),
                    prefix,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = ?,
                    author_raw = ?,
                    video_category = ?
                WHERE prefix = ? AND code = ?
                ''',
                normalized_updates,
            )
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def bulk_update_code_prefix_movies_for_supplement(self, updates):
        normalized_updates = []
        for row in updates or []:
            prefix = str((row or {}).get('prefix', '') or '').strip().upper()
            code = standardize_video_code((row or {}).get('code', ''))
            if not prefix or not code:
                continue
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    sanitize_actor_text((row or {}).get('author', '')),
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    self._normalize_actor_raw_text((row or {}).get('author_raw', (row or {}).get('author', ''))),
                    normalize_video_category((row or {}).get('video_category', '')),
                    prefix,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    author_raw = ?,
                    video_category = ?,
                    supplement_enrichment_status = ?,
                    supplement_enrichment_error = '',
                    supplement_enriched_at = NULL
                WHERE prefix = ? AND code = ?
                ''',
                [(*row[:-2], UNENRICHED_STATUS, row[-2], row[-1]) for row in normalized_updates],
            )
            conn.commit()
        return len(normalized_updates)

    def bulk_update_actor_movies(self, updates):
        normalized_updates = []
        for row in updates or []:
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            code = standardize_video_code((row or {}).get('code', ''))
            if not actor_name or not code:
                continue
            javtxt_status = str((row or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            javtxt_movie_id = str((row or {}).get('javtxt_movie_id', '') or '').strip()
            javtxt_url = str((row or {}).get('javtxt_url', '') or '').strip()
            author, author_raw = self._normalize_web_movie_actor_fields(
                row,
                javtxt_movie_id=javtxt_movie_id,
                javtxt_url=javtxt_url,
            )
            if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
            ):
                javtxt_status = UNENRICHED_STATUS
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    author,
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    str((row or {}).get('javtxt_tags', '') or '').strip(),
                    str((row or {}).get('javtxt_release_date', '') or '').strip(),
                    author_raw,
                    normalize_video_category((row or {}).get('video_category', '')),
                    actor_name,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = ?,
                    author_raw = ?,
                    video_category = ?
                WHERE actor_name = ? AND code = ?
                ''',
                normalized_updates,
            )
            conn.commit()
        self.refresh_actor_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def bulk_update_actor_movies_for_supplement(self, updates):
        normalized_updates = []
        for row in updates or []:
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            code = standardize_video_code((row or {}).get('code', ''))
            if not actor_name or not code:
                continue
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    sanitize_actor_text((row or {}).get('author', '')),
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    self._normalize_actor_raw_text((row or {}).get('author_raw', (row or {}).get('author', ''))),
                    normalize_video_category((row or {}).get('video_category', '')),
                    actor_name,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    author_raw = ?,
                    video_category = ?,
                    supplement_enrichment_status = ?,
                    supplement_enrichment_error = '',
                    supplement_enriched_at = NULL
                WHERE actor_name = ? AND code = ?
                ''',
                [(*row[:-2], UNENRICHED_STATUS, row[-2], row[-1]) for row in normalized_updates],
            )
            conn.commit()
        return len(normalized_updates)

    def refresh_code_prefix_javtxt_statuses(self, prefixes):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix in seen:
                continue
            seen.add(normalized_prefix)
            normalized_prefixes.append(normalized_prefix)

        if not normalized_prefixes:
            return 0

        movies_by_prefix = self.list_code_prefix_movies_by_prefixes(normalized_prefixes)
        all_codes = [
            standardize_video_code((movie or {}).get('code', ''))
            for rows in movies_by_prefix.values()
            for movie in rows
            if (movie or {}).get('code')
        ]
        cache_rows = self.get_javtxt_actor_cache_by_codes(all_codes)

        with self._connect() as conn:
            cursor = conn.cursor()
            for prefix in normalized_prefixes:
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO code_prefix_enrichments (prefix)
                    VALUES (?)
                    ''',
                    (prefix,),
                )
                cursor.execute(
                    '''
                    SELECT javtxt_last_error
                    FROM code_prefix_enrichments
                    WHERE prefix = ?
                    ''',
                    (prefix,),
                )
                existing_error = str((cursor.fetchone() or [''])[0] or '')
                movies = movies_by_prefix.get(prefix, [])
                summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
                status = build_javtxt_library_status(movies, cache_rows=cache_rows)
                cursor.execute(
                    '''
                    UPDATE code_prefix_enrichments
                    SET javtxt_enrichment_status = ?,
                        javtxt_total_videos = ?,
                        javtxt_last_error = ?,
                        javtxt_last_enriched_at = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(summary.get('total_count', 0) or 0),
                        existing_error if status == FAILED_STATUS else '',
                        prefix,
                    ),
                )
                self._refresh_code_prefix_combined_status(cursor, prefix)
            conn.commit()
        return len(normalized_prefixes)

    def refresh_actor_javtxt_statuses(self, actor_names):
        normalized_actor_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_actor_names.append(normalized_name)

        if not normalized_actor_names:
            return 0

        movies_by_name = self.list_actor_movies_by_names(normalized_actor_names)
        all_codes = [
            standardize_video_code((movie or {}).get('code', ''))
            for rows in movies_by_name.values()
            for movie in rows
            if (movie or {}).get('code')
        ]
        cache_rows = self.get_javtxt_actor_cache_by_codes(all_codes)

        with self._connect() as conn:
            cursor = conn.cursor()
            for actor_name in normalized_actor_names:
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO actor_enrichments (actor_name)
                    VALUES (?)
                    ''',
                    (actor_name,),
                )
                cursor.execute(
                    '''
                    SELECT javtxt_last_error
                    FROM actor_enrichments
                    WHERE actor_name = ?
                    ''',
                    (actor_name,),
                )
                existing_error = str((cursor.fetchone() or [''])[0] or '')
                movies = movies_by_name.get(actor_name, [])
                summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
                status = build_javtxt_library_status(movies, cache_rows=cache_rows)
                cursor.execute(
                    '''
                    UPDATE actor_enrichments
                    SET javtxt_enrichment_status = ?,
                        javtxt_total_videos = ?,
                        javtxt_last_error = ?,
                        javtxt_last_enriched_at = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        status,
                        int(summary.get('total_count', 0) or 0),
                        existing_error if status == FAILED_STATUS else '',
                        actor_name,
                    ),
                )
                self._refresh_actor_combined_status(cursor, actor_name)
            conn.commit()
        return len(normalized_actor_names)

    def list_videos_requiring_manual_category(self):
        self.refresh_video_categories_from_filter_rules()
        with self._connect() as conn:
            cursor = conn.cursor()
            staged_rows = self._list_staged_video_categories(cursor)
            staged_codes = set(staged_rows)
            manual_rows = {}
            processed_codes_to_clear = []
            prefix_rowids_to_clear = []
            actor_rowids_to_clear = []

            cursor.execute(
                '''
                SELECT code,
                       COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code) AS display_title,
                       javtxt_url,
                       javtxt_actors,
                       javtxt_actors_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM processed_videos
                WHERE COALESCE(javtxt_enrichment_status, ?) = ?
                  AND COALESCE(video_category, '') = ''
                ORDER BY code
                ''',
                (UNENRICHED_STATUS, ENRICHED_STATUS),
            )
            for row in cursor.fetchall():
                code = str(row[0] or '').strip().upper()
                if not code or code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[1] or '',
                        'release_date': row[5] or '',
                        'javtxt_tags': row[6] or '',
                        'video_category': normalize_video_category(row[7]),
                    }
                ):
                    if (row[2] or '').strip() or (row[3] or '').strip() or (row[4] or '').strip():
                        processed_codes_to_clear.append(code)
                    continue
                manual_rows[code] = {
                        'code': code,
                        'title': row[1] or '',
                        'avfan_url': '',
                        'javtxt_url': row[2] or '',
                        'javtxt_tags': row[6] or '',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'manual_tier': self._classify_manual_category_tier(row[3], row[4]),
                        'actor_count': count_video_actors(row[3]),
                    }
                if not manual_rows[code]['manual_tier']:
                    manual_rows.pop(code, None)

            cursor.execute(
                '''
                SELECT rowid,
                       code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       author_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM code_prefix_movies
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[1] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[2] or '',
                        'release_date': row[7] or '',
                        'javtxt_tags': row[8] or '',
                        'video_category': normalize_video_category(row[9]),
                    }
                ):
                    if str(row[4] or '').strip() or str(row[5] or '').strip() or str(row[6] or '').strip():
                        prefix_rowids_to_clear.append(row[0])
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[2],
                    avfan_url=row[3],
                    javtxt_url=row[4],
                    author=row[5],
                    author_raw=row[6],
                    release_date=row[7],
                    javtxt_tags=row[8],
                    video_category=row[9],
                )

            cursor.execute(
                '''
                SELECT rowid,
                       code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       author_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM actor_movies
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[1] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[2] or '',
                        'release_date': row[7] or '',
                        'javtxt_tags': row[8] or '',
                        'video_category': normalize_video_category(row[9]),
                    }
                ):
                    if str(row[4] or '').strip() or str(row[5] or '').strip() or str(row[6] or '').strip():
                        actor_rowids_to_clear.append(row[0])
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[2],
                    avfan_url=row[3],
                    javtxt_url=row[4],
                    author=row[5],
                    author_raw=row[6],
                    release_date=row[7],
                    javtxt_tags=row[8],
                    video_category=row[9],
                )

            if processed_codes_to_clear:
                self._clear_processed_video_javtxt_codes(cursor, processed_codes_to_clear)
            if prefix_rowids_to_clear:
                self._clear_web_movie_javtxt_rowids(cursor, 'code_prefix_movies', prefix_rowids_to_clear)
            if actor_rowids_to_clear:
                self._clear_web_movie_javtxt_rowids(cursor, 'actor_movies', actor_rowids_to_clear)
            if processed_codes_to_clear or prefix_rowids_to_clear or actor_rowids_to_clear:
                conn.commit()
        return {
            'videos': [manual_rows[code] for code in sorted(manual_rows)],
            'staged_count': len(staged_rows),
        }

    def stage_video_category(self, code, category):
        normalized_code = standardize_video_code(code)
        normalized_category = normalize_video_category(category)
        if not normalized_code:
            raise ValueError('缺少视频编号')
        if normalized_category not in VIDEO_CATEGORY_OPTIONS:
            raise ValueError('视频分类无效')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (normalized_code, normalized_category),
            )
            conn.commit()
            return {
                'staged_count': self._count_staged_video_categories(cursor),
            }

    def stage_video_categories(self, entries):
        normalized_entries = {}
        for entry in entries or []:
            code = standardize_video_code((entry or {}).get('code', ''))
            category = normalize_video_category((entry or {}).get('category', ''))
            if not code:
                continue
            if category not in VIDEO_CATEGORY_OPTIONS:
                raise ValueError('视频分类无效')
            normalized_entries[code] = category

        if not normalized_entries:
            return {
                'staged_count': 0,
                'batch_count': 0,
            }

        payload = [
            (code, category)
            for code, category in normalized_entries.items()
        ]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                payload,
            )
            conn.commit()
            return {
                'staged_count': self._count_staged_video_categories(cursor),
                'batch_count': len(payload),
            }

    def sync_staged_video_categories(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            staged_rows = list(self._list_staged_video_categories(cursor).items())
            if not staged_rows:
                return {
                    'synced_count': 0,
                    'updated_count': 0,
                    'staged_count': 0,
                }

            update_payload = [(category, code) for code, category in staged_rows]
            updated_count = 0
            cursor.executemany(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.execute('DELETE FROM manual_category_staging')
            conn.commit()
            return {
                'synced_count': len(staged_rows),
                'updated_count': updated_count,
                'staged_count': 0,
            }

    def update_video_category(self, code, category):
        return self.update_video_categories([code], category).get('updated_count', 0)

    def update_video_categories(self, codes, category, clear_staged=False):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        normalized_category = normalize_video_category(category)
        if not normalized_codes:
            return {
                'updated_count': 0,
                'code_count': 0,
                'cleared_staged_count': 0,
            }
        if normalized_category not in VIDEO_CATEGORY_OPTIONS:
            raise ValueError('视频分类无效')

        payload = [(normalized_category, code) for code in normalized_codes]
        placeholders = ','.join('?' for _ in normalized_codes)

        with self._connect() as conn:
            cursor = conn.cursor()
            updated_count = 0
            cursor.executemany(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                payload,
            )
            updated_count += int(cursor.rowcount or 0)

            cleared_staged_count = 0
            if clear_staged:
                cursor.execute(
                    f'''
                    DELETE FROM manual_category_staging
                    WHERE code IN ({placeholders})
                    ''',
                    normalized_codes,
                )
                cleared_staged_count = int(cursor.rowcount or 0)

            conn.commit()
            return {
                'updated_count': updated_count,
                'code_count': len(normalized_codes),
                'cleared_staged_count': cleared_staged_count,
            }

    @staticmethod
    def _list_staged_video_categories(cursor):
        cursor.execute(
            '''
            SELECT code, category
            FROM manual_category_staging
            ORDER BY updated_at, code
            '''
        )
        return {
            standardize_video_code(row[0]): normalize_video_category(row[1])
            for row in cursor.fetchall()
            if standardize_video_code(row[0])
        }

    @staticmethod
    def _count_staged_video_categories(cursor):
        cursor.execute('SELECT COUNT(*) FROM manual_category_staging')
        row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    @staticmethod
    def _merge_manual_category_row(
        rows_by_code,
        code,
        title,
        avfan_url,
        javtxt_url,
        author='',
        author_raw='',
        release_date='',
        javtxt_tags='',
        video_category='',
    ):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        if not is_javtxt_eligible_movie(
            {
                'code': normalized_code,
                'title': title,
                'release_date': release_date,
                'javtxt_tags': javtxt_tags,
                'video_category': normalize_video_category(video_category),
            }
        ):
            return

        if not is_manual_category_candidate(
            {
                'author': author,
                'author_raw': author_raw,
                'javtxt_url': javtxt_url,
            }
        ):
            return

        manual_tier = VideoDatabase._classify_manual_category_tier(author, author_raw)
        if not manual_tier:
            return

        current = rows_by_code.get(normalized_code)
        candidate = {
            'code': normalized_code,
            'title': str(title or '').strip() or normalized_code,
            'avfan_url': str(avfan_url or '').strip(),
            'javtxt_url': str(javtxt_url or '').strip(),
            'javtxt_tags': str(javtxt_tags or '').strip(),
            'javtxt_enrichment_status': ENRICHED_STATUS,
            'manual_tier': manual_tier,
            'actor_count': count_video_actors(author),
        }
        if current is None:
            rows_by_code[normalized_code] = candidate
            return

        if not current.get('avfan_url') and candidate['avfan_url']:
            current['avfan_url'] = candidate['avfan_url']
        if not current.get('javtxt_url') and candidate['javtxt_url']:
            current['javtxt_url'] = candidate['javtxt_url']
        if not current.get('manual_tier') and candidate['manual_tier']:
            current['manual_tier'] = candidate['manual_tier']
            current['actor_count'] = candidate['actor_count']
        if not current.get('javtxt_tags') and candidate['javtxt_tags']:
            current['javtxt_tags'] = candidate['javtxt_tags']
        if (
            current.get('title', '').strip().upper() == normalized_code
            or len(current.get('title', '')) < len(candidate['title'])
        ):
            current['title'] = candidate['title']

    @staticmethod
    def _classify_manual_category_tier(author='', author_raw=''):
        tier = classify_manual_category_tier(author, author_raw)
        if tier in (
            MANUAL_CATEGORY_TIER_FIRST,
            MANUAL_CATEGORY_TIER_SECOND,
            MANUAL_CATEGORY_TIER_THIRD,
        ):
            return tier
        return ''

    def get_javtxt_actor_cache_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, javtxt_actors, javtxt_actors_raw, javtxt_movie_id, javtxt_url,
                       javtxt_tags, javtxt_enrichment_status, javtxt_release_date, release_date
                FROM processed_videos
                WHERE code IN ({placeholders})
                ''',
                normalized_codes,
            )
            rows = cursor.fetchall()

        return {
            (row[0] or ''): {
                'code': row[0] or '',
                'javtxt_actors': sanitize_actor_text(row[1] or ''),
                'javtxt_actors_raw': row[2] or '',
                'javtxt_movie_id': row[3] or '',
                'javtxt_url': row[4] or '',
                'javtxt_tags': row[5] or '',
                'javtxt_enrichment_status': row[6] or UNENRICHED_STATUS,
                'javtxt_release_date': row[7] or '',
                'release_date': row[8] or '',
            }
            for row in rows
        }

    def _is_processed_video_javtxt_eligible(self, cursor, code, info=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return False

        cursor.execute(
            '''
            SELECT COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date
            FROM processed_videos
            WHERE code = ?
            ''',
            (normalized_code,),
        )
        row = cursor.fetchone() or ('', '', '', '', '')
        candidate = {
            'code': normalized_code,
            'title': str((info or {}).get('javtxt_title', (info or {}).get('title', row[0] or normalized_code)) or '').strip(),
            'release_date': str((info or {}).get('release_date', row[1] or '') or '').strip(),
            'javtxt_tags': str((info or {}).get('javtxt_tags', row[2] or '') or '').strip(),
            'video_category': normalize_video_category((info or {}).get('video_category', row[3] or '')),
            'javtxt_release_date': str((info or {}).get('release_date', row[4] or '') or '').strip(),
        }
        return is_javtxt_eligible_movie(candidate)

    def _update_processed_video_javtxt_metadata(self, cursor, code, info=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        info = dict(info or {})
        cursor.execute(
            '''
            UPDATE processed_videos
            SET title = COALESCE(NULLIF(?, ''), title),
                javtxt_title = COALESCE(NULLIF(?, ''), javtxt_title),
                release_date = COALESCE(NULLIF(?, ''), release_date),
                maker = COALESCE(NULLIF(?, ''), maker),
                publisher = COALESCE(NULLIF(?, ''), publisher),
                javtxt_tags = COALESCE(NULLIF(?, ''), javtxt_tags),
                javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date)
            WHERE code = ?
            ''',
            (
                str(info.get('title', info.get('javtxt_title', '')) or '').strip(),
                str(info.get('javtxt_title', info.get('title', '')) or '').strip(),
                str(info.get('release_date', '') or '').strip(),
                join_values(info.get('maker')),
                join_values(info.get('publisher')),
                str(info.get('javtxt_tags', '') or '').strip(),
                str(info.get('release_date', '') or '').strip(),
                normalized_code,
            ),
        )

    @staticmethod
    def _resolve_ineligible_javtxt_status(status):
        normalized_status = str(status or '').strip()
        if is_no_result_status(normalized_status):
            return normalized_status
        return NO_SEARCH_RESULTS_STATUS

    def _mark_processed_video_javtxt_ineligible(self, cursor, code, status, error=''):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        cursor.execute(
            '''
            UPDATE processed_videos
            SET javtxt_movie_id = '',
                javtxt_url = '',
                javtxt_actors = '',
                javtxt_actors_raw = '',
                javtxt_enrichment_status = ?,
                javtxt_enrichment_error = ?,
                javtxt_enriched_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            (
                self._resolve_ineligible_javtxt_status(status),
                str(error or '').strip() or JAVTXT_INELIGIBLE_ERROR,
                normalized_code,
            ),
        )

    def _clear_processed_video_javtxt_state(self, cursor, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        cursor.execute(
            '''
            UPDATE processed_videos
            SET javtxt_movie_id = '',
                javtxt_url = '',
                javtxt_title = '',
                javtxt_actors = '',
                javtxt_actors_raw = '',
                javtxt_tags = '',
                javtxt_enrichment_status = ?,
                javtxt_enrichment_error = '',
                javtxt_enriched_at = NULL
            WHERE code = ?
            ''',
            (UNENRICHED_STATUS, normalized_code),
        )

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return 0
        payload = dict(info or {})
        if error and not payload.get('error'):
            payload['error'] = error
        normalized_javtxt = self._normalize_processed_video_javtxt_payload(payload, status)

        with self._connect() as conn:
            cursor = conn.cursor()
            if not self._is_processed_video_javtxt_eligible(cursor, normalized_code, info):
                self._update_processed_video_javtxt_metadata(cursor, normalized_code, info)
                self._refresh_video_category(
                    cursor,
                    normalized_code,
                    tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                    actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                )
                self._mark_processed_video_javtxt_ineligible(
                    cursor,
                    normalized_code,
                    normalized_javtxt['status'],
                    normalized_javtxt['error'],
                )
                self._refresh_combined_video_status(
                    cursor,
                    normalized_code,
                    normalized_javtxt['error'] or JAVTXT_INELIGIBLE_ERROR,
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [normalized_code])
                conn.commit()
                self._refresh_web_movie_parent_javtxt_statuses_for_codes([normalized_code])
                return 0
            cursor.execute(
                '''
                UPDATE processed_videos
                SET javtxt_movie_id = COALESCE(NULLIF(?, ''), javtxt_movie_id),
                    javtxt_url = COALESCE(NULLIF(?, ''), javtxt_url),
                    javtxt_title = COALESCE(NULLIF(?, ''), javtxt_title),
                    javtxt_actors = ?,
                    javtxt_actors_raw = ?,
                    javtxt_tags = COALESCE(NULLIF(?, ''), javtxt_tags),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = ?,
                    javtxt_enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (
                    normalized_javtxt['javtxt_movie_id'],
                    normalized_javtxt['javtxt_url'],
                    normalized_javtxt['javtxt_title'],
                    normalized_javtxt['sanitized_javtxt_actors'],
                    normalized_javtxt['raw_javtxt_actors'],
                    normalized_javtxt['sanitized_javtxt_tags'],
                    normalized_javtxt['release_date'],
                    normalized_javtxt['release_date'],
                    normalized_javtxt['status'],
                    normalized_javtxt['error'],
                    normalized_code,
                ),
            )
            updated_count = int(cursor.rowcount or 0)
            self._refresh_video_category(
                cursor,
                normalized_code,
                tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                actors_text=normalized_javtxt['sanitized_javtxt_actors'],
            )
            self._refresh_combined_video_status(cursor, normalized_code, normalized_javtxt['error'])
            self._propagate_processed_video_javtxt_state_for_codes(cursor, [normalized_code])
            conn.commit()
        self._refresh_web_movie_parent_javtxt_statuses_for_codes([normalized_code])
        return updated_count

    def import_local_videos(self, records):
        normalized_records = {}
        for record in records or []:
            code = standardize_video_code((record or {}).get('code', ''))
            if not code:
                continue
            normalized_records[code] = {
                'code': code,
                'storage_location': str((record or {}).get('storage_location', '') or '').strip(),
                'duration': str((record or {}).get('duration', '') or '').strip(),
                'size': str((record or {}).get('size', '') or '').strip(),
            }

        if not normalized_records:
            return 0

        codes = list(normalized_records.keys())
        existing_records = self.get_videos_by_codes(codes)
        new_records = [normalized_records[code] for code in codes if code not in existing_records]
        existing_updates = [normalized_records[code] for code in codes if code in existing_records]

        with self._connect() as conn:
            cursor = conn.cursor()

            if new_records:
                cursor.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code,
                        title,
                        author,
                        duration,
                        size,
                        storage_location,
                        enrichment_status,
                        avfan_enrichment_status,
                        javtxt_enrichment_status
                    )
                    VALUES (?, '', '', ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        (
                            record['code'],
                            record['duration'],
                            record['size'],
                            record['storage_location'],
                            build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                            UNENRICHED_STATUS,
                            UNENRICHED_STATUS,
                        )
                        for record in new_records
                    ],
                )

            if existing_updates:
                cursor.executemany(
                    '''
                    UPDATE processed_videos
                    SET duration = CASE WHEN ? <> '' THEN ? ELSE duration END,
                        size = CASE WHEN ? <> '' THEN ? ELSE size END,
                        storage_location = CASE WHEN ? <> '' THEN ? ELSE storage_location END
                    WHERE code = ?
                    ''',
                    [
                        (
                            record['duration'],
                            record['duration'],
                            record['size'],
                            record['size'],
                            record['storage_location'],
                            record['storage_location'],
                            record['code'],
                        )
                        for record in existing_updates
                    ],
                )

            conn.commit()

        return len(new_records)
