import json
import re
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    PENDING_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
)
from app.core.library_refresh_expiry import is_library_refresh_expired
from app.core.operation_timeout_settings import (
    ensure_operation_timeout_settings_table,
    get_operation_timeout_seconds,
)
from app.core.actor_profile_completion_status import (
    build_actor_final_completion_status,
    build_actor_source_completion_status,
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
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.core.project_paths import DATABASE_FILE
from app.core.video_filter_rules import (
    FILTER_FIELD_CO_STAR_CODE,
    RuleSet,
    get_filter_keywords,
    matches_filter_keywords,
    should_skip_video_before_enrichment,
    should_hide_video_from_library,
)
from app.core.video_filter_settings import load_video_filter_settings
from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_ENTITY_ACTOR,
    normalize_ladder_medal_text,
    split_ladder_medals,
)
from app.core.medal_types import normalize_medal_type, sort_medal_rows
from app.core.runtime_config import get_avfan_base_url
from app.data.repositories import (
    ActorRepositoryMixin,
    CandidateLibraryRepositoryMixin,
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
    CandidateLibraryRepositoryMixin,
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
    def _connect(self, timeout_seconds=None):
        try:
            if timeout_seconds is None:
                timeout_seconds = get_operation_timeout_seconds('database_wait', self.db_path)
        except Exception:
            timeout_seconds = 60
        conn = sqlite3.connect(self.db_path, timeout=timeout_seconds)
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute(f'PRAGMA busy_timeout = {max(1, int(timeout_seconds * 1000))}')
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
            self._ensure_enrichment_batch_plan_tables(cursor)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actors (
                    name TEXT PRIMARY KEY,
                    birthday TEXT,
                    age TEXT,
                    matched INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS canglangge_actor_candidates (
                    actor_name TEXT PRIMARY KEY,
                    source_prefixes_json TEXT NOT NULL DEFAULT '[]',
                    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    binghuo_enrichment_status TEXT NOT NULL DEFAULT 'UNENRICHED',
                    binghuo_completion_status TEXT NOT NULL DEFAULT '状态1',
                    binghuo_last_error TEXT NOT NULL DEFAULT '',
                    binghuo_last_enriched_at TEXT,
                    binghuo_person_id TEXT NOT NULL DEFAULT '',
                    binghuo_birthday TEXT NOT NULL DEFAULT '',
                    binghuo_age TEXT NOT NULL DEFAULT '',
                    binghuo_height TEXT NOT NULL DEFAULT '',
                    binghuo_bust TEXT NOT NULL DEFAULT '',
                    binghuo_cup TEXT NOT NULL DEFAULT '',
                    binghuo_measurements_raw TEXT NOT NULL DEFAULT '',
                    binghuo_waist TEXT NOT NULL DEFAULT '',
                    binghuo_hip TEXT NOT NULL DEFAULT '',
                    baomu_enrichment_status TEXT NOT NULL DEFAULT 'UNENRICHED',
                    baomu_completion_status TEXT NOT NULL DEFAULT '状态1',
                    baomu_last_error TEXT NOT NULL DEFAULT '',
                    baomu_last_enriched_at TEXT,
                    baomu_birthday TEXT NOT NULL DEFAULT '',
                    baomu_height TEXT NOT NULL DEFAULT '',
                    baomu_bust TEXT NOT NULL DEFAULT '',
                    baomu_cup TEXT NOT NULL DEFAULT '',
                    baomu_measurements_raw TEXT NOT NULL DEFAULT '',
                    baomu_waist TEXT NOT NULL DEFAULT '',
                    baomu_hip TEXT NOT NULL DEFAULT '',
                    candidate_status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self._ensure_column(cursor, 'canglangge_actor_candidates', 'binghuo_completion_status', "TEXT NOT NULL DEFAULT '状态1'")
            self._ensure_column(cursor, 'canglangge_actor_candidates', 'baomu_completion_status', "TEXT NOT NULL DEFAULT '状态1'")
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_canglangge_actor_candidate_status '
                'ON canglangge_actor_candidates (binghuo_enrichment_status, baomu_enrichment_status, candidate_status)'
            )
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
                    medal_type TEXT NOT NULL DEFAULT 'special',
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
                CREATE TABLE IF NOT EXISTS excluded_code_prefix_movies (
                    prefix TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    javtxt_enrichment_status TEXT DEFAULT '',
                    javtxt_movie_id TEXT,
                    javtxt_url TEXT,
                    javtxt_tags TEXT,
                    javtxt_release_date TEXT,
                    author_raw TEXT,
                    video_category TEXT,
                    supplement_enrichment_status TEXT DEFAULT '',
                    supplement_enrichment_error TEXT DEFAULT '',
                    supplement_enriched_at TEXT,
                    exclude_reason TEXT NOT NULL DEFAULT '',
                    excluded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (prefix, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS excluded_actor_movies (
                    actor_name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    javtxt_enrichment_status TEXT DEFAULT '',
                    javtxt_movie_id TEXT,
                    javtxt_url TEXT,
                    javtxt_tags TEXT,
                    javtxt_release_date TEXT,
                    author_raw TEXT,
                    video_category TEXT,
                    supplement_enrichment_status TEXT DEFAULT '',
                    supplement_enrichment_error TEXT DEFAULT '',
                    supplement_enriched_at TEXT,
                    exclude_reason TEXT NOT NULL DEFAULT '',
                    excluded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (actor_name, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS data_source_versions (
                    source_key TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS snapshot_registry (
                    snapshot_key TEXT PRIMARY KEY,
                    source_keys TEXT NOT NULL DEFAULT '',
                    source_version TEXT NOT NULL DEFAULT '',
                    filter_fingerprint TEXT NOT NULL DEFAULT '',
                    dirty INTEGER NOT NULL DEFAULT 1,
                    last_built_at TEXT NOT NULL DEFAULT '',
                    last_accessed_at TEXT NOT NULL DEFAULT '',
                    refresh_duration_ms INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_library_summary (
                    actor_name TEXT PRIMARY KEY,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    eligible_video_count INTEGER NOT NULL DEFAULT 0,
                    latest_release_date TEXT NOT NULL DEFAULT '',
                    avfan_enrichment_status TEXT NOT NULL DEFAULT '',
                    javtxt_enrichment_status TEXT NOT NULL DEFAULT '',
                    profile_completion_status TEXT NOT NULL DEFAULT '',
                    source_version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_prefix_library_summary (
                    prefix TEXT PRIMARY KEY,
                    local_video_count INTEGER NOT NULL DEFAULT 0,
                    web_video_count INTEGER NOT NULL DEFAULT 0,
                    eligible_video_count INTEGER NOT NULL DEFAULT 0,
                    earliest_release_date TEXT NOT NULL DEFAULT '',
                    latest_release_date TEXT NOT NULL DEFAULT '',
                    avfan_enrichment_status TEXT NOT NULL DEFAULT '',
                    javtxt_enrichment_status TEXT NOT NULL DEFAULT '',
                    source_version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS enrichment_candidate_index (
                    target_kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    owner_key TEXT NOT NULL DEFAULT '',
                    code TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 0,
                    candidate_status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT '',
                    source_version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (target_kind, source_key, owner_key, code)
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
                INSERT OR IGNORE INTO hidden_actors (name)
                SELECT actor_name
                FROM masterpiece_actors
                WHERE COALESCE(handle_mark, 0) = 2
                  AND COALESCE(actor_name, '') <> ''
                '''
            )
            cursor.execute(
                'DELETE FROM masterpiece_actors WHERE COALESCE(handle_mark, 0) = 2'
            )
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS candidate_actor_records (
                    actor_name TEXT PRIMARY KEY,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS candidate_code_prefix_records (
                    prefix TEXT PRIMARY KEY,
                    video_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self._ensure_index(
                cursor,
                'idx_candidate_actor_records_video_count',
                'candidate_actor_records',
                'video_count DESC, actor_name',
            )
            self._ensure_index(
                cursor,
                'idx_candidate_code_prefix_records_video_count',
                'candidate_code_prefix_records',
                'video_count DESC, prefix',
            )
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
            self._ensure_library_refresh_tracking_tables(cursor)
            ensure_operation_timeout_settings_table(cursor)
            self._ensure_column(cursor, 'ladder_entries', 'tier', 'TEXT NOT NULL DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'medal', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'ladder_entries', 'updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'global_medals', 'description', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'global_medals', 'medal_type', "TEXT NOT NULL DEFAULT 'special'")
            self._ensure_column(cursor, 'global_medals', 'created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'global_medals', 'updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            cursor.execute(
                "UPDATE global_medals SET medal_type = 'special' WHERE TRIM(COALESCE(medal_type, '')) = ''"
            )
            self._ensure_index(cursor, 'idx_usb_video_inventory_folder', 'usb_video_inventory', 'folder_path, video_code')
            self._ensure_index(cursor, 'idx_usb_video_change_logs_folder', 'usb_video_change_logs', 'folder_path, created_at')
            self._ensure_index(cursor, 'idx_excluded_code_prefix_movies_code', 'excluded_code_prefix_movies', 'code')
            self._ensure_index(cursor, 'idx_excluded_actor_movies_code', 'excluded_actor_movies', 'code')
            self._ensure_index(cursor, 'idx_snapshot_registry_dirty', 'snapshot_registry', 'dirty, snapshot_key')
            self._ensure_index(cursor, 'idx_actor_library_summary_release', 'actor_library_summary', 'latest_release_date, actor_name')
            self._ensure_index(cursor, 'idx_code_prefix_library_summary_release', 'code_prefix_library_summary', 'latest_release_date, prefix')
            self._ensure_index(cursor, 'idx_enrichment_candidate_index_status', 'enrichment_candidate_index', 'target_kind, source_key, candidate_status, priority, updated_at')
            self._ensure_column(cursor, 'enrichment_candidate_index', 'candidate_fingerprint', 'TEXT NOT NULL DEFAULT ""')
            self._ensure_column(cursor, 'enrichment_candidate_index', 'candidate_payload', 'TEXT NOT NULL DEFAULT ""')
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
            self._migrate_enrichment_status_values(cursor)
            self._ensure_video_entity_tables(cursor)
            for column_name, column_type in (
                ('enrichment_status', "TEXT NOT NULL DEFAULT ''"),
                ('enrichment_error', "TEXT NOT NULL DEFAULT ''"),
                ('enriched_at', "TEXT NOT NULL DEFAULT ''"),
                ('avfan_enrichment_status', "TEXT NOT NULL DEFAULT ''"),
                ('avfan_enrichment_error', "TEXT NOT NULL DEFAULT ''"),
                ('avfan_enriched_at', "TEXT NOT NULL DEFAULT ''"),
                ('javtxt_enrichment_error', "TEXT NOT NULL DEFAULT ''"),
                ('javtxt_enriched_at', "TEXT NOT NULL DEFAULT ''"),
                ('description', "TEXT NOT NULL DEFAULT ''"),
                ('javtxt_description', "TEXT NOT NULL DEFAULT ''"),
                ('avfan_actors', "TEXT NOT NULL DEFAULT ''"),
                ('avfan_tags', "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(cursor, 'video_entities', column_name, column_type)
            self._backfill_legacy_supplement_links(cursor)
            legacy_objects = cursor.execute(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE name IN ('processed_videos', 'actor_movies', 'code_prefix_movies')
                ORDER BY name
                """
            ).fetchall()
            if legacy_objects:
                names = ', '.join(str(row[0]) for row in legacy_objects)
                raise RuntimeError(
                    f'检测到未完成迁移的旧数据库对象: {names}。'
                    '请先运行 scripts/migrate_video_entity_views.py'
                )
            conn.commit()

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
            'CREATE INDEX IF NOT EXISTS idx_video_actor_relation_meta_actor '
            'ON video_actor_relation_meta (actor_name, video_code)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_video_prefix_relation_meta_prefix '
            'ON video_prefix_relation_meta (prefix, video_code)'
        )
        return
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_actor_movies_sync_video_entity
            AFTER INSERT ON actor_movies
            BEGIN
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, avfan_url,
                    javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                    javtxt_enrichment_status, javtxt_actors_raw, video_category,
                    supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                ) VALUES (
                    NEW.code, COALESCE(NEW.title, ''), COALESCE(NEW.author, ''), COALESCE(NEW.release_date, ''), COALESCE(NEW.avfan_url, ''),
                    COALESCE(NEW.javtxt_movie_id, ''), COALESCE(NEW.javtxt_url, ''), COALESCE(NEW.javtxt_tags, ''), COALESCE(NEW.javtxt_release_date, ''),
                    COALESCE(NEW.javtxt_enrichment_status, ''), COALESCE(NEW.author_raw, ''), COALESCE(NEW.video_category, ''),
                    COALESCE(NEW.supplement_enrichment_status, ''), COALESCE(NEW.supplement_enrichment_error, ''), COALESCE(NEW.supplement_enriched_at, '')
                );
                INSERT OR IGNORE INTO video_actor_relations (video_code, actor_name)
                VALUES (NEW.code, NEW.actor_name);
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_processed_videos_sync_video_entity
            AFTER INSERT ON processed_videos
            BEGIN
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, maker, publisher, avfan_movie_id,
                    javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_actors_raw,
                    javtxt_tags, javtxt_release_date, javtxt_enrichment_status, video_category,
                    supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                ) VALUES (
                    NEW.code, COALESCE(NEW.title, ''), COALESCE(NEW.author, ''), COALESCE(NEW.release_date, ''),
                    COALESCE(NEW.maker, ''), COALESCE(NEW.publisher, ''), COALESCE(NEW.avfan_movie_id, ''),
                    COALESCE(NEW.javtxt_movie_id, ''), COALESCE(NEW.javtxt_url, ''), COALESCE(NEW.javtxt_title, ''),
                    COALESCE(NEW.javtxt_actors, ''), COALESCE(NEW.javtxt_actors_raw, ''), COALESCE(NEW.javtxt_tags, ''),
                    COALESCE(NEW.javtxt_release_date, ''), COALESCE(NEW.javtxt_enrichment_status, ''), COALESCE(NEW.video_category, ''),
                    COALESCE(NEW.supplement_enrichment_status, ''), COALESCE(NEW.supplement_enrichment_error, ''), COALESCE(NEW.supplement_enriched_at, '')
                );
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_processed_videos_update_video_entity
            AFTER UPDATE ON processed_videos
            BEGIN
                UPDATE video_entities
                SET title = COALESCE(NEW.title, ''), author = COALESCE(NEW.author, ''),
                    release_date = COALESCE(NEW.release_date, ''), maker = COALESCE(NEW.maker, ''),
                    publisher = COALESCE(NEW.publisher, ''), avfan_movie_id = COALESCE(NEW.avfan_movie_id, ''),
                    javtxt_movie_id = COALESCE(NEW.javtxt_movie_id, ''), javtxt_url = COALESCE(NEW.javtxt_url, ''),
                    javtxt_title = COALESCE(NEW.javtxt_title, ''), javtxt_actors = COALESCE(NEW.javtxt_actors, ''),
                    javtxt_actors_raw = COALESCE(NEW.javtxt_actors_raw, ''), javtxt_tags = COALESCE(NEW.javtxt_tags, ''),
                    javtxt_release_date = COALESCE(NEW.javtxt_release_date, ''),
                    javtxt_enrichment_status = COALESCE(NEW.javtxt_enrichment_status, ''),
                    video_category = COALESCE(NEW.video_category, ''),
                    supplement_enrichment_status = COALESCE(NEW.supplement_enrichment_status, ''),
                    supplement_enrichment_error = COALESCE(NEW.supplement_enrichment_error, ''),
                    supplement_enriched_at = COALESCE(NEW.supplement_enriched_at, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = NEW.code;
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_code_prefix_movies_sync_video_entity
            AFTER INSERT ON code_prefix_movies
            BEGIN
                INSERT OR IGNORE INTO video_entities (
                    code, title, author, release_date, avfan_url,
                    javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                    javtxt_enrichment_status, javtxt_actors_raw, video_category,
                    supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                ) VALUES (
                    NEW.code, COALESCE(NEW.title, ''), COALESCE(NEW.author, ''), COALESCE(NEW.release_date, ''), COALESCE(NEW.avfan_url, ''),
                    COALESCE(NEW.javtxt_movie_id, ''), COALESCE(NEW.javtxt_url, ''), COALESCE(NEW.javtxt_tags, ''), COALESCE(NEW.javtxt_release_date, ''),
                    COALESCE(NEW.javtxt_enrichment_status, ''), COALESCE(NEW.author_raw, ''), COALESCE(NEW.video_category, ''),
                    COALESCE(NEW.supplement_enrichment_status, ''), COALESCE(NEW.supplement_enrichment_error, ''), COALESCE(NEW.supplement_enriched_at, '')
                );
                INSERT OR IGNORE INTO video_code_prefix_relations (video_code, prefix)
                VALUES (NEW.code, NEW.prefix);
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_actor_movies_remove_video_relation
            AFTER DELETE ON actor_movies
            BEGIN
                DELETE FROM video_actor_relations
                WHERE video_code = OLD.code
                  AND actor_name = OLD.actor_name
                  AND NOT EXISTS (
                      SELECT 1 FROM actor_movies
                      WHERE code = OLD.code AND actor_name = OLD.actor_name
                  );
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_actor_movies_update_video_entity
            AFTER UPDATE ON actor_movies
            BEGIN
                UPDATE video_entities
                SET title = COALESCE(NEW.title, ''), author = COALESCE(NEW.author, ''),
                    release_date = COALESCE(NEW.release_date, ''), avfan_url = COALESCE(NEW.avfan_url, ''),
                    javtxt_movie_id = COALESCE(NEW.javtxt_movie_id, ''), javtxt_url = COALESCE(NEW.javtxt_url, ''),
                    javtxt_tags = COALESCE(NEW.javtxt_tags, ''), javtxt_release_date = COALESCE(NEW.javtxt_release_date, ''),
                    javtxt_enrichment_status = COALESCE(NEW.javtxt_enrichment_status, ''),
                    javtxt_actors_raw = COALESCE(NEW.author_raw, ''), video_category = COALESCE(NEW.video_category, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = NEW.code;
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_code_prefix_movies_remove_video_relation
            AFTER DELETE ON code_prefix_movies
            BEGIN
                DELETE FROM video_code_prefix_relations
                WHERE video_code = OLD.code
                  AND prefix = OLD.prefix
                  AND NOT EXISTS (
                      SELECT 1 FROM code_prefix_movies
                      WHERE code = OLD.code AND prefix = OLD.prefix
                  );
            END
            '''
        )
        cursor.execute(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_code_prefix_movies_update_video_entity
            AFTER UPDATE ON code_prefix_movies
            BEGIN
                UPDATE video_entities
                SET title = COALESCE(NEW.title, ''), author = COALESCE(NEW.author, ''),
                    release_date = COALESCE(NEW.release_date, ''), avfan_url = COALESCE(NEW.avfan_url, ''),
                    javtxt_movie_id = COALESCE(NEW.javtxt_movie_id, ''), javtxt_url = COALESCE(NEW.javtxt_url, ''),
                    javtxt_tags = COALESCE(NEW.javtxt_tags, ''), javtxt_release_date = COALESCE(NEW.javtxt_release_date, ''),
                    javtxt_enrichment_status = COALESCE(NEW.javtxt_enrichment_status, ''),
                    javtxt_actors_raw = COALESCE(NEW.author_raw, ''), video_category = COALESCE(NEW.video_category, ''),
                    updated_at = CURRENT_TIMESTAMP
                WHERE code = NEW.code;
            END
            '''
        )

    def _migrate_video_entities(self, cursor):
        fields = (
            'title', 'author', 'release_date', 'maker', 'publisher', 'avfan_url',
            'avfan_movie_id', 'javtxt_movie_id', 'javtxt_url', 'javtxt_title',
            'javtxt_actors', 'javtxt_actors_raw', 'javtxt_tags', 'javtxt_release_date',
            'javtxt_enrichment_status', 'video_category', 'supplement_enrichment_status', 'supplement_enrichment_error',
            'supplement_enriched_at',
        )
        entities = {}
        actor_relations = set()
        prefix_relations = set()

        for row in cursor.execute(
            f'SELECT code, {", ".join(fields)} FROM video_entities'
        ).fetchall():
            code = standardize_video_code(row[0])
            if code:
                entities[code] = {'code': code, **dict(zip(fields, row[1:]))}

        def merge_entity(code_value, values):
            code = standardize_video_code(code_value)
            if not code:
                return
            entity = entities.setdefault(code, {'code': code, **{field: '' for field in fields}})
            for field in fields:
                value = str(values.get(field, '') or '').strip()
                existing = str(entity.get(field, '') or '').strip()
                if field == 'supplement_enrichment_status':
                    if value == ENRICHED_STATUS or not existing or existing == UNENRICHED_STATUS:
                        if value:
                            entity[field] = value
                elif value and (not existing or (field == 'title' and existing == code and value != code)):
                    entity[field] = value
            return code

        for row in cursor.execute(
            '''
            SELECT code, title, author, release_date, maker, publisher,
                   avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title,
                   javtxt_actors, javtxt_actors_raw, javtxt_tags, javtxt_release_date,
                   javtxt_enrichment_status, video_category, supplement_enrichment_status,
                   supplement_enrichment_error, supplement_enriched_at
            FROM processed_videos
            '''
        ).fetchall():
            merge_entity(row[0], dict(zip(
                ('title', 'author', 'release_date', 'maker', 'publisher', 'avfan_movie_id',
                 'javtxt_movie_id', 'javtxt_url', 'javtxt_title', 'javtxt_actors',
                 'javtxt_actors_raw', 'javtxt_tags', 'javtxt_release_date', 'javtxt_enrichment_status', 'video_category',
                 'supplement_enrichment_status', 'supplement_enrichment_error', 'supplement_enriched_at'),
                row[1:],
            )))

        for row in cursor.execute(
            '''
            SELECT actor_name, code, title, author, release_date, avfan_url,
                   javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                   javtxt_enrichment_status, author_raw, video_category, supplement_enrichment_status,
                   supplement_enrichment_error, supplement_enriched_at
            FROM actor_movies
            '''
        ).fetchall():
            code = merge_entity(row[1], {
                'title': row[2], 'author': row[3], 'release_date': row[4], 'avfan_url': row[5],
                'javtxt_movie_id': row[6], 'javtxt_url': row[7], 'javtxt_tags': row[8],
                'javtxt_release_date': row[9], 'javtxt_enrichment_status': row[10],
                'javtxt_actors_raw': row[11], 'video_category': row[12],
                'supplement_enrichment_status': row[13],
                'supplement_enrichment_error': row[14], 'supplement_enriched_at': row[15],
            })
            actor_name = str(row[0] or '').strip()
            if code and actor_name:
                actor_relations.add((code, actor_name))

        for row in cursor.execute(
            '''
            SELECT prefix, code, title, author, release_date, avfan_url,
                   javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                   javtxt_enrichment_status, author_raw, video_category, supplement_enrichment_status,
                   supplement_enrichment_error, supplement_enriched_at
            FROM code_prefix_movies
            '''
        ).fetchall():
            code = merge_entity(row[1], {
                'title': row[2], 'author': row[3], 'release_date': row[4], 'avfan_url': row[5],
                'javtxt_movie_id': row[6], 'javtxt_url': row[7], 'javtxt_tags': row[8],
                'javtxt_release_date': row[9], 'javtxt_enrichment_status': row[10],
                'javtxt_actors_raw': row[11], 'video_category': row[12],
                'supplement_enrichment_status': row[13],
                'supplement_enrichment_error': row[14], 'supplement_enriched_at': row[15],
            })
            prefix = str(row[0] or '').strip().upper()
            if code and prefix:
                prefix_relations.add((code, prefix))

        if entities:
            cursor.executemany(
                f'''
                INSERT OR REPLACE INTO video_entities ({', '.join(('code', *fields))})
                VALUES ({', '.join('?' for _ in ('code', *fields))})
                ''',
                [tuple(entity.get(field, '') or '' for field in ('code', *fields)) for entity in entities.values()],
            )
        cursor.executemany(
            'INSERT OR IGNORE INTO video_actor_relations (video_code, actor_name) VALUES (?, ?)',
            sorted(actor_relations),
        )
        cursor.executemany(
            'INSERT OR IGNORE INTO video_code_prefix_relations (video_code, prefix) VALUES (?, ?)',
            sorted(prefix_relations),
        )
        cursor.execute(
            '''
            UPDATE video_entities
            SET enrichment_status = COALESCE((SELECT enrichment_status FROM processed_videos p WHERE p.code = video_entities.code), enrichment_status),
                enrichment_error = COALESCE((SELECT enrichment_error FROM processed_videos p WHERE p.code = video_entities.code), enrichment_error),
                enriched_at = COALESCE((SELECT enriched_at FROM processed_videos p WHERE p.code = video_entities.code), enriched_at),
                avfan_enrichment_status = COALESCE((SELECT avfan_enrichment_status FROM processed_videos p WHERE p.code = video_entities.code), avfan_enrichment_status),
                avfan_enrichment_error = COALESCE((SELECT avfan_enrichment_error FROM processed_videos p WHERE p.code = video_entities.code), avfan_enrichment_error),
                avfan_enriched_at = COALESCE((SELECT avfan_enriched_at FROM processed_videos p WHERE p.code = video_entities.code), avfan_enriched_at),
                javtxt_enrichment_error = COALESCE((SELECT javtxt_enrichment_error FROM processed_videos p WHERE p.code = video_entities.code), javtxt_enrichment_error),
                javtxt_enriched_at = COALESCE((SELECT javtxt_enriched_at FROM processed_videos p WHERE p.code = video_entities.code), javtxt_enriched_at),
                description = COALESCE((SELECT description FROM processed_videos p WHERE p.code = video_entities.code), description),
                javtxt_description = COALESCE((SELECT javtxt_description FROM processed_videos p WHERE p.code = video_entities.code), javtxt_description),
                avfan_actors = COALESCE((SELECT avfan_actors FROM processed_videos p WHERE p.code = video_entities.code), avfan_actors),
                avfan_tags = COALESCE((SELECT avfan_tags FROM processed_videos p WHERE p.code = video_entities.code), avfan_tags)
            '''
        )
        cursor.execute(
            '''
            INSERT OR IGNORE INTO video_actor_relation_meta (
                video_code, actor_name, avfan_url, avfan_movie_id, page_number
            )
            SELECT code, actor_name, COALESCE(avfan_url, ''), COALESCE(javtxt_movie_id, ''),
                   COALESCE(page_number, 1)
            FROM actor_movies
            '''
        )
        cursor.execute(
            '''
            UPDATE video_actor_relation_meta
            SET avfan_url = COALESCE(NULLIF((SELECT avfan_url FROM actor_movies s WHERE s.code = video_code AND s.actor_name = video_actor_relation_meta.actor_name), ''), avfan_url),
                avfan_movie_id = COALESCE(NULLIF((SELECT javtxt_movie_id FROM actor_movies s WHERE s.code = video_code AND s.actor_name = video_actor_relation_meta.actor_name), ''), avfan_movie_id),
                page_number = COALESCE((SELECT page_number FROM actor_movies s WHERE s.code = video_code AND s.actor_name = video_actor_relation_meta.actor_name), page_number)
            '''
        )
        cursor.execute(
            '''
            INSERT OR IGNORE INTO video_prefix_relation_meta (
                video_code, prefix, avfan_url, avfan_movie_id, page_number
            )
            SELECT code, UPPER(prefix), COALESCE(avfan_url, ''), COALESCE(javtxt_movie_id, ''),
                   COALESCE(page_number, 1)
            FROM code_prefix_movies
            '''
        )
        cursor.execute(
            '''
            UPDATE video_prefix_relation_meta
            SET avfan_url = COALESCE(NULLIF((SELECT avfan_url FROM code_prefix_movies s WHERE s.code = video_code AND UPPER(s.prefix) = video_prefix_relation_meta.prefix), ''), avfan_url),
                avfan_movie_id = COALESCE(NULLIF((SELECT javtxt_movie_id FROM code_prefix_movies s WHERE s.code = video_code AND UPPER(s.prefix) = video_prefix_relation_meta.prefix), ''), avfan_movie_id),
                page_number = COALESCE((SELECT page_number FROM code_prefix_movies s WHERE s.code = video_code AND UPPER(s.prefix) = video_prefix_relation_meta.prefix), page_number)
            '''
        )
        cursor.execute(
            '''
            INSERT OR IGNORE INTO local_video_records (code, duration, size, storage_location)
            SELECT code, COALESCE(duration, ''), COALESCE(size, ''), COALESCE(storage_location, '')
            FROM processed_videos
            '''
        )
        cursor.execute(
            '''
            UPDATE local_video_records
            SET duration = COALESCE(NULLIF((SELECT duration FROM processed_videos s WHERE s.code = local_video_records.code), ''), duration),
                size = COALESCE(NULLIF((SELECT size FROM processed_videos s WHERE s.code = local_video_records.code), ''), size),
                storage_location = COALESCE(NULLIF((SELECT storage_location FROM processed_videos s WHERE s.code = local_video_records.code), ''), storage_location),
                updated_at = CURRENT_TIMESTAMP
            '''
        )

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
        return normalized_code

    def convert_legacy_tables_to_compatibility_views(self):
        """Replace legacy movie tables with read-only canonical compatibility views.

        The renamed tables are retained as rollback snapshots. This operation is
        intentionally explicit so normal startup never changes a user's schema.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_video_entity_compatibility_columns(cursor)
            for table_name in ('processed_videos', 'actor_movies', 'code_prefix_movies'):
                object_row = cursor.execute(
                    'SELECT type FROM sqlite_master WHERE name = ?', (table_name,)
                ).fetchone()
                if object_row and object_row[0] == 'table':
                    backup_name = f'{table_name}_legacy_backup'
                    if not cursor.execute(
                        'SELECT 1 FROM sqlite_master WHERE name = ?', (backup_name,)
                    ).fetchone():
                        cursor.execute(f'ALTER TABLE {table_name} RENAME TO {backup_name}')

            source_table = 'processed_videos_legacy_backup'
            if cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (source_table,),
            ).fetchone():
                self._backfill_video_entity_compatibility_columns(cursor, source_table)

            cursor.execute(
                '''
                CREATE VIEW IF NOT EXISTS actor_movies AS
                SELECT r.actor_name AS actor_name, e.code AS code, e.title AS title, e.author AS author, e.release_date AS release_date,
                       COALESCE(m.avfan_url, '') AS avfan_url, COALESCE(m.page_number, 1) AS page_number, '' AS description,
                       e.javtxt_enrichment_status AS javtxt_enrichment_status, e.javtxt_movie_id AS javtxt_movie_id, e.javtxt_url AS javtxt_url,
                       e.video_category AS video_category, e.javtxt_actors_raw AS author_raw, e.javtxt_tags AS javtxt_tags,
                       e.javtxt_release_date AS javtxt_release_date, e.supplement_enrichment_status AS supplement_enrichment_status,
                       e.supplement_enrichment_error AS supplement_enrichment_error, e.supplement_enriched_at AS supplement_enriched_at
                FROM video_actor_relations r
                JOIN video_entities e ON e.code = r.video_code
                LEFT JOIN video_actor_relation_meta m
                  ON m.video_code = r.video_code AND m.actor_name = r.actor_name
                '''
            )
            cursor.execute(
                '''
                CREATE VIEW IF NOT EXISTS code_prefix_movies AS
                SELECT r.prefix AS prefix, e.code AS code, e.title AS title, e.author AS author, e.release_date AS release_date,
                       COALESCE(m.avfan_url, '') AS avfan_url, COALESCE(m.page_number, 1) AS page_number, '' AS description,
                       e.javtxt_enrichment_status AS javtxt_enrichment_status, e.javtxt_movie_id AS javtxt_movie_id, e.javtxt_url AS javtxt_url,
                       e.video_category AS video_category, e.javtxt_actors_raw AS author_raw, e.javtxt_tags AS javtxt_tags,
                       e.javtxt_release_date AS javtxt_release_date, e.supplement_enrichment_status AS supplement_enrichment_status,
                       e.supplement_enrichment_error AS supplement_enrichment_error, e.supplement_enriched_at AS supplement_enriched_at
                FROM video_code_prefix_relations r
                JOIN video_entities e ON e.code = r.video_code
                LEFT JOIN video_prefix_relation_meta m
                  ON m.video_code = r.video_code AND m.prefix = r.prefix
                '''
            )
            cursor.execute(
                '''
                CREATE VIEW IF NOT EXISTS processed_videos AS
                SELECT e.code, e.title, e.author,
                       COALESCE(l.duration, '') AS duration, COALESCE(l.size, '') AS size,
                       COALESCE(l.storage_location, '') AS storage_location, e.avfan_movie_id,
                       e.release_date, e.maker, e.publisher,
                       e.enrichment_status AS enrichment_status, e.enrichment_error AS enrichment_error, e.enriched_at AS enriched_at,
                       e.javtxt_movie_id, e.javtxt_url, e.javtxt_title,
                       e.javtxt_actors, e.avfan_enrichment_status AS avfan_enrichment_status,
                       e.avfan_enrichment_error AS avfan_enrichment_error, e.avfan_enriched_at AS avfan_enriched_at,
                       e.javtxt_enrichment_status, e.javtxt_enrichment_error AS javtxt_enrichment_error,
                       e.javtxt_enriched_at AS javtxt_enriched_at, e.javtxt_tags, e.description AS description,
                       e.video_category, e.javtxt_actors_raw, e.javtxt_release_date,
                       e.supplement_enrichment_status, e.supplement_enrichment_error,
                       e.supplement_enriched_at, e.javtxt_description AS javtxt_description,
                       e.avfan_actors AS avfan_actors, e.avfan_tags AS avfan_tags
                FROM video_entities e
                LEFT JOIN local_video_records l ON l.code = e.code
                '''
            )
            for trigger_name in (
                'trg_actor_movies_view_insert',
                'trg_actor_movies_view_update',
                'trg_actor_movies_view_delete',
                'trg_code_prefix_movies_view_insert',
                'trg_code_prefix_movies_view_update',
                'trg_code_prefix_movies_view_delete',
                'trg_processed_videos_view_insert',
                'trg_processed_videos_view_update',
                'trg_processed_videos_view_delete',
            ):
                cursor.execute(f'DROP TRIGGER IF EXISTS {trigger_name}')
            self._create_compatibility_view_triggers(cursor)
            conn.commit()

    def finalize_legacy_schema(self):
        """Migrate any remaining legacy movie objects, then remove them permanently."""
        legacy_names = ('processed_videos', 'actor_movies', 'code_prefix_movies')
        backup_names = tuple(f'{name}_legacy_backup' for name in legacy_names)
        with self._connect() as conn:
            cursor = conn.cursor()
            self._ensure_video_entity_compatibility_columns(cursor)
            if any(
                cursor.execute(
                    'SELECT 1 FROM sqlite_master WHERE name = ?', (name,)
                ).fetchone()
                for name in legacy_names
            ):
                self._migrate_video_entities(cursor)

            for name in legacy_names:
                object_row = cursor.execute(
                    'SELECT type FROM sqlite_master WHERE name = ?', (name,)
                ).fetchone()
                if not object_row:
                    continue
                if object_row[0] == 'view':
                    cursor.execute(f'DROP VIEW {name}')
                elif object_row[0] == 'table':
                    cursor.execute(f'DROP TABLE {name}')

            for name in backup_names:
                cursor.execute(f'DROP TABLE IF EXISTS {name}')

            trigger_rows = cursor.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger'
                  AND (
                      name LIKE 'trg_processed_videos%'
                      OR name LIKE 'trg_actor_movies%'
                      OR name LIKE 'trg_code_prefix_movies%'
                  )
                """
            ).fetchall()
            for (trigger_name,) in trigger_rows:
                cursor.execute(f'DROP TRIGGER IF EXISTS {trigger_name}')
            conn.commit()

    @staticmethod
    def _ensure_video_entity_compatibility_columns(cursor):
        columns = {
            str(row[1] or '').strip()
            for row in cursor.execute('PRAGMA table_info(video_entities)').fetchall()
        }
        for column_name, column_type in (
            ('enrichment_status', "TEXT NOT NULL DEFAULT ''"),
            ('enrichment_error', "TEXT NOT NULL DEFAULT ''"),
            ('enriched_at', "TEXT NOT NULL DEFAULT ''"),
            ('avfan_enrichment_status', "TEXT NOT NULL DEFAULT ''"),
            ('avfan_enrichment_error', "TEXT NOT NULL DEFAULT ''"),
            ('avfan_enriched_at', "TEXT NOT NULL DEFAULT ''"),
            ('javtxt_enrichment_error', "TEXT NOT NULL DEFAULT ''"),
            ('javtxt_enriched_at', "TEXT NOT NULL DEFAULT ''"),
            ('description', "TEXT NOT NULL DEFAULT ''"),
            ('javtxt_description', "TEXT NOT NULL DEFAULT ''"),
            ('avfan_actors', "TEXT NOT NULL DEFAULT ''"),
            ('avfan_tags', "TEXT NOT NULL DEFAULT ''"),
        ):
            if column_name not in columns:
                cursor.execute(f'ALTER TABLE video_entities ADD COLUMN {column_name} {column_type}')

    @staticmethod
    def _legacy_table_name(cursor, name):
        row = cursor.execute(
            'SELECT name FROM sqlite_master WHERE type = ? AND name = ?',
            ('table', name),
        ).fetchone()
        return str(row[0]) if row else ''

    @staticmethod
    def _backfill_video_entity_compatibility_columns(cursor, source_table):
        source_columns = {
            str(row[1] or '').strip()
            for row in cursor.execute(f'PRAGMA table_info({source_table})').fetchall()
        }
        for column_name in (
            'enrichment_status', 'enrichment_error', 'enriched_at',
            'avfan_enrichment_status', 'avfan_enrichment_error', 'avfan_enriched_at',
            'javtxt_enrichment_error', 'javtxt_enriched_at', 'description',
            'javtxt_description', 'avfan_actors', 'avfan_tags',
        ):
            if column_name not in source_columns:
                continue
            cursor.execute(
                f'''
                UPDATE video_entities
                SET {column_name} = COALESCE(
                    NULLIF((SELECT source.{column_name} FROM {source_table} source WHERE source.code = video_entities.code), ''),
                    {column_name}
                )
                WHERE EXISTS (
                    SELECT 1 FROM {source_table} source WHERE source.code = video_entities.code
                )
                '''
            )

    @staticmethod
    def _create_compatibility_view_triggers(cursor):
        # Compatibility views are intentionally read-only; business APIs write canonical tables.
        return
        cursor.executescript(
            '''
            CREATE TRIGGER IF NOT EXISTS trg_processed_videos_view_insert
            INSTEAD OF INSERT ON processed_videos
            BEGIN
                INSERT INTO video_entities (code, title, author, release_date, maker, publisher,
                    avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors,
                    enrichment_status, enrichment_error, enriched_at,
                    avfan_enrichment_status, avfan_enrichment_error, avfan_enriched_at,
                    javtxt_enrichment_status, javtxt_enrichment_error, javtxt_enriched_at,
                    javtxt_tags, description, javtxt_description, avfan_actors, avfan_tags,
                    javtxt_release_date, video_category,
                    javtxt_actors_raw, supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at)
                VALUES (NEW.code, COALESCE(NEW.title, ''), COALESCE(NEW.author, ''), COALESCE(NEW.release_date, ''),
                    COALESCE(NEW.maker, ''), COALESCE(NEW.publisher, ''), COALESCE(NEW.avfan_movie_id, ''),
                    COALESCE(NEW.javtxt_movie_id, ''), COALESCE(NEW.javtxt_url, ''), COALESCE(NEW.javtxt_title, ''),
                    COALESCE(NEW.javtxt_actors, ''), COALESCE(NEW.enrichment_status, ''), COALESCE(NEW.enrichment_error, ''), COALESCE(NEW.enriched_at, ''),
                    COALESCE(NEW.avfan_enrichment_status, ''), COALESCE(NEW.avfan_enrichment_error, ''), COALESCE(NEW.avfan_enriched_at, ''),
                    COALESCE(NEW.javtxt_enrichment_status, ''), COALESCE(NEW.javtxt_enrichment_error, ''), COALESCE(NEW.javtxt_enriched_at, ''),
                    COALESCE(NEW.javtxt_tags, ''), COALESCE(NEW.description, ''), COALESCE(NEW.javtxt_description, ''), COALESCE(NEW.avfan_actors, ''), COALESCE(NEW.avfan_tags, ''),
                    COALESCE(NEW.javtxt_release_date, ''), COALESCE(NEW.video_category, ''), COALESCE(NEW.javtxt_actors_raw, ''),
                    COALESCE(NEW.supplement_enrichment_status, ''), COALESCE(NEW.supplement_enrichment_error, ''), COALESCE(NEW.supplement_enriched_at, ''))
                ON CONFLICT(code) DO UPDATE SET
                    title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE video_entities.title END,
                    author = CASE WHEN excluded.author <> '' THEN excluded.author ELSE video_entities.author END,
                    release_date = CASE WHEN excluded.release_date <> '' THEN excluded.release_date ELSE video_entities.release_date END;
                INSERT INTO local_video_records (code, duration, size, storage_location)
                VALUES (NEW.code, COALESCE(NEW.duration, ''), COALESCE(NEW.size, ''), COALESCE(NEW.storage_location, ''))
                ON CONFLICT(code) DO UPDATE SET duration = excluded.duration, size = excluded.size, storage_location = excluded.storage_location, updated_at = CURRENT_TIMESTAMP;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_processed_videos_view_update
            INSTEAD OF UPDATE ON processed_videos
            BEGIN
                UPDATE video_entities SET title = COALESCE(NEW.title, title), author = COALESCE(NEW.author, author),
                    release_date = COALESCE(NEW.release_date, release_date), maker = COALESCE(NEW.maker, maker),
                    publisher = COALESCE(NEW.publisher, publisher), avfan_movie_id = COALESCE(NEW.avfan_movie_id, avfan_movie_id),
                    javtxt_movie_id = COALESCE(NEW.javtxt_movie_id, javtxt_movie_id), javtxt_url = COALESCE(NEW.javtxt_url, javtxt_url),
                    javtxt_title = COALESCE(NEW.javtxt_title, javtxt_title), javtxt_actors = COALESCE(NEW.javtxt_actors, javtxt_actors),
                    javtxt_tags = COALESCE(NEW.javtxt_tags, javtxt_tags), javtxt_release_date = COALESCE(NEW.javtxt_release_date, javtxt_release_date),
                    enrichment_status = COALESCE(NEW.enrichment_status, enrichment_status), enrichment_error = COALESCE(NEW.enrichment_error, enrichment_error), enriched_at = COALESCE(NEW.enriched_at, enriched_at),
                    avfan_enrichment_status = COALESCE(NEW.avfan_enrichment_status, avfan_enrichment_status), avfan_enrichment_error = COALESCE(NEW.avfan_enrichment_error, avfan_enrichment_error), avfan_enriched_at = COALESCE(NEW.avfan_enriched_at, avfan_enriched_at),
                    javtxt_enrichment_status = COALESCE(NEW.javtxt_enrichment_status, javtxt_enrichment_status), javtxt_enrichment_error = COALESCE(NEW.javtxt_enrichment_error, javtxt_enrichment_error), javtxt_enriched_at = COALESCE(NEW.javtxt_enriched_at, javtxt_enriched_at),
                    description = COALESCE(NEW.description, description), javtxt_description = COALESCE(NEW.javtxt_description, javtxt_description), avfan_actors = COALESCE(NEW.avfan_actors, avfan_actors), avfan_tags = COALESCE(NEW.avfan_tags, avfan_tags),
                    video_category = COALESCE(NEW.video_category, video_category), javtxt_actors_raw = COALESCE(NEW.javtxt_actors_raw, javtxt_actors_raw),
                    supplement_enrichment_status = COALESCE(NEW.supplement_enrichment_status, supplement_enrichment_status),
                    supplement_enrichment_error = COALESCE(NEW.supplement_enrichment_error, supplement_enrichment_error),
                    supplement_enriched_at = COALESCE(NEW.supplement_enriched_at, supplement_enriched_at), updated_at = CURRENT_TIMESTAMP
                WHERE code = OLD.code;
                UPDATE local_video_records SET duration = COALESCE(NEW.duration, duration), size = COALESCE(NEW.size, size), storage_location = COALESCE(NEW.storage_location, storage_location), updated_at = CURRENT_TIMESTAMP WHERE code = OLD.code;
            END;

            CREATE TRIGGER IF NOT EXISTS trg_processed_videos_view_delete
            INSTEAD OF DELETE ON processed_videos
            BEGIN
                DELETE FROM local_video_records WHERE code = OLD.code;
                DELETE FROM video_entities WHERE code = OLD.code
                  AND NOT EXISTS (SELECT 1 FROM video_actor_relations WHERE video_code = OLD.code)
                  AND NOT EXISTS (SELECT 1 FROM video_code_prefix_relations WHERE video_code = OLD.code);
            END;
            '''
        )

    def _backfill_legacy_supplement_links(self, cursor):
        """Fill links for legacy supplement queue rows once source tables exist."""
        cursor.execute(
            '''
            UPDATE pending_video_avfan
            SET avfan_movie_id = (
                    SELECT COALESCE(NULLIF(TRIM(source.avfan_movie_id), ''), '')
                    FROM video_entities AS source
                    WHERE source.code = pending_video_avfan.code
                ),
                avfan_url = ? || '/movies/' || (
                    SELECT TRIM(source.avfan_movie_id)
                    FROM video_entities AS source
                    WHERE source.code = pending_video_avfan.code
                )
            WHERE source_key = ?
              AND TRIM(COALESCE(avfan_movie_id, '')) = ''
              AND TRIM(COALESCE(avfan_url, '')) = ''
              AND EXISTS (
                    SELECT 1 FROM video_entities AS source
                    WHERE source.code = pending_video_avfan.code
                      AND TRIM(COALESCE(source.avfan_movie_id, '')) <> ''
                )
            ''',
            (get_avfan_base_url().rstrip('/'), SUPPLEMENT_TASK_SOURCE),
        )
        cursor.execute(
            '''
            UPDATE pending_actor_supplement
            SET avfan_url = (
                    SELECT TRIM(meta.avfan_url)
                    FROM video_actor_relation_meta AS meta
                    WHERE meta.actor_name = pending_actor_supplement.actor_name
                      AND meta.video_code = pending_actor_supplement.code
                )
            WHERE source_key = ?
              AND TRIM(COALESCE(avfan_url, '')) = ''
              AND EXISTS (
                    SELECT 1 FROM video_actor_relation_meta AS meta
                    WHERE meta.actor_name = pending_actor_supplement.actor_name
                      AND meta.video_code = pending_actor_supplement.code
                      AND TRIM(COALESCE(meta.avfan_url, '')) <> ''
                )
            ''',
            (SUPPLEMENT_TASK_SOURCE,),
        )
        cursor.execute(
            '''
            UPDATE pending_code_prefix_supplement
            SET avfan_url = (
                    SELECT TRIM(meta.avfan_url)
                    FROM video_prefix_relation_meta AS meta
                    WHERE UPPER(meta.prefix) = UPPER(pending_code_prefix_supplement.prefix)
                      AND meta.video_code = pending_code_prefix_supplement.code
                )
            WHERE source_key = ?
              AND TRIM(COALESCE(avfan_url, '')) = ''
              AND EXISTS (
                    SELECT 1 FROM video_prefix_relation_meta AS meta
                    WHERE UPPER(meta.prefix) = UPPER(pending_code_prefix_supplement.prefix)
                      AND meta.video_code = pending_code_prefix_supplement.code
                      AND TRIM(COALESCE(meta.avfan_url, '')) <> ''
                )
            ''',
            (SUPPLEMENT_TASK_SOURCE,),
        )

    def _migrate_enrichment_status_values(self, cursor):
        """Normalize legacy human-readable source statuses to stable codes."""
        status_columns = {
            'processed_videos': ('enrichment_status', 'avfan_enrichment_status', 'javtxt_enrichment_status', 'supplement_enrichment_status'),
            'actor_enrichments': ('enrichment_status', 'avfan_enrichment_status', 'javtxt_enrichment_status', 'binghuo_enrichment_status', 'baomu_enrichment_status'),
            'actor_movies': ('javtxt_enrichment_status', 'supplement_enrichment_status'),
            'code_prefix_enrichments': ('avfan_enrichment_status', 'javtxt_enrichment_status'),
            'code_prefix_movies': ('javtxt_enrichment_status', 'supplement_enrichment_status'),
            'excluded_actor_movies': ('javtxt_enrichment_status', 'supplement_enrichment_status'),
            'excluded_code_prefix_movies': ('javtxt_enrichment_status', 'supplement_enrichment_status'),
            'actor_library_summary': ('avfan_enrichment_status', 'javtxt_enrichment_status'),
            'code_prefix_library_summary': ('avfan_enrichment_status', 'javtxt_enrichment_status'),
            'canglangge_actor_candidates': ('binghuo_enrichment_status', 'baomu_enrichment_status'),
        }
        legacy_to_code = {
            '未补全': UNENRICHED_STATUS,
            '无搜索结果': NO_SEARCH_RESULTS_STATUS,
            '无视频详情': NO_VIDEO_DETAIL_STATUS,
            '已补全': ENRICHED_STATUS,
            '补全失败': FAILED_STATUS,
            '等待补全': PENDING_STATUS,
            'x': UNENRICHED_STATUS,
            'y': NO_SEARCH_RESULTS_STATUS,
            'z': NO_VIDEO_DETAIL_STATUS,
            'f': ENRICHED_STATUS,
            's': FAILED_STATUS,
            'w': PENDING_STATUS,
        }
        for table_name, columns in status_columns.items():
            cursor.execute(
                'SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?',
                ('view', table_name),
            )
            if cursor.fetchone() is not None:
                continue
            table_columns = {
                str(row[1] or '').strip()
                for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()
            }
            for column_name in columns:
                if column_name not in table_columns:
                    continue
                cases = ' '.join('WHEN ? THEN ?' for _ in legacy_to_code)
                parameters = []
                for legacy_value, code_value in legacy_to_code.items():
                    parameters.extend((legacy_value, code_value))
                cursor.execute(
                    f'''UPDATE {table_name}
                        SET {column_name} = CASE TRIM(COALESCE({column_name}, '')) {cases}
                            ELSE {column_name} END
                        WHERE TRIM(COALESCE({column_name}, '')) IN ({','.join('?' for _ in legacy_to_code)})''',
                    [*parameters, *legacy_to_code],
                )

    @staticmethod
    def _ensure_library_refresh_tracking_tables(cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS actor_enrichment_refresh_times (
                actor_name TEXT NOT NULL,
                source_key TEXT NOT NULL,
                last_completed_at TEXT NOT NULL,
                update_status TEXT DEFAULT '',
                PRIMARY KEY (actor_name, source_key)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS code_prefix_enrichment_refresh_times (
                prefix TEXT NOT NULL,
                source_key TEXT NOT NULL,
                last_completed_at TEXT NOT NULL,
                update_status TEXT DEFAULT '',
                PRIMARY KEY (prefix, source_key)
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS actor_expired_refresh_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_name TEXT NOT NULL,
                source_key TEXT NOT NULL,
                previous_video_count INTEGER NOT NULL DEFAULT 0,
                current_video_count INTEGER NOT NULL DEFAULT 0,
                added_video_count INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS code_prefix_expired_refresh_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prefix TEXT NOT NULL,
                source_key TEXT NOT NULL,
                previous_video_count INTEGER NOT NULL DEFAULT 0,
                current_video_count INTEGER NOT NULL DEFAULT 0,
                added_video_count INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        for source_key, timestamp_column in (
            (AVFAN_VIDEO_SOURCE, 'avfan_last_enriched_at'),
            (JAVTXT_VIDEO_SOURCE, 'javtxt_last_enriched_at'),
        ):
            cursor.execute(
                f'''
                INSERT OR IGNORE INTO actor_enrichment_refresh_times (
                    actor_name, source_key, last_completed_at
                )
                SELECT actor_name, ?, {timestamp_column}
                FROM actor_enrichments
                WHERE TRIM(COALESCE({timestamp_column}, '')) <> ''
                ''',
                (source_key,),
            )
            cursor.execute(
                f'''
                INSERT OR IGNORE INTO code_prefix_enrichment_refresh_times (
                    prefix, source_key, last_completed_at
                )
                SELECT UPPER(prefix), ?, {timestamp_column}
                FROM code_prefix_enrichments
                WHERE TRIM(COALESCE({timestamp_column}, '')) <> ''
                ''',
                (source_key,),
            )

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
        processed_write_table = self._processed_video_storage_target(cursor)
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
            UPDATE video_entities
            SET javtxt_enrichment_status = COALESCE(
                    NULLIF(javtxt_enrichment_status, ''),
                    (
                        SELECT COALESCE(NULLIF(p.javtxt_enrichment_status, ''), ?)
                        FROM processed_videos p
                        WHERE p.code = video_entities.code
                    ),
                    ?
                ),
                javtxt_movie_id = COALESCE(
                    NULLIF(javtxt_movie_id, ''),
                    (
                        SELECT p.javtxt_movie_id
                        FROM processed_videos p
                        WHERE p.code = video_entities.code
                    ),
                    ''
                ),
                javtxt_url = COALESCE(
                    NULLIF(javtxt_url, ''),
                    (
                        SELECT p.javtxt_url
                        FROM processed_videos p
                        WHERE p.code = video_entities.code
                    ),
                    ''
                ),
                javtxt_tags = COALESCE(
                    NULLIF(javtxt_tags, ''),
                    (
                        SELECT p.javtxt_tags
                        FROM processed_videos p
                        WHERE p.code = video_entities.code
                    ),
                    ''
                ),
                javtxt_release_date = COALESCE(
                    NULLIF(javtxt_release_date, ''),
                    (
                        SELECT p.javtxt_release_date
                        FROM processed_videos p
                        WHERE p.code = video_entities.code
                    ),
                    ''
                ),
                javtxt_actors_raw = COALESCE(NULLIF(javtxt_actors_raw, ''), NULLIF(author, ''), '')
            ''',
            (UNENRICHED_STATUS, UNENRICHED_STATUS),
        )
        cursor.execute(
            '''
            UPDATE video_entities
            SET javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?),
                javtxt_movie_id = COALESCE(NULLIF(javtxt_movie_id, ''), ''),
                javtxt_url = COALESCE(NULLIF(javtxt_url, ''), ''),
                javtxt_tags = COALESCE(NULLIF(javtxt_tags, ''), ''),
                javtxt_release_date = COALESCE(NULLIF(javtxt_release_date, ''), ''),
                javtxt_actors_raw = COALESCE(NULLIF(javtxt_actors_raw, ''), NULLIF(author, ''), '')
            WHERE code IN (SELECT video_code FROM video_actor_relations)
            ''',
            (UNENRICHED_STATUS,),
        )
        cursor.execute(
            f'''
            UPDATE {processed_write_table}
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
        storage_table = self._processed_video_storage_target(cursor)
        read_table = storage_table
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return

        cursor.execute(
            f'''
            SELECT javtxt_tags, javtxt_actors, video_category
            FROM {read_table}
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
                f'''
                UPDATE {storage_table}
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, normalized_code),
            )

    def _backfill_video_categories(self, cursor, filter_settings=None):
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            SELECT code, javtxt_tags, javtxt_actors, video_category
            FROM {storage_table}
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
                f'''
                UPDATE {storage_table}
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, code),
            )

    @staticmethod
    def _web_movie_storage_target(cursor, table_name):
        object_type = cursor.execute(
            'SELECT type FROM sqlite_master WHERE name = ?', (table_name,)
        ).fetchone()
        if object_type and object_type[0] == 'view':
            return 'video_entities', 'javtxt_actors_raw'
        return table_name, 'author_raw'

    @staticmethod
    def _processed_video_storage_target(cursor):
        return VideoDatabase._legacy_table_name(cursor, 'processed_videos') or 'video_entities'

    @staticmethod
    def _processed_video_read_sql(cursor=None):
        if cursor is not None and VideoDatabase._legacy_table_name(cursor, 'processed_videos'):
            return '''
                SELECT code, title, author, duration, size, storage_location,
                       avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title,
                       javtxt_actors, javtxt_tags, video_category,
                       release_date, maker, publisher,
                       avfan_enrichment_status, javtxt_enrichment_status
                FROM processed_videos
            '''
        return '''
            SELECT e.code, e.title, e.author,
                   COALESCE(l.duration, '') AS duration,
                   COALESCE(l.size, '') AS size,
                   COALESCE(l.storage_location, '') AS storage_location,
                   e.avfan_movie_id, e.javtxt_movie_id, e.javtxt_url, e.javtxt_title,
                   e.javtxt_actors, e.javtxt_tags, e.video_category,
                   e.release_date, e.maker, e.publisher,
                   e.avfan_enrichment_status, e.javtxt_enrichment_status
            FROM video_entities AS e
            LEFT JOIN local_video_records AS l ON l.code = e.code
        '''

    def _backfill_web_movie_categories(self, cursor, table_name, filter_settings=None):
        storage_table, _author_raw_column = self._web_movie_storage_target(cursor, table_name)
        cursor.execute(
            f'''
            SELECT code, author, javtxt_tags, video_category
            FROM {table_name}
            WHERE COALESCE(video_category, '') = ''
            '''
        )
        rows = cursor.fetchall()
        for code, author, javtxt_tags, current_category in rows:
            normalized_code = standardize_video_code(code)
            processed_category = ''
            if normalized_code:
                cursor.execute(
                    f'''
                    SELECT video_category
                    FROM {storage_table}
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
                UPDATE {storage_table}
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, normalized_code),
            )

    def _clear_staged_video_categories_for_categorized_codes(self, cursor):
        cursor.execute(
            '''
            DELETE FROM manual_category_staging
            WHERE code IN (
                SELECT code FROM video_entities WHERE COALESCE(video_category, '') <> ''
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
        storage_table, author_raw_column = self._web_movie_storage_target(cursor, table_name)

        cursor.execute(
            f'''
            SELECT code,
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
            if is_no_result_status(javtxt_status):
                codes_to_preserve_terminal.append(standardize_video_code(code))
            else:
                codes_to_mark_no_result.append(standardize_video_code(code))

        for index in range(0, len(codes_to_preserve_terminal), 500):
            chunk = [code for code in codes_to_preserve_terminal[index:index + 500] if code]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {storage_table}
                SET author = '',
                    {author_raw_column} = '',
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE code IN ({placeholders})
                ''',
                (*chunk,),
            )

        for index in range(0, len(codes_to_mark_no_result), 500):
            chunk = [code for code in codes_to_mark_no_result[index:index + 500] if code]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {storage_table}
                SET author = '',
                    {author_raw_column} = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE code IN ({placeholders})
                ''',
                (NO_SEARCH_RESULTS_STATUS, *chunk),
            )

    def _clear_web_movie_javtxt_state_without_detail_reference(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')
        storage_table, author_raw_column = self._web_movie_storage_target(cursor, table_name)

        cursor.execute(
            f'''
            SELECT code
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
        codes_to_clear = [standardize_video_code(row[0]) for row in cursor.fetchall() if row and row[0]]
        for index in range(0, len(codes_to_clear), 500):
            chunk = [code for code in codes_to_clear[index:index + 500] if code]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {storage_table}
                SET author = '',
                    {author_raw_column} = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_legacy_web_movie_javtxt_state_without_release_date(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')
        storage_table, _author_raw_column = self._web_movie_storage_target(cursor, table_name)

        cursor.execute(
            f'''
            SELECT code
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
        codes_to_clear = [standardize_video_code(row[0]) for row in cursor.fetchall() if row and row[0]]
        for index in range(0, len(codes_to_clear), 500):
            chunk = [code for code in codes_to_clear[index:index + 500] if code]
            if not chunk:
                continue
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {storage_table}
                SET javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = ''
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_ineligible_processed_video_javtxt_state(self, cursor):
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date,
                   javtxt_enrichment_status
            FROM {storage_table}
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
                UPDATE {storage_table}
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
                UPDATE {storage_table}
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
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            SELECT code
            FROM {storage_table}
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
                UPDATE {storage_table}
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
            SELECT prefix FROM video_code_prefix_relations
            UNION
            SELECT prefix FROM code_prefix_enrichments
            '''
        )
        prefixes = [str((row or [''])[0] or '').strip().upper() for row in cursor.fetchall()]
        cursor.execute(
            '''
            SELECT actor_name FROM video_actor_relations
            UNION
            SELECT actor_name FROM actor_enrichments
            '''
        )
        actor_names = [str((row or [''])[0] or '').strip() for row in cursor.fetchall()]
        cursor.execute(
            '''
            SELECT video_code FROM video_code_prefix_relations
            UNION
            SELECT video_code FROM video_actor_relations
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
        storage_table = self._processed_video_storage_target(cursor)
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
                UPDATE {storage_table}
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

    def _clear_web_movie_javtxt_codes(self, cursor, codes):
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
                UPDATE video_entities
                SET author = '',
                    javtxt_actors_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _normalize_existing_web_movie_codes(self, cursor):
        self._normalize_processed_video_codes(cursor)
        self._normalize_code_prefix_movie_codes(cursor)
        self._normalize_actor_movie_codes(cursor)
        self._normalize_manual_category_staging_codes(cursor)

    def _normalize_processed_video_codes(self, cursor):
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(f'SELECT code FROM {storage_table}')
        for (code,) in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute(f'SELECT 1 FROM {storage_table} WHERE code = ?', (normalized_code,))
            if cursor.fetchone():
                cursor.execute(f'DELETE FROM {storage_table} WHERE code = ?', (code,))
            else:
                cursor.execute(f'UPDATE {storage_table} SET code = ? WHERE code = ?', (normalized_code, code))

    def _normalize_code_prefix_movie_codes(self, cursor):
        legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
        cursor.execute('SELECT prefix, code FROM code_prefix_movies')
        for prefix, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            normalized_prefix = self._extract_standard_code_prefix(normalized_code)
            if not normalized_code or not normalized_prefix:
                continue
            if normalized_code == code and normalized_prefix == prefix:
                continue
            duplicate_sql = (
                f'SELECT 1 FROM {legacy_code_prefix_movies} WHERE prefix = ? AND code = ?'
                if legacy_code_prefix_movies
                else 'SELECT 1 FROM video_code_prefix_relations WHERE prefix = ? AND video_code = ?'
            )
            cursor.execute(duplicate_sql, (normalized_prefix, normalized_code))
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM video_prefix_relation_meta WHERE prefix = ? AND video_code = ?',
                    (prefix, code),
                )
                cursor.execute(
                    'DELETE FROM video_code_prefix_relations WHERE prefix = ? AND video_code = ?',
                    (prefix, code),
                )
                if legacy_code_prefix_movies:
                    cursor.execute(
                        f'DELETE FROM {legacy_code_prefix_movies} WHERE prefix = ? AND code = ?',
                        (prefix, code),
                    )
            else:
                cursor.execute(
                    'UPDATE video_code_prefix_relations SET prefix = ?, video_code = ? WHERE prefix = ? AND video_code = ?',
                    (normalized_prefix, normalized_code, prefix, code),
                )
                cursor.execute(
                    'UPDATE video_prefix_relation_meta SET prefix = ?, video_code = ? WHERE prefix = ? AND video_code = ?',
                    (normalized_prefix, normalized_code, prefix, code),
                )
                if legacy_code_prefix_movies:
                    cursor.execute(
                        f'UPDATE {legacy_code_prefix_movies} SET prefix = ?, code = ? WHERE prefix = ? AND code = ?',
                        (normalized_prefix, normalized_code, prefix, code),
                    )

    def _normalize_actor_movie_codes(self, cursor):
        legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
        if legacy_actor_movies:
            legacy_rows = cursor.execute(
                f'SELECT actor_name, code FROM {legacy_actor_movies}'
            ).fetchall()
            for actor_name, code in legacy_rows:
                normalized_code = standardize_video_code(code)
                if not normalized_code or normalized_code == code:
                    continue
                duplicate = cursor.execute(
                    f'SELECT 1 FROM {legacy_actor_movies} WHERE actor_name = ? AND code = ?',
                    (actor_name, normalized_code),
                ).fetchone()
                if duplicate:
                    cursor.execute(
                        f'DELETE FROM {legacy_actor_movies} WHERE actor_name = ? AND code = ?',
                        (actor_name, code),
                    )
                    cursor.execute(
                        'DELETE FROM video_actor_relation_meta WHERE actor_name = ? AND video_code = ?',
                        (actor_name, code),
                    )
                    cursor.execute(
                        'DELETE FROM video_actor_relations WHERE actor_name = ? AND video_code = ?',
                        (actor_name, code),
                    )
                else:
                    cursor.execute(
                        f'UPDATE {legacy_actor_movies} SET code = ? WHERE actor_name = ? AND code = ?',
                        (normalized_code, actor_name, code),
                    )
                    canonical_duplicate = cursor.execute(
                        'SELECT 1 FROM video_actor_relations WHERE actor_name = ? AND video_code = ?',
                        (actor_name, normalized_code),
                    ).fetchone()
                    if canonical_duplicate:
                        cursor.execute(
                            'DELETE FROM video_actor_relation_meta WHERE actor_name = ? AND video_code = ?',
                            (actor_name, code),
                        )
                        cursor.execute(
                            'DELETE FROM video_actor_relations WHERE actor_name = ? AND video_code = ?',
                            (actor_name, code),
                        )
                    else:
                        cursor.execute(
                            'UPDATE video_actor_relations SET video_code = ? WHERE actor_name = ? AND video_code = ?',
                            (normalized_code, actor_name, code),
                        )
                        cursor.execute(
                            'UPDATE video_actor_relation_meta SET video_code = ? WHERE actor_name = ? AND video_code = ?',
                            (normalized_code, actor_name, code),
                        )
        cursor.execute('SELECT actor_name, code FROM actor_movies')
        for actor_name, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            duplicate_sql = (
                f'SELECT 1 FROM {legacy_actor_movies} WHERE actor_name = ? AND code = ?'
                if legacy_actor_movies
                else 'SELECT 1 FROM video_actor_relations WHERE actor_name = ? AND video_code = ?'
            )
            cursor.execute(duplicate_sql, (actor_name, normalized_code))
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM video_actor_relation_meta WHERE actor_name = ? AND video_code = ?',
                    (actor_name, code),
                )
                cursor.execute(
                    'DELETE FROM video_actor_relations WHERE actor_name = ? AND video_code = ?',
                    (actor_name, code),
                )
                if legacy_actor_movies:
                    cursor.execute(
                        f'DELETE FROM {legacy_actor_movies} WHERE actor_name = ? AND code = ?',
                        (actor_name, code),
                    )
            else:
                cursor.execute(
                    'UPDATE video_actor_relations SET video_code = ? WHERE actor_name = ? AND video_code = ?',
                    (normalized_code, actor_name, code),
                )
                cursor.execute(
                    'UPDATE video_actor_relation_meta SET video_code = ? WHERE actor_name = ? AND video_code = ?',
                    (normalized_code, actor_name, code),
                )
                if legacy_actor_movies:
                    cursor.execute(
                        f'UPDATE {legacy_actor_movies} SET code = ? WHERE actor_name = ? AND code = ?',
                        (normalized_code, actor_name, code),
                    )
            if cursor.execute(
                'SELECT 1 FROM video_actor_relations WHERE actor_name = ? AND video_code = ?',
                (actor_name, normalized_code),
            ).fetchone() is None:
                cursor.execute(
                    'INSERT OR IGNORE INTO video_actor_relations (video_code, actor_name) VALUES (?, ?)',
                    (normalized_code, actor_name),
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
            cursor.execute(
                f'''
                SELECT code, title, author, release_date, javtxt_enrichment_status,
                       javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                       javtxt_actors_raw, video_category
                FROM video_entities
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
        cursor.execute(
            f'''
            SELECT code, title, author, release_date, javtxt_enrichment_status,
                   javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                   javtxt_actors_raw, video_category
            FROM video_entities
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
        cursor.executemany(
            '''
            UPDATE video_entities
            SET author = ?,
                javtxt_actors_raw = ?,
                javtxt_enrichment_status = ?,
                javtxt_movie_id = ?,
                javtxt_url = ?,
                javtxt_tags = ?,
                javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                release_date = COALESCE(NULLIF(?, ''), release_date),
                video_category = COALESCE(NULLIF(?, ''), video_category),
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            updates,
        )
        legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
        if legacy_actor_movies:
            cursor.executemany(
                f'''
                UPDATE {legacy_actor_movies}
                SET author = ?, author_raw = ?, javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?, javtxt_url = ?, javtxt_tags = ?,
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    video_category = COALESCE(NULLIF(?, ''), video_category)
                WHERE code = ?
                ''',
                updates,
            )
        return int(cursor.rowcount or 0)

    def _propagate_existing_web_movie_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT relation.video_code
            FROM video_code_prefix_relations AS relation
            JOIN video_entities AS entity ON entity.code = relation.video_code
            WHERE COALESCE(entity.javtxt_movie_id, '') <> '' OR COALESCE(entity.javtxt_url, '') <> ''
            UNION
            SELECT relation.video_code
            FROM video_actor_relations AS relation
            JOIN video_entities AS entity ON entity.code = relation.video_code
            WHERE COALESCE(entity.javtxt_movie_id, '') <> '' OR COALESCE(entity.javtxt_url, '') <> ''
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
        processed_read_table = self._processed_video_storage_target(cursor)
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
            FROM {processed_read_table}
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

        cursor.executemany(
            '''
            UPDATE video_entities
            SET author = ?,
                javtxt_actors_raw = ?,
                javtxt_enrichment_status = ?,
                javtxt_movie_id = ?,
                javtxt_url = ?,
                javtxt_tags = ?,
                javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                release_date = COALESCE(NULLIF(?, ''), release_date),
                video_category = COALESCE(NULLIF(?, ''), video_category),
                updated_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            updates,
        )
        return int(cursor.rowcount or 0)

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
            FROM video_code_prefix_relations
            WHERE video_code IN ({placeholders})
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
            FROM video_actor_relations
            WHERE video_code IN ({placeholders})
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
            processed_write_table = self._processed_video_storage_target(cursor)
            for plan in plans:
                normalized_code = standardize_video_code(plan.metadata.code)
                if not normalized_code:
                    continue
                cursor.execute(f'DELETE FROM {processed_write_table} WHERE code = ?', (normalized_code,))
                if processed_write_table == 'video_entities':
                    cursor.execute(
                        '''
                        INSERT INTO video_entities (code, title, author, enrichment_status)
                        VALUES (?, ?, ?, 'UNENRICHED')
                        ''',
                        (normalized_code, plan.metadata.title, plan.metadata.author),
                    )
                    cursor.execute(
                        '''
                        INSERT INTO local_video_records (code, duration, size, storage_location)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(code) DO UPDATE SET
                            duration = excluded.duration, size = excluded.size,
                            storage_location = excluded.storage_location,
                            updated_at = CURRENT_TIMESTAMP
                        ''',
                        (normalized_code, plan.metadata.duration, plan.metadata.size, plan.storage_location),
                    )
                else:
                    cursor.execute(f'''
                        INSERT INTO {processed_write_table} (
                            code, title, author, duration, size, storage_location, enrichment_status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'UNENRICHED')
                    ''', (
                        normalized_code, plan.metadata.title, plan.metadata.author,
                        plan.metadata.duration, plan.metadata.size, plan.storage_location,
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
        clauses.append(
            'NOT EXISTS (SELECT 1 FROM hidden_actors h WHERE h.name = a.name)'
        )
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
        completion_record = {
            'binghuo_enrichment_status': binghuo_enrichment_status,
            'binghuo_person_id': row[9] or '',
            'binghuo_birthday': row[10] or '',
            'binghuo_height': row[12] or '',
            'binghuo_bust': row[13] or '',
            'binghuo_waist': row[14] or '',
            'binghuo_hip': row[15] or '',
            'baomu_enrichment_status': baomu_enrichment_status,
            'baomu_birthday': row[16] or '',
            'binghuo_cup': row[17] or '',
            'baomu_height': row[18] or '',
            'baomu_bust': row[19] or '',
            'baomu_cup': row[20] or '',
            'baomu_waist': row[21] or '',
            'baomu_hip': row[22] or '',
        }
        binghuo_completion_status = build_actor_source_completion_status(
            completion_record,
            BINGHUO_ACTOR_SOURCE,
        )
        baomu_completion_status = build_actor_source_completion_status(
            completion_record,
            BAOMU_ACTOR_SOURCE,
        )
        final_completion_status = build_actor_final_completion_status(completion_record)
        enrichment_status = build_library_enrichment_status_text(
            avfan_enrichment_status,
            javtxt_enrichment_status,
            binghuo_completion_status,
            baomu_completion_status,
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
            'binghuo_cup': row[17] or '',
            'baomu_height': row[18] or '',
            'baomu_bust': row[19] or '',
            'baomu_cup': row[20] or '',
            'baomu_waist': row[21] or '',
            'baomu_hip': row[22] or '',
            'binghuo_completion_status': binghuo_completion_status,
            'baomu_completion_status': baomu_completion_status,
            'final_completion_status': final_completion_status,
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
                       COALESCE(e.baomu_birthday, '') AS baomu_birthday,
                       COALESCE(e.binghuo_cup, '') AS binghuo_cup,
                       COALESCE(e.baomu_height, '') AS baomu_height,
                       COALESCE(e.baomu_bust, '') AS baomu_bust,
                       COALESCE(e.baomu_cup, '') AS baomu_cup,
                       COALESCE(e.baomu_waist, '') AS baomu_waist,
                       COALESCE(e.baomu_hip, '') AS baomu_hip
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
                        {self._code_prefix_expression_sql('entity.code')} AS prefix,
                        COUNT(DISTINCT entity.code) AS video_count
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(entity.code, '')) <> ''
                      AND {self._code_prefix_expression_sql('entity.code')} GLOB '*[A-Z]*'
                    GROUP BY {self._code_prefix_expression_sql('entity.code')}
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
                        UPPER(relation.prefix) AS prefix,
                        MIN(CASE WHEN TRIM(COALESCE(entity.release_date, '')) <> '' THEN entity.release_date END) AS earliest_release_date,
                        MAX(CASE WHEN TRIM(COALESCE(entity.release_date, '')) <> '' THEN entity.release_date END) AS latest_release_date
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(relation.prefix, '')) <> ''
                    GROUP BY UPPER(relation.prefix)
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
                    SELECT UPPER(relation.prefix) AS prefix
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(entity.code, '')) <> ''
                      AND UPPER(relation.prefix) GLOB '*[A-Z]*'
                    GROUP BY UPPER(relation.prefix)
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
            processed_write_table = self._processed_video_storage_target(cursor)

            cursor.execute('SELECT 1 FROM code_prefix_enrichments WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已存在')

            cursor.execute('SELECT 1 FROM video_code_prefix_relations WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已存在网页作品记录')

            cursor.execute('SELECT 1 FROM hidden_code_prefixes WHERE prefix = ?', (normalized_prefix,))
            if cursor.fetchone():
                raise ValueError(f'番号前缀 {normalized_prefix} 已被删除，请避免重复添加')

            cursor.execute(f'SELECT code FROM {processed_write_table}')
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
                processed_read_sql = self._processed_video_read_sql(cursor)
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

    @staticmethod
    def _normalize_excluded_movie_reason(reason):
        values = []
        seen = set()
        for value in str(reason or '').split(','):
            normalized = str(value or '').strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return ','.join(values)

    def _store_excluded_web_movie_rows(self, cursor, table_name, owner_column, owner_value, movies, reason):
        normalized_owner = str(owner_value or '').strip()
        normalized_reason = self._normalize_excluded_movie_reason(reason)
        values = []
        for movie in movies or []:
            if not isinstance(movie, dict):
                continue
            normalized_code = standardize_video_code(movie.get('code', ''))
            if not normalized_owner or not normalized_code:
                continue
            values.append(
                (
                    normalized_owner,
                    normalized_code,
                    str(movie.get('title', '') or '').strip(),
                    str(movie.get('author', '') or '').strip(),
                    str(movie.get('release_date', '') or '').strip(),
                    str(movie.get('avfan_url', '') or '').strip(),
                    max(1, int(movie.get('page_number', 1) or 1)),
                    str(movie.get('javtxt_enrichment_status', '') or '').strip(),
                    str(movie.get('javtxt_movie_id', '') or '').strip(),
                    str(movie.get('javtxt_url', '') or '').strip(),
                    str(movie.get('javtxt_tags', '') or '').strip(),
                    str(movie.get('javtxt_release_date', '') or '').strip(),
                    str(movie.get('author_raw', '') or '').strip(),
                    str(movie.get('video_category', '') or '').strip(),
                    str(movie.get('supplement_enrichment_status', '') or '').strip(),
                    str(movie.get('supplement_enrichment_error', '') or '').strip(),
                    str(movie.get('supplement_enriched_at', '') or '').strip(),
                    normalized_reason,
                )
            )
        if not values:
            return 0
        cursor.executemany(
            f'''
            INSERT INTO {table_name} (
                {owner_column}, code, title, author, release_date, avfan_url, page_number,
                javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                javtxt_release_date, author_raw, video_category,
                supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at,
                exclude_reason, excluded_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT({owner_column}, code) DO UPDATE SET
                title = excluded.title,
                author = excluded.author,
                release_date = excluded.release_date,
                avfan_url = excluded.avfan_url,
                page_number = excluded.page_number,
                javtxt_enrichment_status = excluded.javtxt_enrichment_status,
                javtxt_movie_id = excluded.javtxt_movie_id,
                javtxt_url = excluded.javtxt_url,
                javtxt_tags = excluded.javtxt_tags,
                javtxt_release_date = excluded.javtxt_release_date,
                author_raw = excluded.author_raw,
                video_category = excluded.video_category,
                exclude_reason = excluded.exclude_reason,
                last_seen_at = CURRENT_TIMESTAMP
            ''',
            values,
        )
        return len(values)

    def store_excluded_code_prefix_movies(self, prefix, movies, reason=''):
        normalized_prefix = str(prefix or '').strip().upper()
        with self._connect() as conn:
            count = self._store_excluded_web_movie_rows(
                conn,
                'excluded_code_prefix_movies',
                'prefix',
                normalized_prefix,
                movies,
                reason,
            )
            conn.commit()
        return count

    def store_excluded_actor_movies(self, actor_name, movies, reason=''):
        normalized_name = str(actor_name or '').strip()
        with self._connect() as conn:
            count = self._store_excluded_web_movie_rows(
                conn,
                'excluded_actor_movies',
                'actor_name',
                normalized_name,
                movies,
                reason,
            )
            conn.commit()
        return count

    def list_excluded_code_prefix_movie_keys(self, prefixes=None, codes=None):
        normalized_prefixes = sorted({str(value or '').strip().upper() for value in prefixes or [] if str(value or '').strip()})
        normalized_codes = sorted({standardize_video_code(value) for value in codes or [] if standardize_video_code(value)})
        if not normalized_prefixes or not normalized_codes:
            return set()
        prefix_placeholders = ','.join('?' for _ in normalized_prefixes)
        code_placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT prefix, code
                FROM excluded_code_prefix_movies
                WHERE prefix IN ({prefix_placeholders})
                  AND code IN ({code_placeholders})
                ''',
                [*normalized_prefixes, *normalized_codes],
            ).fetchall()
        return {(str(row[0] or '').strip().upper(), standardize_video_code(row[1])) for row in rows}

    def _list_excluded_web_movie_reasons(self, table_name, owner_column, owners, codes, uppercase_owner=False):
        normalized_owners = sorted({
            (str(value or '').strip().upper() if uppercase_owner else str(value or '').strip())
            for value in owners or []
            if str(value or '').strip()
        })
        normalized_codes = sorted({
            standardize_video_code(value)
            for value in codes or []
            if standardize_video_code(value)
        })
        if not normalized_owners or not normalized_codes:
            return {}
        owner_placeholders = ','.join('?' for _ in normalized_owners)
        code_placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT {owner_column}, code, exclude_reason
                FROM {table_name}
                WHERE {owner_column} IN ({owner_placeholders})
                  AND code IN ({code_placeholders})
                ''',
                [*normalized_owners, *normalized_codes],
            ).fetchall()
        return {
            (
                str(row[0] or '').strip().upper()
                if uppercase_owner
                else str(row[0] or '').strip(),
                standardize_video_code(row[1]),
            ): self._normalize_excluded_movie_reason(row[2]) or 'already_excluded'
            for row in rows
        }

    def list_excluded_actor_movie_keys(self, actor_names=None, codes=None):
        normalized_names = sorted({str(value or '').strip() for value in actor_names or [] if str(value or '').strip()})
        normalized_codes = sorted({standardize_video_code(value) for value in codes or [] if standardize_video_code(value)})
        if not normalized_names or not normalized_codes:
            return set()
        name_placeholders = ','.join('?' for _ in normalized_names)
        code_placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT actor_name, code
                FROM excluded_actor_movies
                WHERE actor_name IN ({name_placeholders})
                  AND code IN ({code_placeholders})
                ''',
                [*normalized_names, *normalized_codes],
            ).fetchall()
        return {(str(row[0] or '').strip(), standardize_video_code(row[1])) for row in rows}

    def bump_data_source_versions(self, source_keys):
        normalized_keys = sorted({str(key or '').strip() for key in source_keys or [] if str(key or '').strip()})
        if not normalized_keys:
            return {}
        with self._connect() as conn:
            cursor = conn.cursor()
            for source_key in normalized_keys:
                cursor.execute(
                    '''
                    INSERT INTO data_source_versions (source_key, version, updated_at)
                    VALUES (?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_key) DO UPDATE SET
                        version = data_source_versions.version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (source_key,),
                )
            conn.commit()
            rows = cursor.execute(
                f'''
                SELECT source_key, version
                FROM data_source_versions
                WHERE source_key IN ({','.join('?' for _ in normalized_keys)})
                ''',
                normalized_keys,
            ).fetchall()
        return {str(row[0] or '').strip(): int(row[1] or 0) for row in rows}

    def get_data_source_versions(self, source_keys=None):
        normalized_keys = sorted({str(key or '').strip() for key in source_keys or [] if str(key or '').strip()})
        where_sql = ''
        parameters = []
        if source_keys is not None:
            if not normalized_keys:
                return {}
            where_sql = f"WHERE source_key IN ({','.join('?' for _ in normalized_keys)})"
            parameters = normalized_keys
        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT source_key, version FROM data_source_versions {where_sql}',
                parameters,
            ).fetchall()
        return {str(row[0] or '').strip(): int(row[1] or 0) for row in rows}

    def update_snapshot_registry(
        self,
        snapshot_key,
        source_keys=None,
        source_version='',
        filter_fingerprint='',
        dirty=False,
        refreshed_at='',
        refresh_duration_ms=0,
    ):
        normalized_key = str(snapshot_key or '').strip()
        if not normalized_key:
            return
        normalized_sources = ','.join(sorted({
            str(key or '').strip() for key in source_keys or [] if str(key or '').strip()
        }))
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT INTO snapshot_registry (
                    snapshot_key, source_keys, source_version, filter_fingerprint, dirty,
                    last_built_at, last_accessed_at, refresh_duration_ms, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(snapshot_key) DO UPDATE SET
                    source_keys = excluded.source_keys,
                    source_version = excluded.source_version,
                    filter_fingerprint = excluded.filter_fingerprint,
                    dirty = excluded.dirty,
                    last_built_at = CASE
                        WHEN excluded.dirty = 0 AND excluded.last_built_at <> ''
                        THEN excluded.last_built_at ELSE snapshot_registry.last_built_at END,
                    last_accessed_at = CURRENT_TIMESTAMP,
                    refresh_duration_ms = excluded.refresh_duration_ms,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    normalized_key,
                    normalized_sources,
                    str(source_version or '').strip(),
                    str(filter_fingerprint or '').strip(),
                    1 if dirty else 0,
                    str(refreshed_at or '').strip(),
                    max(0, int(refresh_duration_ms or 0)),
                ),
            )
            conn.commit()

    def mark_snapshot_registry_dirty(self, source_keys=None, snapshot_keys=None):
        normalized_sources = sorted({str(key or '').strip() for key in source_keys or [] if str(key or '').strip()})
        normalized_snapshots = sorted({str(key or '').strip() for key in snapshot_keys or [] if str(key or '').strip()})
        if not normalized_sources and not normalized_snapshots:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            changed = 0
            if normalized_snapshots:
                placeholders = ','.join('?' for _ in normalized_snapshots)
                cursor.execute(
                    f'UPDATE snapshot_registry SET dirty = 1, updated_at = CURRENT_TIMESTAMP WHERE snapshot_key IN ({placeholders})',
                    normalized_snapshots,
                )
                changed += int(cursor.rowcount or 0)
            if normalized_sources:
                source_terms = ','.join('?' for _ in normalized_sources)
                cursor.execute(
                    f'''
                    UPDATE snapshot_registry
                    SET dirty = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE EXISTS (
                        SELECT 1
                        FROM json_each('[' || '"' || REPLACE(source_keys, ',', '","') || '"' || ']') AS source
                        WHERE source.value IN ({source_terms})
                    )
                    ''',
                    normalized_sources,
                )
                changed += int(cursor.rowcount or 0)
            conn.commit()
        return changed

    def get_snapshot_registry(self, snapshot_key=None):
        normalized_key = str(snapshot_key or '').strip()
        with self._connect() as conn:
            if normalized_key:
                row = conn.execute(
                    '''
                    SELECT snapshot_key, source_keys, source_version, filter_fingerprint, dirty,
                           last_built_at, last_accessed_at, refresh_duration_ms, updated_at
                    FROM snapshot_registry
                    WHERE snapshot_key = ?
                    ''',
                    (normalized_key,),
                ).fetchone()
                if row is None:
                    return {}
                return self._build_snapshot_registry_row(row)
            rows = conn.execute(
                '''
                SELECT snapshot_key, source_keys, source_version, filter_fingerprint, dirty,
                       last_built_at, last_accessed_at, refresh_duration_ms, updated_at
                FROM snapshot_registry
                ''',
            ).fetchall()
        return {
            str(row[0] or '').strip(): self._build_snapshot_registry_row(row)
            for row in rows
            if str(row[0] or '').strip()
        }

    @staticmethod
    def _build_snapshot_registry_row(row):
        return {
            'snapshot_key': str(row[0] or '').strip(),
            'source_keys': [item for item in str(row[1] or '').split(',') if item],
            'source_version': str(row[2] or '').strip(),
            'filter_fingerprint': str(row[3] or '').strip(),
            'dirty': bool(row[4]),
            'last_built_at': str(row[5] or '').strip(),
            'last_accessed_at': str(row[6] or '').strip(),
            'refresh_duration_ms': int(row[7] or 0),
            'updated_at': str(row[8] or '').strip(),
        }

    def rebuild_library_summary_tables(self):
        versions = self.get_data_source_versions()
        actor_version = int(versions.get('actor_library', 0) or 0)
        prefix_version = int(versions.get('code_prefix_library', 0) or 0)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_library_summary')
            cursor.execute(
                '''
                INSERT INTO actor_library_summary (
                    actor_name, video_count, eligible_video_count, latest_release_date,
                    avfan_enrichment_status, javtxt_enrichment_status, profile_completion_status,
                    source_version, updated_at
                )
                SELECT a.name,
                       COUNT(DISTINCT relation.video_code),
                       COUNT(DISTINCT CASE WHEN entity.video_category IN (?, ?) THEN entity.code END),
                       COALESCE(MAX(NULLIF(COALESCE(NULLIF(entity.javtxt_release_date, ''), entity.release_date), '')), ''),
                       COALESCE(e.avfan_enrichment_status, ?),
                       COALESCE(e.javtxt_enrichment_status, ?),
                       COALESCE(e.enrichment_status, ''),
                       ?, CURRENT_TIMESTAMP
                FROM actors a
                LEFT JOIN video_actor_relations relation ON relation.actor_name = a.name
                LEFT JOIN video_entities entity ON entity.code = relation.video_code
                LEFT JOIN actor_enrichments e ON e.actor_name = a.name
                GROUP BY a.name
                ''',
                [VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_CO_STAR, UNENRICHED_STATUS, UNENRICHED_STATUS, actor_version],
            )
            prefix_sql = self._code_prefix_expression_sql('p.code')
            cursor.execute('DELETE FROM code_prefix_library_summary')
            cursor.execute(
                f'''
                WITH local AS (
                    SELECT {prefix_sql} AS prefix, COUNT(*) AS local_video_count
                    FROM video_entities p
                    JOIN local_video_records local_record ON local_record.code = p.code
                    WHERE TRIM(COALESCE(p.code, '')) <> ''
                      AND TRIM(COALESCE(local_record.storage_location, '')) <> ''
                      AND {prefix_sql} GLOB '*[A-Z]*'
                    GROUP BY {prefix_sql}
                ), web AS (
                    SELECT UPPER(relation.prefix) AS prefix,
                           COUNT(DISTINCT entity.code) AS web_video_count,
                           COUNT(DISTINCT CASE WHEN entity.video_category IN (?, ?) THEN entity.code END) AS eligible_video_count,
                           MIN(NULLIF(COALESCE(NULLIF(entity.javtxt_release_date, ''), entity.release_date), '')) AS earliest_release_date,
                           MAX(NULLIF(COALESCE(NULLIF(entity.javtxt_release_date, ''), entity.release_date), '')) AS latest_release_date
                    FROM video_code_prefix_relations relation
                    JOIN video_entities entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(relation.prefix, '')) <> ''
                    GROUP BY UPPER(relation.prefix)
                ), combined AS (
                    SELECT prefix FROM local UNION SELECT prefix FROM web
                )
                INSERT INTO code_prefix_library_summary (
                    prefix, local_video_count, web_video_count, eligible_video_count,
                    earliest_release_date, latest_release_date,
                    avfan_enrichment_status, javtxt_enrichment_status, source_version, updated_at
                )
                SELECT combined.prefix,
                       COALESCE(local.local_video_count, 0), COALESCE(web.web_video_count, 0),
                       COALESCE(web.eligible_video_count, 0),
                       COALESCE(web.earliest_release_date, ''), COALESCE(web.latest_release_date, ''),
                       COALESCE(e.avfan_enrichment_status, ?), COALESCE(e.javtxt_enrichment_status, ?),
                       ?, CURRENT_TIMESTAMP
                FROM combined
                LEFT JOIN local ON local.prefix = combined.prefix
                LEFT JOIN web ON web.prefix = combined.prefix
                LEFT JOIN code_prefix_enrichments e ON UPPER(e.prefix) = combined.prefix
                ''',
                [VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_CO_STAR, UNENRICHED_STATUS, UNENRICHED_STATUS, prefix_version],
            )
            conn.commit()
        return {'actor_count': self._count_table_rows('actor_library_summary'), 'code_prefix_count': self._count_table_rows('code_prefix_library_summary')}

    def _count_table_rows(self, table_name):
        with self._connect() as conn:
            row = conn.execute(f'SELECT COUNT(*) FROM {table_name}').fetchone()
        return int(row[0] or 0)

    def load_enrichment_candidate_index(self, target_kind, source_key, source_version, candidate_fingerprint, limit):
        normalized_target = str(target_kind or '').strip()
        normalized_source = str(source_key or '').strip()
        if not normalized_target or not normalized_source or int(limit or 0) <= 0:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT candidate_payload
                FROM enrichment_candidate_index
                WHERE target_kind = ? AND source_key = ?
                  AND source_version = ? AND candidate_fingerprint = ?
                  AND candidate_status = 'pending'
                ORDER BY priority DESC, updated_at, owner_key, code
                LIMIT ?
                ''',
                (
                    normalized_target,
                    normalized_source,
                    int(source_version or 0),
                    str(candidate_fingerprint or '').strip(),
                    max(1, int(limit)),
                ),
            ).fetchall()
        if not rows:
            return None
        candidates = []
        for row in rows:
            try:
                payload = json.loads(row[0] or '{}')
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                candidates.append(payload)
        return candidates

    def replace_enrichment_candidate_index(
        self,
        target_kind,
        source_key,
        candidates,
        source_version=0,
        candidate_fingerprint='',
    ):
        normalized_target = str(target_kind or '').strip()
        normalized_source = str(source_key or '').strip()
        if not normalized_target or not normalized_source:
            return 0
        values = []
        for index, candidate in enumerate(candidates or []):
            payload = dict(candidate or {})
            owner_key = str(
                payload.get('actor_name')
                or payload.get('prefix')
                or payload.get('code')
                or ''
            ).strip()
            code = standardize_video_code(payload.get('code', ''))
            if not owner_key and not code:
                continue
            values.append(
                (
                    normalized_target,
                    normalized_source,
                    owner_key,
                    code,
                    max(0, len(candidates or []) - index),
                    'pending',
                    str(payload.get('candidate_reason', '') or '').strip(),
                    int(source_version or 0),
                    str(candidate_fingerprint or '').strip(),
                    json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                )
            )
        with self._connect() as conn:
            conn.execute(
                '''
                DELETE FROM enrichment_candidate_index
                WHERE target_kind = ? AND source_key = ?
                ''',
                (normalized_target, normalized_source),
            )
            if values:
                conn.executemany(
                    '''
                    INSERT INTO enrichment_candidate_index (
                        target_kind, source_key, owner_key, code, priority, candidate_status,
                        reason, source_version, candidate_fingerprint, candidate_payload, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(target_kind, source_key, owner_key, code) DO UPDATE SET
                        priority = excluded.priority,
                        candidate_status = excluded.candidate_status,
                        reason = excluded.reason,
                        source_version = excluded.source_version,
                        candidate_fingerprint = excluded.candidate_fingerprint,
                        candidate_payload = excluded.candidate_payload,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    values,
                )
            conn.commit()
        return len(values)

    def _migrate_excluded_web_movie_table(
        self,
        table_name,
        archive_table_name,
        owner_column,
        hidden_table_name,
        hidden_column,
        owner_reason,
        filter_settings,
        batch_size,
    ):
        hidden_owners = set()
        with self._connect() as conn:
            hidden_owners = {
                str(row[0] or '').strip()
                for row in conn.execute(f'SELECT {hidden_column} FROM {hidden_table_name}').fetchall()
                if str(row[0] or '').strip()
            }

        last_owner = ''
        last_code = ''
        migrated_count = 0
        columns = (
            f'{owner_column}, code, title, author, release_date, avfan_url, page_number, '
            'javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, '
            'javtxt_release_date, author_raw, video_category, supplement_enrichment_status, '
            'supplement_enrichment_error, supplement_enriched_at'
        )
        while True:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f'''
                    SELECT {columns}
                    FROM {table_name}
                    WHERE ({owner_column} > ? OR ({owner_column} = ? AND code > ?))
                    ORDER BY {owner_column}, code
                    LIMIT ?
                    ''',
                    (last_owner, last_owner, last_code, batch_size),
                )
                rows = cursor.fetchall()
                if not rows:
                    break

                to_archive = []
                for row in rows:
                    owner = str(row[0] or '').strip()
                    movie = {
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': row[3] or '',
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': row[6] or 1,
                        'javtxt_enrichment_status': row[7] or '',
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': row[13] or '',
                        'supplement_enrichment_status': row[14] or '',
                        'supplement_enrichment_error': row[15] or '',
                        'supplement_enriched_at': row[16] or '',
                    }
                    reason = self._resolve_web_movie_exclusion_reason(
                        movie,
                        filter_settings=filter_settings,
                        owner_blacklisted=owner in hidden_owners,
                        owner_reason=owner_reason,
                    )
                    if reason:
                        to_archive.append((owner, movie, reason))

                if to_archive:
                    by_owner = {}
                    for owner, movie, reason in to_archive:
                        by_owner.setdefault(owner, []).append({**movie, 'exclude_reason': reason})
                    for owner, movies in by_owner.items():
                        self._store_excluded_web_movie_rows(
                            cursor,
                            archive_table_name,
                            owner_column,
                            owner,
                            movies,
                            ','.join(sorted({movie['exclude_reason'] for movie in movies})),
                        )
                    for owner, movie, _reason in to_archive:
                        cursor.execute(
                            f'DELETE FROM {table_name} WHERE {owner_column} = ? AND code = ?',
                            (owner, movie['code']),
                        )
                    migrated_count += len(to_archive)
                last_owner = str(rows[-1][0] or '').strip()
                last_code = str(rows[-1][1] or '').strip()
                conn.commit()
        return migrated_count

    def migrate_excluded_web_movies(self, batch_size=500):
        try:
            normalized_batch_size = max(1, int(batch_size))
        except (TypeError, ValueError):
            normalized_batch_size = 500
        filter_settings = self._load_video_category_filter_settings()
        code_count = self._migrate_excluded_web_movie_table(
            'code_prefix_movies',
            'excluded_code_prefix_movies',
            'prefix',
            'hidden_code_prefixes',
            'prefix',
            'code_blacklist',
            filter_settings,
            normalized_batch_size,
        )
        actor_count = self._migrate_excluded_web_movie_table(
            'actor_movies',
            'excluded_actor_movies',
            'actor_name',
            'hidden_actors',
            'name',
            'actor_blacklist',
            filter_settings,
            normalized_batch_size,
        )
        return {
            'code_prefix_movies': code_count,
            'actor_movies': actor_count,
            'total': code_count + actor_count,
        }

    @staticmethod
    def _resolve_web_movie_exclusion_reason(movie, filter_settings=None, owner_blacklisted=False, owner_reason=''):
        reasons = []
        if owner_blacklisted:
            reasons.append(owner_reason)
        post_enrichment_filter_hit = should_hide_video_from_library(movie, filter_settings)
        has_detail_reference = bool(
            str((movie or {}).get('javtxt_movie_id', '') or '').strip()
            or str((movie or {}).get('javtxt_url', '') or '').strip()
        )
        if should_skip_video_before_enrichment(movie, filter_settings) or (
            post_enrichment_filter_hit and has_detail_reference
        ):
            reasons.append('filter')
        return VideoDatabase._normalize_excluded_movie_reason(','.join(reasons))

    @staticmethod
    def _is_hidden_web_movie_owner(cursor, table_name, column_name, owner_value):
        cursor.execute(
            f'SELECT 1 FROM {table_name} WHERE {column_name} = ? LIMIT 1',
            (owner_value,),
        )
        return bool(cursor.fetchone())

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
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            cursor.execute('DELETE FROM video_prefix_relation_meta WHERE prefix = ?', (prefix,))
            cursor.execute('DELETE FROM video_code_prefix_relations WHERE prefix = ?', (prefix,))
            if legacy_code_prefix_movies:
                cursor.execute(f'DELETE FROM {legacy_code_prefix_movies} WHERE prefix = ?', (prefix,))
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
                if legacy_code_prefix_movies:
                    cursor.executemany(f'''
                    INSERT OR REPLACE INTO {legacy_code_prefix_movies} (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category,
                        supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', values)
                if values:
                    self._propagate_web_movie_javtxt_state_for_codes(cursor, active_codes)
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
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.prefix = relation.prefix AND meta.video_code = entity.code
                WHERE relation.prefix = ?
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
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

    def replace_canglangge_actor_candidates(self, candidates):
        normalized_rows = []
        seen = set()
        for candidate in candidates or []:
            row = dict(candidate or {})
            actor_name = str(row.get('actor_name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            seen.add(actor_name)
            prefixes = row.get('prefixes', row.get('source_prefixes', [])) or []
            if isinstance(prefixes, str):
                prefixes = [value.strip() for value in prefixes.split(',') if value.strip()]
            normalized_rows.append(
                (
                    actor_name,
                    json.dumps(sorted({str(value or '').strip().upper() for value in prefixes if str(value or '').strip()}), ensure_ascii=False),
                    str(row.get('binghuo_enrichment_status', UNENRICHED_STATUS) or UNENRICHED_STATUS).strip(),
                    str(row.get('binghuo_birthday', row.get('birthday', '')) or '').strip(),
                    str(row.get('binghuo_age', row.get('age', '')) or '').strip(),
                    str(row.get('binghuo_height', '') or '').strip(),
                    str(row.get('binghuo_bust', '') or '').strip(),
                    str(row.get('binghuo_cup', '') or '').strip().upper(),
                    str(row.get('binghuo_waist', '') or '').strip(),
                    str(row.get('binghuo_hip', '') or '').strip(),
                    str(row.get('baomu_enrichment_status', UNENRICHED_STATUS) or UNENRICHED_STATUS).strip(),
                    str(row.get('baomu_birthday', '') or '').strip(),
                    str(row.get('baomu_height', '') or '').strip(),
                    str(row.get('baomu_bust', '') or '').strip(),
                    str(row.get('baomu_cup', '') or '').strip().upper(),
                    str(row.get('baomu_waist', '') or '').strip(),
                    str(row.get('baomu_hip', '') or '').strip(),
                )
            )

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT INTO canglangge_actor_candidates (
                    actor_name, source_prefixes_json, refreshed_at, updated_at,
                    binghuo_enrichment_status, binghuo_birthday, binghuo_age,
                    binghuo_height, binghuo_bust, binghuo_cup, binghuo_waist, binghuo_hip,
                    baomu_enrichment_status, baomu_birthday, baomu_height, baomu_bust,
                    baomu_cup, baomu_waist, baomu_hip
                )
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(actor_name) DO UPDATE SET
                    source_prefixes_json = excluded.source_prefixes_json,
                    refreshed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                normalized_rows,
            )
            for actor_name, _source_prefixes, *_ in normalized_rows:
                self._refresh_canglangge_completion_status(cursor, actor_name)
            current_names = [row[0] for row in normalized_rows]
            current_placeholders = ','.join('?' for _ in current_names)
            stale_sql = f'''
                DELETE FROM canglangge_actor_candidates AS candidate
                WHERE candidate.actor_name NOT IN ({current_placeholders})
                  AND NOT EXISTS (
                      SELECT 1 FROM pending_actor_binghuo
                      WHERE actor_name = candidate.actor_name
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM pending_actor_baomu
                      WHERE actor_name = candidate.actor_name
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM enrichment_running_items
                      WHERE actor_name = candidate.actor_name
                  )
            '''
            if current_names:
                cursor.execute(stale_sql, current_names)
            else:
                cursor.execute(
                    '''
                    DELETE FROM canglangge_actor_candidates AS candidate
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pending_actor_binghuo
                        WHERE actor_name = candidate.actor_name
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM pending_actor_baomu
                        WHERE actor_name = candidate.actor_name
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM enrichment_running_items
                        WHERE actor_name = candidate.actor_name
                    )
                    '''
                )
            conn.commit()
        return len(normalized_rows)

    def list_canglangge_actor_candidates(self, actor_names=None):
        normalized_names = [
            str(value or '').strip() for value in (actor_names or []) if str(value or '').strip()
        ]
        where_sql = ''
        parameters = []
        if normalized_names:
            placeholders = ','.join('?' for _ in normalized_names)
            where_sql = f'WHERE actor_name IN ({placeholders})'
            parameters.extend(normalized_names)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT actor_name, source_prefixes_json, discovered_at, refreshed_at,
                       binghuo_enrichment_status, binghuo_last_error, binghuo_last_enriched_at,
                       binghuo_person_id, binghuo_birthday, binghuo_age, binghuo_height,
                       binghuo_bust, binghuo_cup, binghuo_measurements_raw, binghuo_waist, binghuo_hip,
                       baomu_enrichment_status, baomu_last_error, baomu_last_enriched_at,
                       baomu_birthday, baomu_height, baomu_bust, baomu_cup,
                       baomu_measurements_raw, baomu_waist, baomu_hip,
                       candidate_status, retry_count, last_error, updated_at,
                       binghuo_completion_status, baomu_completion_status
                FROM canglangge_actor_candidates
                {where_sql}
                ORDER BY actor_name ASC
                ''',
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            prefixes = []
            try:
                prefixes = list(json.loads(row[1] or '[]') or [])
            except (TypeError, ValueError):
                prefixes = []
            result.append({
                'actor_name': row[0] or '',
                'prefixes': prefixes,
                'birthday': row[8] or row[19] or '',
                'age': row[9] or '',
                'discovered_at': row[2] or '',
                'refreshed_at': row[3] or '',
                'binghuo_enrichment_status': row[4] or UNENRICHED_STATUS,
                'binghuo_completion_status': row[30] or '状态1',
                'binghuo_last_error': row[5] or '',
                'binghuo_last_enriched_at': row[6] or '',
                'binghuo_person_id': row[7] or '',
                'binghuo_birthday': row[8] or '',
                'binghuo_age': row[9] or '',
                'binghuo_height': row[10] or '',
                'binghuo_bust': row[11] or '',
                'binghuo_cup': row[12] or '',
                'binghuo_measurements_raw': row[13] or '',
                'binghuo_waist': row[14] or '',
                'binghuo_hip': row[15] or '',
                'baomu_enrichment_status': row[16] or UNENRICHED_STATUS,
                'baomu_completion_status': row[31] or '状态1',
                'baomu_last_error': row[17] or '',
                'baomu_last_enriched_at': row[18] or '',
                'baomu_birthday': row[19] or '',
                'baomu_height': row[20] or '',
                'baomu_bust': row[21] or '',
                'baomu_cup': row[22] or '',
                'baomu_measurements_raw': row[23] or '',
                'baomu_waist': row[24] or '',
                'baomu_hip': row[25] or '',
                'candidate_status': row[26] or 'pending',
                'retry_count': int(row[27] or 0),
                'last_error': row[28] or '',
                'updated_at': row[29] or '',
            })
        return result

    def _refresh_canglangge_completion_status(self, cursor, actor_name):
        row = cursor.execute(
            '''
            SELECT binghuo_enrichment_status, binghuo_person_id,
                   binghuo_birthday, binghuo_age, binghuo_height, binghuo_bust,
                   binghuo_cup, binghuo_waist, binghuo_hip,
                   baomu_enrichment_status, baomu_birthday, baomu_height,
                   baomu_bust, baomu_cup, baomu_waist, baomu_hip
            FROM canglangge_actor_candidates
            WHERE actor_name = ?
            ''',
            (str(actor_name or '').strip(),),
        ).fetchone()
        if row is None:
            return
        candidate = {
            'binghuo_enrichment_status': row[0] or UNENRICHED_STATUS,
            'binghuo_person_id': row[1] or '',
            'binghuo_birthday': row[2] or '',
            'binghuo_age': row[3] or '',
            'binghuo_height': row[4] or '',
            'binghuo_bust': row[5] or '',
            'binghuo_cup': row[6] or '',
            'binghuo_waist': row[7] or '',
            'binghuo_hip': row[8] or '',
            'baomu_enrichment_status': row[9] or UNENRICHED_STATUS,
            'baomu_birthday': row[10] or '',
            'baomu_height': row[11] or '',
            'baomu_bust': row[12] or '',
            'baomu_cup': row[13] or '',
            'baomu_waist': row[14] or '',
            'baomu_hip': row[15] or '',
        }
        cursor.execute(
            '''
            UPDATE canglangge_actor_candidates
            SET binghuo_completion_status = ?,
                baomu_completion_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE actor_name = ?
            ''',
            (
                build_actor_source_completion_status(candidate, BINGHUO_ACTOR_SOURCE),
                build_actor_source_completion_status(candidate, BAOMU_ACTOR_SOURCE),
                str(actor_name or '').strip(),
            ),
        )

    def delete_canglangge_actor_candidates(self, actor_names):
        normalized_names = [
            str(value or '').strip() for value in (actor_names or []) if str(value or '').strip()
        ]
        if not normalized_names:
            return 0
        placeholders = ','.join('?' for _ in normalized_names)
        with self._connect() as conn:
            cursor = conn.execute(
                f'DELETE FROM canglangge_actor_candidates WHERE actor_name IN ({placeholders})',
                normalized_names,
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def list_canglangge_actor_task_names(self, actor_names):
        normalized_names = [
            str(value or '').strip() for value in (actor_names or []) if str(value or '').strip()
        ]
        if not normalized_names:
            return set()
        placeholders = ','.join('?' for _ in normalized_names)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT actor_name FROM pending_actor_binghuo WHERE actor_name IN ({placeholders})
                UNION
                SELECT actor_name FROM pending_actor_baomu WHERE actor_name IN ({placeholders})
                UNION
                SELECT actor_name FROM enrichment_running_items WHERE actor_name IN ({placeholders})
                ''',
                [*normalized_names, *normalized_names, *normalized_names],
            ).fetchall()
        return {str(row[0] or '').strip() for row in rows if str(row[0] or '').strip()}

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

    def list_sql_enrichment_candidates(self, task_kind, source_key, limit):
        """Select simple enrichment candidates in SQLite using canonical codes."""
        normalized_task = str(task_kind or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key)
        normalized_limit = max(0, int(limit or 0))
        if normalized_limit <= 0:
            return []

        if normalized_task not in {'actor', 'actor_birthday'}:
            return []

        pending_table = {
            ('actor', AVFAN_VIDEO_SOURCE): 'pending_actor_avfan',
            ('actor_birthday', BINGHUO_ACTOR_SOURCE): 'pending_actor_binghuo',
            ('actor_birthday', BAOMU_ACTOR_SOURCE): 'pending_actor_baomu',
        }.get((normalized_task, normalized_source))
        queue_exclusion_sql = ''
        if pending_table:
            queue_exclusion_sql = f'''
                      AND NOT EXISTS (
                                SELECT 1 FROM {pending_table} AS pending
                                WHERE pending.actor_name = a.name
                                  AND pending.status IN ('pending', 'failed')
                            )
                      AND NOT EXISTS (
                                SELECT 1 FROM enrichment_running_items AS running
                                WHERE running.task_kind = ?
                                  AND running.origin_table = ?
                                  AND running.actor_name = a.name
                            )
            '''

        with self._connect() as conn:
            if normalized_task == 'actor' and normalized_source == AVFAN_VIDEO_SOURCE:
                rows = conn.execute(
                    f'''
                    SELECT a.name
                    FROM actors AS a
                    LEFT JOIN actor_enrichments AS e ON e.actor_name = a.name
                    WHERE NOT EXISTS (
                              SELECT 1 FROM hidden_actors AS h WHERE h.name = a.name
                          )
                      AND COALESCE(NULLIF(TRIM(e.avfan_enrichment_status), ''), ?) IN (?, ?)
                      {queue_exclusion_sql}
                    ORDER BY UPPER(a.name) ASC
                    LIMIT ?
                    ''',
                    (
                        UNENRICHED_STATUS, UNENRICHED_STATUS, FAILED_STATUS,
                        normalized_task, pending_table, normalized_limit,
                    ),
                ).fetchall()
            elif normalized_task == 'actor_birthday' and normalized_source == BINGHUO_ACTOR_SOURCE:
                rows = conn.execute(
                    f'''
                    SELECT a.name
                    FROM actors AS a
                    LEFT JOIN actor_enrichments AS e ON e.actor_name = a.name
                    WHERE NOT EXISTS (
                              SELECT 1 FROM hidden_actors AS h WHERE h.name = a.name
                          )
                          {queue_exclusion_sql}
                      AND COALESCE(NULLIF(TRIM(e.binghuo_enrichment_status), ''), ?) NOT IN (?, ?)
                      AND (
                            (
                                COALESCE(NULLIF(TRIM(a.birthday), ''),
                                         NULLIF(TRIM(e.binghuo_birthday), ''), '') = ''
                                AND NOT (
                                    TRIM(COALESCE(e.binghuo_birthday, '')) <> ''
                                    OR TRIM(COALESCE(e.binghuo_age, '')) <> ''
                                    OR TRIM(COALESCE(e.binghuo_height, '')) <> ''
                                    OR TRIM(COALESCE(e.binghuo_bust, '')) <> ''
                                    OR TRIM(COALESCE(e.binghuo_waist, '')) <> ''
                                    OR TRIM(COALESCE(e.binghuo_hip, '')) <> ''
                                )
                            )
                            OR (
                                COALESCE(NULLIF(TRIM(a.birthday), ''),
                                         NULLIF(TRIM(e.binghuo_birthday), ''), '') <> ''
                                AND (
                                    TRIM(COALESCE(e.binghuo_person_id, '')) = ''
                                    OR (
                                        TRIM(COALESCE(e.binghuo_height, '')) = ''
                                        AND TRIM(COALESCE(e.binghuo_bust, '')) = ''
                                        AND TRIM(COALESCE(e.binghuo_waist, '')) = ''
                                        AND TRIM(COALESCE(e.binghuo_hip, '')) = ''
                                    )
                                    OR NOT (
                                        TRIM(COALESCE(e.binghuo_birthday, '')) <> ''
                                        OR TRIM(COALESCE(e.binghuo_age, '')) <> ''
                                        OR TRIM(COALESCE(e.binghuo_height, '')) <> ''
                                        OR TRIM(COALESCE(e.binghuo_bust, '')) <> ''
                                        OR TRIM(COALESCE(e.binghuo_waist, '')) <> ''
                                        OR TRIM(COALESCE(e.binghuo_hip, '')) <> ''
                                    )
                                )
                            )
                          )
                    ORDER BY UPPER(a.name) ASC
                    LIMIT ?
                    ''',
                    (
                        normalized_task, pending_table,
                        UNENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS,
                        normalized_limit,
                    ),
                ).fetchall()
            elif normalized_task == 'actor_birthday' and normalized_source == BAOMU_ACTOR_SOURCE:
                rows = conn.execute(
                    f'''
                    SELECT a.name
                    FROM actors AS a
                    LEFT JOIN actor_enrichments AS e ON e.actor_name = a.name
                    WHERE NOT EXISTS (
                              SELECT 1 FROM hidden_actors AS h WHERE h.name = a.name
                          )
                          {queue_exclusion_sql}
                      AND COALESCE(e.binghuo_enrichment_status, ?) <> ?
                      AND COALESCE(NULLIF(TRIM(e.baomu_enrichment_status), ''), ?) = ?
                      AND (
                            COALESCE(NULLIF(TRIM(a.birthday), ''),
                                     NULLIF(TRIM(e.binghuo_birthday), ''), '') = ''
                            OR TRIM(COALESCE(e.binghuo_height, '')) = ''
                            OR TRIM(COALESCE(e.binghuo_bust, '')) = ''
                            OR TRIM(COALESCE(e.binghuo_cup, '')) = ''
                            OR TRIM(COALESCE(e.binghuo_waist, '')) = ''
                            OR TRIM(COALESCE(e.binghuo_hip, '')) = ''
                          )
                    ORDER BY UPPER(a.name) ASC
                    LIMIT ?
                    ''',
                    (
                        normalized_task,
                        pending_table,
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        normalized_limit,
                    ),
                ).fetchall()
            else:
                return []

        return [{'actor_name': str(row[0] or '').strip()} for row in rows if str(row[0] or '').strip()]

    def list_sql_code_prefix_candidates(self, source_key, limit):
        """Select AVFan code-prefix candidates without loading library rows."""
        if normalize_video_enrichment_source(source_key) != AVFAN_VIDEO_SOURCE:
            return []
        normalized_limit = max(0, int(limit or 0))
        if normalized_limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                '''
                WITH prefix_keys(prefix) AS (
                    SELECT prefix FROM code_prefix_enrichments
                    UNION
                    SELECT UPPER(prefix) FROM video_code_prefix_relations
                )
                SELECT prefix_keys.prefix
                FROM prefix_keys
                LEFT JOIN code_prefix_enrichments AS e
                       ON e.prefix = prefix_keys.prefix
                WHERE TRIM(COALESCE(prefix_keys.prefix, '')) <> ''
                  AND NOT EXISTS (
                          SELECT 1 FROM hidden_code_prefixes AS h
                          WHERE h.prefix = prefix_keys.prefix
                      )
                  AND COALESCE(NULLIF(TRIM(e.avfan_enrichment_status), ''), ?) IN (?, ?)
                ORDER BY prefix_keys.prefix ASC
                LIMIT ?
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS, FAILED_STATUS, normalized_limit),
            ).fetchall()
        return [{'prefix': str(row[0] or '').strip().upper()} for row in rows if str(row[0] or '').strip()]

    def list_sql_javtxt_candidate_items(self, task_kind, limit):
        """Return a bounded JAVTXT candidate set with its cache joined in SQL."""
        normalized_task = str(task_kind or '').strip()
        normalized_limit = max(0, int(limit or 0))
        if normalized_task not in {'actor', 'code_prefix'} or normalized_limit <= 0:
            return []

        if normalized_task == 'actor':
            table_name = '''(
                SELECT relation.actor_name, entity.code, entity.title, entity.author,
                       entity.release_date, entity.javtxt_enrichment_status,
                       entity.javtxt_release_date, entity.javtxt_movie_id, entity.javtxt_url,
                       entity.javtxt_tags, entity.javtxt_actors_raw AS author_raw,
                       entity.video_category
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
            )'''
            owner_column = 'actor_name'
            ready_join = (
                'JOIN actor_enrichments AS ready '
                'ON ready.actor_name = source.actor_name '
                'AND ready.avfan_enrichment_status = ? '
                'AND COALESCE(ready.avfan_total_videos, 0) > 0'
            )
            pending_table = 'pending_actor_javtxt'
            order_sql = 'source.actor_name ASC, source.code ASC'
            owner_select = 'source.actor_name'
        else:
            table_name = '''(
                SELECT relation.prefix, entity.code, entity.title, entity.author,
                       entity.release_date, entity.javtxt_enrichment_status,
                       entity.javtxt_release_date, entity.javtxt_movie_id, entity.javtxt_url,
                       entity.javtxt_tags, entity.javtxt_actors_raw AS author_raw,
                       entity.video_category
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
            )'''
            owner_column = 'prefix'
            ready_join = (
                'JOIN code_prefix_enrichments AS ready '
                'ON ready.prefix = source.prefix '
                'AND ready.avfan_enrichment_status = ? '
                'AND COALESCE(ready.avfan_total_videos, 0) > 0'
            )
            pending_table = 'pending_code_prefix_javtxt'
            order_sql = 'source.prefix ASC, source.code ASC'
            owner_select = 'source.prefix'

        with self._connect() as conn:
            cache_table = self._processed_video_storage_target(conn.cursor())
            rows = conn.execute(
                f'''
                SELECT {owner_select} AS owner_key,
                       source.code, source.title, source.author, source.release_date,
                       source.javtxt_enrichment_status, source.javtxt_release_date,
                       source.javtxt_movie_id, source.javtxt_url, source.javtxt_tags,
                       source.author_raw, source.video_category,
                       cache.javtxt_actors AS cached_javtxt_actors,
                       cache.javtxt_actors_raw AS cached_javtxt_actors_raw,
                       cache.javtxt_movie_id AS cached_javtxt_movie_id,
                       cache.javtxt_url AS cached_javtxt_url,
                       cache.javtxt_tags AS cached_javtxt_tags,
                       cache.javtxt_enrichment_status AS cached_javtxt_enrichment_status,
                       cache.javtxt_release_date AS cached_javtxt_release_date,
                       cache.release_date AS cached_release_date
                FROM {table_name} AS source
                {ready_join}
                LEFT JOIN {cache_table} AS cache ON cache.code = source.code
                WHERE COALESCE(NULLIF(TRIM(source.javtxt_enrichment_status), ''), ?) IN (?, ?)
                  AND COALESCE(
                        NULLIF(source.javtxt_release_date, ''),
                        NULLIF(cache.javtxt_release_date, ''),
                        NULLIF(source.release_date, ''),
                        NULLIF(cache.release_date, '')
                      ) >= '2020-01-01'
                  AND source.code LIKE '%-%'
                  AND NOT EXISTS (
                        SELECT 1 FROM {pending_table} AS pending
                        WHERE pending.{owner_column} = source.{owner_column}
                          AND pending.code = source.code
                          AND pending.status IN ('pending', 'failed')
                      )
                  AND NOT EXISTS (
                        SELECT 1 FROM enrichment_running_items AS running
                        WHERE running.task_kind = ?
                          AND running.origin_table = ?
                          AND running.{owner_column} = source.{owner_column}
                          AND running.code = source.code
                      )
                ORDER BY {order_sql}
                LIMIT ?
                ''',
                (
                    ENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    FAILED_STATUS,
                    normalized_task,
                    pending_table,
                    normalized_limit,
                ),
            ).fetchall()

        result = []
        for row in rows:
            owner_key = str(row[0] or '').strip()
            current = {
                'code': row[1] or '',
                'title': row[2] or '',
                'author': row[3] or '',
                'release_date': row[4] or '',
                'javtxt_enrichment_status': row[5] or UNENRICHED_STATUS,
                'javtxt_release_date': row[6] or '',
                'javtxt_movie_id': row[7] or '',
                'javtxt_url': row[8] or '',
                'javtxt_tags': row[9] or '',
                'author_raw': row[10] or '',
                'video_category': row[11] or '',
                'cached_javtxt_actors': row[12] or '',
                'cached_javtxt_actors_raw': row[13] or '',
                'cached_javtxt_movie_id': row[14] or '',
                'cached_javtxt_url': row[15] or '',
                'cached_javtxt_tags': row[16] or '',
                'cached_javtxt_enrichment_status': row[17] or UNENRICHED_STATUS,
                'cached_javtxt_release_date': row[18] or '',
                'cached_release_date': row[19] or '',
            }
            if normalized_task == 'actor':
                current['actor_name'] = owner_key
            else:
                current['prefix'] = owner_key
            result.append(current)
        return result

    def list_sql_supplement_candidates(
        self,
        target_kind,
        limit,
        include_queued=False,
        running_plan_id='',
    ):
        """Pre-filter supplement candidates, optionally including a plan's running rows."""
        normalized_target = str(target_kind or '').strip()
        normalized_limit = max(0, int(limit or 0))
        if normalized_target in {'actor', 'code_prefix'}:
            return self._list_normalized_supplement_candidates(
                normalized_target,
                normalized_limit,
                include_queued=include_queued,
                running_plan_id=running_plan_id,
            )
        table_config = {
            'video': ('processed_videos', 'code', 'pending_video_avfan', 'video'),
            'actor': ('actor_movies', 'actor_name', 'pending_actor_supplement', 'actor'),
            'code_prefix': ('code_prefix_movies', 'prefix', 'pending_code_prefix_supplement', 'code_prefix'),
        }
        if normalized_target not in table_config or normalized_limit <= 0:
            return []
        table_name, owner_column, pending_table, task_kind = table_config[normalized_target]
        owner_select = f'source.{owner_column}' if normalized_target != 'video' else "''"
        source_alias = 'source'
        cache_join = ''
        if normalized_target == 'video':
            author_column = 'source.javtxt_actors'
            author_raw_column = 'source.javtxt_actors_raw'
            avfan_url_column = "''"
            page_number_column = '1'
            javtxt_status_column = 'source.javtxt_enrichment_status'
            javtxt_movie_id_column = 'source.javtxt_movie_id'
            javtxt_url_column = 'source.javtxt_url'
            javtxt_tags_column = 'source.javtxt_tags'
            javtxt_release_date_column = 'source.javtxt_release_date'
            video_category_column = 'source.video_category'
        else:
            cache_join = 'LEFT JOIN video_entities AS cache ON cache.code = source.code'
            author_column = 'COALESCE(NULLIF(TRIM(cache.javtxt_actors), \'\'), source.author)'
            author_raw_column = 'COALESCE(NULLIF(TRIM(cache.javtxt_actors_raw), \'\'), source.author_raw)'
            avfan_url_column = 'source.avfan_url'
            page_number_column = 'source.page_number'
            javtxt_status_column = 'COALESCE(NULLIF(TRIM(source.javtxt_enrichment_status), \'\'), cache.javtxt_enrichment_status)'
            javtxt_movie_id_column = 'COALESCE(NULLIF(TRIM(source.javtxt_movie_id), \'\'), cache.javtxt_movie_id)'
            javtxt_url_column = 'COALESCE(NULLIF(TRIM(source.javtxt_url), \'\'), cache.javtxt_url)'
            javtxt_tags_column = 'COALESCE(NULLIF(TRIM(source.javtxt_tags), \'\'), cache.javtxt_tags)'
            javtxt_release_date_column = 'COALESCE(NULLIF(TRIM(source.javtxt_release_date), \'\'), cache.javtxt_release_date)'
            video_category_column = 'COALESCE(NULLIF(TRIM(source.video_category), \'\'), cache.video_category)'
        owner_pending = f'pending.{owner_column} = source.{owner_column}' if normalized_target != 'video' else 'pending.code = source.code'
        owner_running = f'running.{owner_column} = source.{owner_column}' if normalized_target != 'video' else 'running.code = source.code'
        pending_exclusion_sql = '' if include_queued else f'''
                  AND NOT EXISTS (
                        SELECT 1 FROM {pending_table} AS pending
                        WHERE {owner_pending}
                          AND pending.code = source.code
                          AND pending.status IN ('pending', 'failed')
                      )'''
        normalized_running_plan_id = str(running_plan_id or '').strip()
        if normalized_running_plan_id:
            running_exclusion_sql = f'''
                  AND NOT EXISTS (
                        SELECT 1 FROM enrichment_running_items AS running
                        WHERE running.task_kind = ?
                          AND running.origin_table = ?
                          AND {owner_running}
                          AND running.code = source.code
                          AND NOT (
                                running.plan_id = ?
                                AND running.task_kind = ?
                          )
                      )'''
            running_parameters = [
                task_kind,
                pending_table,
                normalized_running_plan_id,
                task_kind,
            ]
        else:
            running_exclusion_sql = f'''
                  AND NOT EXISTS (
                        SELECT 1 FROM enrichment_running_items AS running
                        WHERE running.task_kind = ?
                          AND running.origin_table = ?
                          AND {owner_running}
                          AND running.code = source.code
                      )'''
            running_parameters = [task_kind, pending_table]
        with self._connect() as conn:
            if normalized_target == 'video':
                table_name = self._processed_video_storage_target(conn.cursor())
            rows = conn.execute(
                f'''
                SELECT {owner_select} AS owner_key,
                       source.code, source.title, {author_column},
                       source.release_date, {avfan_url_column}, {page_number_column},
                       {javtxt_status_column},
                       {javtxt_movie_id_column}, {javtxt_url_column},
                       {javtxt_tags_column}, {javtxt_release_date_column},
                       {author_raw_column}, {video_category_column},
                       source.supplement_enrichment_status
                FROM {table_name} AS source
                {cache_join}
                WHERE COALESCE(NULLIF(TRIM(source.supplement_enrichment_status), ''), ?) = ?
                  AND source.code LIKE '%-%'
                  AND (
                        (
                            (TRIM(COALESCE({javtxt_movie_id_column}, '')) <> ''
                             OR TRIM(COALESCE({javtxt_url_column}, '')) <> '')
                            AND LOWER(TRIM(COALESCE({author_column}, ''))) IN (
                                '', '-', '--', 'na', 'n/a', 'none', 'null', 'unknown',
                                '无', '無', '暂无', '暫無', '未知', '无记录', '無記錄',
                                '未公开', '未公開'
                            )
                        )
                        OR (
                            COALESCE(NULLIF(TRIM({javtxt_status_column}), ''), ?) IN (?, ?)
                            AND (
                                LOWER(TRIM(COALESCE({author_column}, ''))) IN (
                                    '', '-', '--', 'na', 'n/a', 'none', 'null', 'unknown',
                                    '无', '無', '暂无', '暫無', '未知', '无记录', '無記錄',
                                    '未公开', '未公開'
                                )
                                OR TRIM(COALESCE(source.title, '')) = ''
                                OR TRIM(COALESCE(source.release_date, '')) = ''
                            )
                        )
                      )
                  {pending_exclusion_sql}
                  {running_exclusion_sql}
                ORDER BY source.code ASC
                LIMIT ?
                ''',
                (
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    NO_SEARCH_RESULTS_STATUS,
                    NO_VIDEO_DETAIL_STATUS,
                    *running_parameters,
                    normalized_limit,
                ),
            ).fetchall()

        result = []
        for row in rows:
            current = {
                'code': row[1] or '',
                'title': row[2] or '',
                'author': row[3] or '',
                'release_date': row[4] or '',
                'avfan_url': row[5] or '',
                'page_number': int(row[6] or 1),
                'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[8] or '',
                'javtxt_url': row[9] or '',
                'javtxt_tags': row[10] or '',
                'javtxt_release_date': row[11] or '',
                'author_raw': row[12] or '',
                'video_category': row[13] or '',
                'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
            }
            if normalized_target == 'actor':
                current['actor_name'] = row[0] or ''
            elif normalized_target == 'code_prefix':
                current['prefix'] = row[0] or ''
            result.append(current)
        return result

    def _list_normalized_supplement_candidates(
        self,
        target_kind,
        limit,
        include_queued=False,
        running_plan_id='',
    ):
        if int(limit or 0) <= 0:
            return []
        is_actor = str(target_kind or '').strip() == 'actor'
        relation_table = 'video_actor_relations' if is_actor else 'video_code_prefix_relations'
        owner_column = 'actor_name' if is_actor else 'prefix'
        owner_select = f'relation.{owner_column}'
        pending_table = 'pending_actor_supplement' if is_actor else 'pending_code_prefix_supplement'
        task_kind = 'actor' if is_actor else 'code_prefix'
        owner_pending = f'pending.{owner_column} = relation.{owner_column}'
        owner_running = f'running.{owner_column} = relation.{owner_column}'
        pending_exclusion_sql = '' if include_queued else f'''
            AND NOT EXISTS (
                SELECT 1 FROM {pending_table} AS pending
                WHERE {owner_pending}
                  AND pending.code = source.code
                  AND pending.status IN ('pending', 'failed')
            )'''
        normalized_plan_id = str(running_plan_id or '').strip()
        if normalized_plan_id:
            running_exclusion_sql = f'''
                AND NOT EXISTS (
                    SELECT 1 FROM enrichment_running_items AS running
                    WHERE running.task_kind = ?
                      AND running.origin_table = ?
                      AND {owner_running}
                      AND running.code = source.code
                      AND NOT (running.plan_id = ? AND running.task_kind = ?)
                )'''
            running_parameters = [task_kind, pending_table, normalized_plan_id, task_kind]
        else:
            running_exclusion_sql = f'''
                AND NOT EXISTS (
                    SELECT 1 FROM enrichment_running_items AS running
                    WHERE running.task_kind = ?
                      AND running.origin_table = ?
                      AND {owner_running}
                      AND running.code = source.code
                )'''
            running_parameters = [task_kind, pending_table]
        owner_filter = ''
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT {owner_select} AS owner_key,
                       source.code, source.title,
                       COALESCE(NULLIF(TRIM(source.javtxt_actors), ''), source.author),
                       source.release_date, source.avfan_url, 1,
                       source.javtxt_enrichment_status, source.javtxt_movie_id,
                       source.javtxt_url, source.javtxt_tags, source.javtxt_release_date,
                       source.javtxt_actors_raw, source.video_category,
                       source.supplement_enrichment_status
                FROM video_entities AS source
                JOIN {relation_table} AS relation ON relation.video_code = source.code
                WHERE COALESCE(NULLIF(TRIM(source.supplement_enrichment_status), ''), ?) = ?
                  AND source.code LIKE '%-%'
                  AND (
                        (
                            (TRIM(COALESCE(source.javtxt_movie_id, '')) <> ''
                             OR TRIM(COALESCE(source.javtxt_url, '')) <> '')
                            AND LOWER(TRIM(COALESCE(source.javtxt_actors, source.author, ''))) IN (
                                '', '-', '--', 'na', 'n/a', 'none', 'null', 'unknown',
                                '无', '無', '暂无', '暫無', '未知', '无记录', '無記錄',
                                '未公开', '未公開'
                            )
                        )
                        OR (
                            COALESCE(NULLIF(TRIM(source.javtxt_enrichment_status), ''), ?) IN (?, ?)
                            AND (
                                LOWER(TRIM(COALESCE(source.javtxt_actors, source.author, ''))) IN (
                                    '', '-', '--', 'na', 'n/a', 'none', 'null', 'unknown',
                                    '无', '無', '暂无', '暫無', '未知', '无记录', '無記錄',
                                    '未公开', '未公開'
                                )
                                OR TRIM(COALESCE(source.title, '')) = ''
                                OR TRIM(COALESCE(source.release_date, '')) = ''
                            )
                        )
                      )
                  {owner_filter}
                  {pending_exclusion_sql}
                  {running_exclusion_sql}
                ORDER BY source.code ASC
                LIMIT ?
                ''',
                (
                    UNENRICHED_STATUS, UNENRICHED_STATUS, UNENRICHED_STATUS,
                    NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS,
                    *running_parameters, int(limit or 0),
                ),
            ).fetchall()
        result = []
        for row in rows:
            current = {
                'code': row[1] or '', 'title': row[2] or '', 'author': row[3] or '',
                'release_date': row[4] or '', 'avfan_url': row[5] or '', 'page_number': 1,
                'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[8] or '', 'javtxt_url': row[9] or '',
                'javtxt_tags': row[10] or '', 'javtxt_release_date': row[11] or '',
                'author_raw': row[12] or '', 'video_category': row[13] or '',
                'supplement_enrichment_status': row[14] or UNENRICHED_STATUS,
            }
            current[owner_column] = row[0] or ''
            result.append(current)
        return result

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
                FROM video_entities AS p
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

    def list_actor_enrichment_refresh_times(self, actor_names=None):
        return self._list_library_enrichment_refresh_times(
            'actor_enrichment_refresh_times',
            'actor_name',
            actor_names,
            uppercase=False,
        )

    def list_code_prefix_enrichment_refresh_times(self, prefixes=None):
        return self._list_library_enrichment_refresh_times(
            'code_prefix_enrichment_refresh_times',
            'prefix',
            prefixes,
            uppercase=True,
        )

    def _list_library_enrichment_refresh_times(self, table_name, entity_column, entities, uppercase=False):
        normalized_entities = []
        seen = set()
        for entity in entities or []:
            normalized = str(entity or '').strip()
            if uppercase:
                normalized = normalized.upper()
            if not normalized or normalized in seen:
                continue
            normalized_entities.append(normalized)
            seen.add(normalized)

        where_sql = ''
        parameters = []
        if entities is not None:
            if not normalized_entities:
                return {}
            placeholders = ','.join('?' for _ in normalized_entities)
            where_sql = f'WHERE {entity_column} IN ({placeholders})'
            parameters.extend(normalized_entities)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT {entity_column}, source_key, last_completed_at, update_status
                FROM {table_name}
                {where_sql}
                ''',
                parameters,
            )
            return {
                (str(row[0] or ''), str(row[1] or '')): {
                    entity_column: str(row[0] or ''),
                    'source_key': str(row[1] or ''),
                    'last_completed_at': str(row[2] or ''),
                    'update_status': str(row[3] or ''),
                }
                for row in cursor.fetchall()
            }

    def record_actor_enrichment_refresh_completion(
        self,
        actor_name,
        source_key,
        update_status='',
        completed_at=None,
    ):
        self._record_library_enrichment_refresh_completion(
            'actor_enrichment_refresh_times',
            'actor_name',
            actor_name,
            source_key,
            update_status,
            completed_at,
            uppercase=False,
        )

    def record_code_prefix_enrichment_refresh_completion(
        self,
        prefix,
        source_key,
        update_status='',
        completed_at=None,
    ):
        self._record_library_enrichment_refresh_completion(
            'code_prefix_enrichment_refresh_times',
            'prefix',
            prefix,
            source_key,
            update_status,
            completed_at,
            uppercase=True,
        )

    def _record_library_enrichment_refresh_completion(
        self,
        table_name,
        entity_column,
        entity,
        source_key,
        update_status,
        completed_at,
        uppercase,
    ):
        normalized_entity = str(entity or '').strip()
        if uppercase:
            normalized_entity = normalized_entity.upper()
        if not normalized_entity:
            return
        normalized_source = normalize_video_enrichment_source(source_key)
        timestamp = str(completed_at or '').strip() or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        normalized_update_status = str(update_status or '').strip()
        with self._connect() as conn:
            conn.execute(
                f'''
                INSERT INTO {table_name} ({entity_column}, source_key, last_completed_at, update_status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT({entity_column}, source_key) DO UPDATE SET
                    last_completed_at = excluded.last_completed_at,
                    update_status = CASE
                        WHEN excluded.update_status <> '' THEN excluded.update_status
                        ELSE {table_name}.update_status
                    END
                ''',
                (normalized_entity, normalized_source, timestamp, normalized_update_status),
            )
            conn.commit()

    def update_actor_enrichment_refresh_statuses(self, statuses):
        self._update_library_enrichment_refresh_statuses(
            'actor_enrichment_refresh_times',
            'actor_name',
            statuses,
            uppercase=False,
        )

    def update_code_prefix_enrichment_refresh_statuses(self, statuses):
        self._update_library_enrichment_refresh_statuses(
            'code_prefix_enrichment_refresh_times',
            'prefix',
            statuses,
            uppercase=True,
        )

    def _update_library_enrichment_refresh_statuses(
        self,
        table_name,
        entity_column,
        statuses,
        uppercase,
    ):
        values = []
        for entity, update_status in dict(statuses or {}).items():
            normalized_entity = str(entity or '').strip()
            if uppercase:
                normalized_entity = normalized_entity.upper()
            if normalized_entity:
                values.append((str(update_status or '').strip(), normalized_entity))
        if not values:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                f'UPDATE {table_name} SET update_status = ? WHERE {entity_column} = ?',
                values,
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def list_expired_actor_enrichment_entities(self, source_key, now=None):
        return self._list_expired_library_enrichment_entities(
            self.list_actor_enrichment_refresh_times(),
            source_key,
            now,
        )

    def list_expired_code_prefix_enrichment_entities(self, source_key, now=None):
        return self._list_expired_library_enrichment_entities(
            self.list_code_prefix_enrichment_refresh_times(),
            source_key,
            now,
        )

    @staticmethod
    def _list_expired_library_enrichment_entities(records, source_key, now):
        normalized_source = normalize_video_enrichment_source(source_key)
        return {
            entity
            for (entity, current_source), record in dict(records or {}).items()
            if current_source == normalized_source
            and is_library_refresh_expired(
                record.get('last_completed_at', ''),
                record.get('update_status', ''),
                now=now,
            )
        }

    def record_actor_expired_refresh_history(
        self,
        actor_name,
        source_key,
        previous_video_count,
        current_video_count,
        completed_at=None,
    ):
        self._record_library_expired_refresh_history(
            'actor_expired_refresh_history',
            'actor_name',
            actor_name,
            source_key,
            previous_video_count,
            current_video_count,
            completed_at,
            uppercase=False,
        )

    def record_code_prefix_expired_refresh_history(
        self,
        prefix,
        source_key,
        previous_video_count,
        current_video_count,
        completed_at=None,
    ):
        self._record_library_expired_refresh_history(
            'code_prefix_expired_refresh_history',
            'prefix',
            prefix,
            source_key,
            previous_video_count,
            current_video_count,
            completed_at,
            uppercase=True,
        )

    def _record_library_expired_refresh_history(
        self,
        table_name,
        entity_column,
        entity,
        source_key,
        previous_video_count,
        current_video_count,
        completed_at,
        uppercase,
    ):
        normalized_entity = str(entity or '').strip()
        if uppercase:
            normalized_entity = normalized_entity.upper()
        previous_count = max(0, int(previous_video_count or 0))
        current_count = max(0, int(current_video_count or 0))
        timestamp = str(completed_at or '').strip() or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._connect() as conn:
            conn.execute(
                f'''
                INSERT INTO {table_name} (
                    {entity_column}, source_key, previous_video_count,
                    current_video_count, added_video_count, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    normalized_entity,
                    normalize_video_enrichment_source(source_key),
                    previous_count,
                    current_count,
                    max(0, current_count - previous_count),
                    timestamp,
                ),
            )
            conn.commit()

    def list_actor_expired_refresh_history(self, actor_name=None):
        return self._list_library_expired_refresh_history(
            'actor_expired_refresh_history',
            'actor_name',
            actor_name,
            uppercase=False,
        )

    def list_code_prefix_expired_refresh_history(self, prefix=None):
        return self._list_library_expired_refresh_history(
            'code_prefix_expired_refresh_history',
            'prefix',
            prefix,
            uppercase=True,
        )

    def _list_library_expired_refresh_history(self, table_name, entity_column, entity, uppercase):
        normalized_entity = str(entity or '').strip()
        if uppercase:
            normalized_entity = normalized_entity.upper()
        where_sql = f'WHERE {entity_column} = ?' if normalized_entity else ''
        parameters = (normalized_entity,) if normalized_entity else ()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT id, {entity_column}, source_key, previous_video_count,
                       current_video_count, added_video_count, completed_at
                FROM {table_name}
                {where_sql}
                ORDER BY id DESC
                ''',
                parameters,
            )
            return [
                {
                    'id': int(row[0] or 0),
                    entity_column: str(row[1] or ''),
                    'source_key': str(row[2] or ''),
                    'previous_video_count': int(row[3] or 0),
                    'current_video_count': int(row[4] or 0),
                    'added_video_count': int(row[5] or 0),
                    'completed_at': str(row[6] or ''),
                }
                for row in cursor.fetchall()
            ]

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
            cursor.execute(
                '''
                UPDATE canglangge_actor_candidates
                SET binghuo_enrichment_status = ?,
                    binghuo_last_error = ?,
                    binghuo_last_enriched_at = CURRENT_TIMESTAMP,
                    binghuo_person_id = COALESCE(NULLIF(?, ''), binghuo_person_id),
                    binghuo_birthday = COALESCE(NULLIF(?, ''), binghuo_birthday),
                    binghuo_age = COALESCE(NULLIF(?, ''), binghuo_age),
                    binghuo_height = COALESCE(NULLIF(?, ''), binghuo_height),
                    binghuo_bust = COALESCE(NULLIF(?, ''), binghuo_bust),
                    binghuo_cup = COALESCE(NULLIF(?, ''), binghuo_cup),
                    binghuo_measurements_raw = COALESCE(NULLIF(?, ''), binghuo_measurements_raw),
                    binghuo_waist = COALESCE(NULLIF(?, ''), binghuo_waist),
                    binghuo_hip = COALESCE(NULLIF(?, ''), binghuo_hip),
                    updated_at = CURRENT_TIMESTAMP
                WHERE actor_name = ?
                ''',
                (
                    normalized_status,
                    normalized_error,
                    normalized_person_id,
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
            self._refresh_canglangge_completion_status(cursor, normalized_name)
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
            cursor.execute(
                '''
                UPDATE canglangge_actor_candidates
                SET baomu_enrichment_status = ?,
                    baomu_last_error = ?,
                    baomu_last_enriched_at = CURRENT_TIMESTAMP,
                    baomu_birthday = COALESCE(NULLIF(?, ''), baomu_birthday),
                    baomu_height = COALESCE(NULLIF(?, ''), baomu_height),
                    baomu_bust = COALESCE(NULLIF(?, ''), baomu_bust),
                    baomu_cup = COALESCE(NULLIF(?, ''), baomu_cup),
                    baomu_measurements_raw = COALESCE(NULLIF(?, ''), baomu_measurements_raw),
                    baomu_waist = COALESCE(NULLIF(?, ''), baomu_waist),
                    baomu_hip = COALESCE(NULLIF(?, ''), baomu_hip),
                    updated_at = CURRENT_TIMESTAMP
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
            self._refresh_canglangge_completion_status(cursor, normalized_name)
            conn.commit()
            return int(cursor.rowcount or 0)

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
            legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
            cursor.execute(
                'DELETE FROM video_actor_relation_meta WHERE actor_name = ?',
                (normalized_name,),
            )
            cursor.execute(
                'DELETE FROM video_actor_relations WHERE actor_name = ?',
                (normalized_name,),
            )
            if legacy_actor_movies:
                cursor.execute(
                    f'DELETE FROM {legacy_actor_movies} WHERE actor_name = ?',
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
                if legacy_actor_movies and legacy_values:
                    cursor.executemany(
                        f'''
                        INSERT OR REPLACE INTO {legacy_actor_movies} (
                            actor_name, code, title, author, release_date, avfan_url, page_number,
                            javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                            javtxt_release_date, author_raw, video_category,
                            supplement_enrichment_status, supplement_enrichment_error, supplement_enriched_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        legacy_values,
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

    def list_legacy_actor_movies(self, actor_name=None):
        if actor_name is None:
            return self.list_all_actor_movies()
        return self.list_actor_movies(actor_name)

    def list_legacy_code_prefix_movies(self, prefix=None):
        if prefix is None:
            return self.list_all_code_prefix_movies()
        return self.list_code_prefix_movies(prefix)

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
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.actor_name = relation.actor_name AND meta.video_code = entity.code
                WHERE relation.actor_name = ?
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
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
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       COALESCE(NULLIF(meta.avfan_url, ''), entity.avfan_url), COALESCE(meta.page_number, 1), entity.javtxt_enrichment_status, entity.javtxt_movie_id,
                       entity.javtxt_url, entity.javtxt_tags, entity.javtxt_release_date,
                       entity.javtxt_actors_raw, entity.video_category, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
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
        entity_release_date_sql = "COALESCE(NULLIF(entity.javtxt_release_date, ''), NULLIF(entity.release_date, ''), '')"
        tracked_categories = (VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_CO_STAR)
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name, MAX({entity_release_date_sql}) AS latest_release_date
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                WHERE relation.actor_name IN ({placeholders})
                  AND entity.code LIKE '%-%'
                  AND entity.video_category IN (?, ?)
                  AND {entity_release_date_sql} >= ?
                  {filter_sql}
                GROUP BY relation.actor_name
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

    def list_actor_dashboard_stats(self, actor_names, filter_settings=None):
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
        entity_release_date_sql = "COALESCE(NULLIF(entity.javtxt_release_date, ''), NULLIF(entity.release_date, ''), '')"
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT relation.actor_name,
                       COUNT(DISTINCT CASE
                           WHEN entity.video_category IN (?, ?) THEN entity.code
                       END) AS video_count,
                       MAX(CASE
                           WHEN entity.video_category IN (?, ?) THEN {entity_release_date_sql}
                       END) AS latest_release_date
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                WHERE relation.actor_name IN ({placeholders})
                  {filter_sql}
                GROUP BY relation.actor_name
                ''',
                [
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    *normalized_names,
                    *filter_params,
                ],
            )
            return {
                str(row[0] or '').strip(): {
                    'video_count': int(row[1] or 0),
                    'latest_release_date': str(row[2] or '').strip(),
                }
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }

    def list_actor_video_count_stats(self, actor_names, filter_settings=None):
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
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT relation.actor_name, COUNT(DISTINCT entity.code) AS video_count
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                WHERE relation.actor_name IN ({placeholders})
                  AND entity.video_category IN (?, ?)
                  {filter_sql}
                GROUP BY relation.actor_name
                ''',
                [
                    *normalized_names,
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    *filter_params,
                ],
            ).fetchall()
        return {
            str(row[0] or '').strip(): int(row[1] or 0)
            for row in rows
            if str(row[0] or '').strip()
        }

    def list_actor_numeric_metric_rows(self, metric_key):
        metric_expressions = {
            'age': "effective_actor_age_sql(a.age, e.binghuo_age, a.birthday, e.binghuo_birthday, e.baomu_birthday)",
            'height': "e.binghuo_height",
            'bust': "e.binghuo_bust",
            'waist': "e.binghuo_waist",
            'hip': "e.binghuo_hip",
        }
        expression = metric_expressions.get(str(metric_key or '').strip())
        if expression is None:
            raise ValueError(f'Unsupported actor numeric metric: {metric_key}')
        where_sql, parameters = self._actor_search_where_sql('')
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT a.name,
                       CASE
                           WHEN TRIM(COALESCE({expression}, '')) GLOB '[0-9]*'
                           THEN CAST(TRIM(COALESCE({expression}, '')) AS INTEGER)
                           ELSE NULL
                       END AS numeric_value
                FROM actors AS a
                LEFT JOIN actor_enrichments AS e ON e.actor_name = a.name
                {where_sql}
                ORDER BY numeric_value DESC, a.name ASC
                ''',
                parameters,
            ).fetchall()
        return [
            {
                'actor_name': str(row[0] or '').strip(),
                'numeric_value': int(row[1]),
            }
            for row in rows
            if str(row[0] or '').strip() and row[1] is not None
        ], sum(1 for row in rows if row[1] is None)

    def list_code_prefix_dashboard_stats(self, filter_settings=None):
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                WITH combined AS (
                    SELECT UPPER(relation.prefix) AS prefix,
                           entity.code,
                           COALESCE(NULLIF(entity.javtxt_release_date, ''), NULLIF(entity.release_date, ''), '') AS release_date,
                           entity.video_category, entity.title, entity.javtxt_tags
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(relation.prefix, '')) <> ''
                    UNION
                    SELECT {self._code_prefix_expression_sql('entity.code')} AS prefix,
                           entity.code,
                           COALESCE(NULLIF(entity.javtxt_release_date, ''), NULLIF(entity.release_date, ''), '') AS release_date,
                           entity.video_category, entity.title, entity.javtxt_tags
                    FROM video_actor_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(entity.code, '')) <> ''
                )
                SELECT relation.prefix,
                       COUNT(DISTINCT code) AS video_count,
                       MAX(CASE
                           WHEN video_category IN (?, ?) THEN release_date
                       END) AS latest_release_date
                FROM combined
                WHERE TRIM(COALESCE(prefix, '')) <> ''
                  AND prefix GLOB '*[A-Z]*'
                  {filter_sql}
                GROUP BY prefix
                ''',
                [
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    *filter_params,
                ],
            )
            return {
                str(row[0] or '').strip().upper(): {
                    'video_count': int(row[1] or 0),
                    'latest_release_date': str(row[2] or '').strip(),
                }
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }

    def list_code_prefix_video_count_stats(self, filter_settings=None):
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                WITH combined AS (
                    SELECT UPPER(relation.prefix) AS prefix, entity.code, entity.title, entity.javtxt_tags
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(relation.prefix, '')) <> ''
                      AND entity.video_category IN (?, ?)
                    UNION
                    SELECT {self._code_prefix_expression_sql('entity.code')} AS prefix, entity.code, entity.title, entity.javtxt_tags
                    FROM video_actor_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(entity.code, '')) <> ''
                      AND entity.video_category IN (?, ?)
                )
                SELECT prefix, COUNT(DISTINCT code) AS video_count
                FROM combined
                WHERE TRIM(COALESCE(prefix, '')) <> ''
                  AND prefix GLOB '*[A-Z]*'
                  {filter_sql}
                GROUP BY prefix
                ''',
                [
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    VIDEO_CATEGORY_SINGLE,
                    VIDEO_CATEGORY_CO_STAR,
                    *filter_params,
                ],
            ).fetchall()
        return {
            str(row[0] or '').strip().upper(): int(row[1] or 0)
            for row in rows
            if str(row[0] or '').strip()
        }

    def list_code_prefix_collection_stats(self, filter_settings=None):
        filter_sql, filter_params = self._dashboard_library_filter_sql(filter_settings)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                WITH combined AS (
                    SELECT UPPER(relation.prefix) AS prefix, entity.code, entity.video_category, entity.title, entity.javtxt_tags
                    FROM video_code_prefix_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(relation.prefix, '')) <> ''
                    UNION
                    SELECT {self._code_prefix_expression_sql('entity.code')} AS prefix, entity.code, entity.video_category, entity.title, entity.javtxt_tags
                    FROM video_actor_relations AS relation
                    JOIN video_entities AS entity ON entity.code = relation.video_code
                    WHERE TRIM(COALESCE(entity.code, '')) <> ''
                )
                SELECT prefix,
                       COUNT(DISTINCT code) AS total_count,
                       COUNT(DISTINCT CASE WHEN video_category = ? THEN code END) AS collection_count
                FROM combined
                    WHERE TRIM(COALESCE(prefix, '')) <> ''
                      AND prefix GLOB '*[A-Z]*'
                      {filter_sql}
                GROUP BY prefix
                ''',
                [VIDEO_CATEGORY_COLLECTION, *filter_params],
            ).fetchall()
        return {
            str(row[0] or '').strip().upper(): {
                'total_count': int(row[1] or 0),
                'collection_count': int(row[2] or 0),
            }
            for row in rows
            if str(row[0] or '').strip()
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

    @classmethod
    def _dashboard_library_filter_sql(cls, filter_settings=None):
        if not isinstance(filter_settings, (dict, RuleSet)):
            return '', []
        rule_set = RuleSet.normalize(filter_settings, scope='library')
        predicate, parameters = rule_set.compile_sql(
            visibility='visible',
            post_enriched_only=False,
        )
        if not predicate or predicate.strip() == '1 = 1':
            return '', []
        return f'AND ({predicate})', parameters

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

    @staticmethod
    def _append_rule_set_where(
        where_sql,
        parameters,
        rule_set=None,
        table_alias='',
        scope=None,
        visibility='visible',
    ):
        if rule_set is None:
            return where_sql, list(parameters or [])
        if not isinstance(rule_set, RuleSet):
            rule_set = RuleSet.normalize(rule_set, scope=scope or 'library')
        predicate, rule_parameters = rule_set.compile_sql(
            table_alias,
            scope=scope,
            visibility=visibility,
        )
        if not predicate or predicate.strip() == '1 = 1':
            return where_sql, list(parameters or [])
        normalized_where = str(where_sql or '').strip()
        if normalized_where:
            return f'{normalized_where} AND ({predicate})', [*(parameters or []), *rule_parameters]
        return f'WHERE {predicate}', list(rule_parameters)

    @staticmethod
    def _apply_rule_set_residual(rows, rule_set=None, scope=None, visibility='visible'):
        if rule_set is None:
            return rows
        if not isinstance(rule_set, RuleSet):
            rule_set = RuleSet.normalize(rule_set, scope=scope or 'library')
        return rule_set.apply_residual(rows, scope=scope, visibility=visibility)

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
            processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
            cursor.execute(f'''
                UPDATE {processed_write_table}
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
                    UPDATE video_entities
                    SET author = '',
                        javtxt_actors_raw = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = '',
                        javtxt_enrichment_status = ?,
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_tags = '',
                        video_category = ''
                    WHERE code IN (
                        SELECT video_code FROM video_actor_relations
                        WHERE actor_name IN ({placeholders})
                    )
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
                    UPDATE video_entities
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code IN (
                        SELECT video_code FROM video_actor_relations
                        WHERE actor_name IN ({placeholders})
                    )
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
            else:
                cursor.execute(
                    f'DELETE FROM video_actor_relation_meta WHERE actor_name IN ({placeholders})',
                    normalized_names,
                )
                cursor.execute(
                    f'DELETE FROM video_actor_relations WHERE actor_name IN ({placeholders})',
                    normalized_names,
                )
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
        if normalized_old_name != normalized_new_name and self.is_actor_blacklisted(normalized_new_name):
            raise ValueError(f'演员 {normalized_new_name} 已被加入黑名单')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM actors WHERE name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 已存在')

            cursor.execute('SELECT 1 FROM actor_enrichments WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的补全记录已存在')

            cursor.execute('SELECT 1 FROM video_actor_relations WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的作品记录已存在')

            cursor.execute('SELECT 1 FROM excluded_actor_movies WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的排除网页作品记录已存在')

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
                'UPDATE video_actor_relations SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )
            cursor.execute(
                'UPDATE video_actor_relation_meta SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )
            cursor.execute(
                'UPDATE excluded_actor_movies SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )

            for update in updates:
                code = standardize_video_code(update.get('code', ''))
                author = str(update.get('author', '')).strip()
                if not code:
                    continue
                cursor.execute(
                    f'UPDATE {processed_write_table} SET author = ? WHERE code = ?',
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
            cursor.execute(
                '''
                SELECT relation.actor_name, entity.code, entity.title, entity.author, entity.release_date,
                       meta.avfan_url, meta.page_number,
                       entity.javtxt_enrichment_status, entity.javtxt_movie_id, entity.javtxt_url, entity.javtxt_tags,
                       entity.javtxt_release_date, entity.javtxt_actors_raw, entity.video_category,
                       entity.supplement_enrichment_status, entity.supplement_enrichment_error,
                       entity.supplement_enriched_at
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.actor_name = relation.actor_name AND meta.video_code = relation.video_code
                WHERE relation.actor_name = ?
                ''',
                (normalized_name,),
            )
            excluded_movies = []
            for row in cursor.fetchall():
                excluded_movies.append(
                    {
                        'actor_name': row[0] or normalized_name,
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': row[3] or '',
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': row[6] or 1,
                        'javtxt_enrichment_status': row[7] or '',
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': row[13] or '',
                        'supplement_enrichment_status': row[14] or '',
                        'supplement_enrichment_error': row[15] or '',
                        'supplement_enriched_at': row[16] or '',
                    }
                )
            if excluded_movies:
                self._store_excluded_web_movie_rows(
                    cursor,
                    'excluded_actor_movies',
                    'actor_name',
                    normalized_name,
                    excluded_movies,
                    'actor_blacklist',
                )
            cursor.execute(
                'DELETE FROM video_actor_relation_meta WHERE actor_name = ?',
                (normalized_name,),
            )
            cursor.execute(
                'DELETE FROM video_actor_relations WHERE actor_name = ?',
                (normalized_name,),
            )
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
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                status_column, error_column, at_column = self._library_source_columns(normalized_source)
                cursor.execute(
                    f'''
                    UPDATE video_entities
                    SET author = '', javtxt_actors_raw = '',
                        supplement_enrichment_status = ?, supplement_enrichment_error = '', supplement_enriched_at = '',
                        javtxt_enrichment_status = ?, javtxt_movie_id = '', javtxt_url = '', javtxt_tags = '', video_category = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code IN (SELECT video_code FROM video_code_prefix_relations WHERE prefix IN ({placeholders}))
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
                    UPDATE video_entities
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code IN (
                        SELECT video_code FROM video_code_prefix_relations
                        WHERE prefix IN ({placeholders})
                    )
                    ''',
                    [UNENRICHED_STATUS, *normalized_prefixes],
                )
            else:
                cursor.execute(
                    f'DELETE FROM video_prefix_relation_meta WHERE prefix IN ({placeholders})',
                    normalized_prefixes,
                )
                cursor.execute(
                    f'DELETE FROM video_code_prefix_relations WHERE prefix IN ({placeholders})',
                    normalized_prefixes,
                )
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
            processed_write_table = self._processed_video_storage_target(cursor)

            if normalized_old_prefix != normalized_new_prefix:
                cursor.execute('SELECT 1 FROM code_prefix_enrichments WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在补全记录')

                cursor.execute('SELECT 1 FROM video_code_prefix_relations WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在网页作品记录')

                cursor.execute('SELECT 1 FROM excluded_code_prefix_movies WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在排除网页作品记录')

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
                    FROM {processed_write_table}
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
                    f'UPDATE {processed_write_table} SET code = ? WHERE code = ?',
                    (new_code, old_code),
                )

            for old_code, new_code in normalized_web_movie_updates:
                cursor.execute(
                    '''
                    UPDATE video_code_prefix_relations
                    SET prefix = ?, video_code = ?
                    WHERE prefix = ? AND video_code = ?
                    ''',
                    (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                )
                cursor.execute(
                    '''
                    UPDATE video_prefix_relation_meta
                    SET prefix = ?, video_code = ?
                    WHERE prefix = ? AND video_code = ?
                    ''',
                    (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                )
                if legacy_code_prefix_movies:
                    cursor.execute(
                        f'''
                        UPDATE {legacy_code_prefix_movies}
                        SET prefix = ?, code = ?
                        WHERE prefix = ? AND code = ?
                        ''',
                        (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                    )
                cursor.execute(
                    '''
                    UPDATE excluded_code_prefix_movies
                    SET prefix = ?, code = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                )

            if not normalized_web_movie_updates:
                cursor.execute(
                    'UPDATE video_code_prefix_relations SET prefix = ? WHERE prefix = ?',
                    (normalized_new_prefix, normalized_old_prefix),
                )
                cursor.execute(
                    'UPDATE video_prefix_relation_meta SET prefix = ? WHERE prefix = ?',
                    (normalized_new_prefix, normalized_old_prefix),
                )
                if legacy_code_prefix_movies:
                    cursor.execute(
                        f'UPDATE {legacy_code_prefix_movies} SET prefix = ? WHERE prefix = ?',
                        (normalized_new_prefix, normalized_old_prefix),
                    )
                cursor.execute(
                    'UPDATE excluded_code_prefix_movies SET prefix = ? WHERE prefix = ?',
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

        self.blacklist_code_prefixes([normalized_prefix])
        return 1

    def blacklist_code_prefixes(self, prefixes):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if normalized_prefix and normalized_prefix not in seen:
                seen.add(normalized_prefix)
                normalized_prefixes.append(normalized_prefix)
        if not normalized_prefixes:
            return {'blacklisted_count': 0, 'candidate_removed_count': 0}

        with self._connect() as conn:
            cursor = conn.cursor()
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            cursor.executemany(
                'INSERT OR IGNORE INTO hidden_code_prefixes (prefix) VALUES (?)',
                [(prefix,) for prefix in normalized_prefixes],
            )
            placeholders = ','.join('?' for _ in normalized_prefixes)
            cursor.execute(
                f'DELETE FROM candidate_code_prefix_records WHERE prefix IN ({placeholders})',
                normalized_prefixes,
            )
            candidate_removed_count = int(cursor.rowcount or 0)
            cursor.execute(
                f'''
                SELECT relation.prefix, entity.code, entity.title, entity.author, entity.release_date,
                       meta.avfan_url, meta.page_number,
                       entity.javtxt_enrichment_status, entity.javtxt_movie_id, entity.javtxt_url, entity.javtxt_tags,
                       entity.javtxt_release_date, entity.javtxt_actors_raw, entity.video_category,
                       entity.supplement_enrichment_status, entity.supplement_enrichment_error,
                       entity.supplement_enriched_at
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.prefix = relation.prefix AND meta.video_code = relation.video_code
                WHERE relation.prefix IN ({placeholders})
                ''',
                normalized_prefixes,
            )
            excluded_by_prefix = {prefix: [] for prefix in normalized_prefixes}
            for row in cursor.fetchall():
                excluded_by_prefix.setdefault(row[0] or '', []).append(
                    {
                        'prefix': row[0] or '',
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': row[3] or '',
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': row[6] or 1,
                        'javtxt_enrichment_status': row[7] or '',
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': row[13] or '',
                        'supplement_enrichment_status': row[14] or '',
                        'supplement_enrichment_error': row[15] or '',
                        'supplement_enriched_at': row[16] or '',
                    }
                )
            for prefix, movies in excluded_by_prefix.items():
                if movies:
                    self._store_excluded_web_movie_rows(
                        cursor,
                        'excluded_code_prefix_movies',
                        'prefix',
                        prefix,
                        movies,
                        'code_blacklist',
                    )
            cursor.execute(
                f'DELETE FROM video_prefix_relation_meta WHERE prefix IN ({placeholders})',
                normalized_prefixes,
            )
            cursor.execute(
                f'DELETE FROM video_code_prefix_relations WHERE prefix IN ({placeholders})',
                normalized_prefixes,
            )
            if legacy_code_prefix_movies:
                cursor.execute(
                    f'DELETE FROM {legacy_code_prefix_movies} WHERE prefix IN ({placeholders})',
                    normalized_prefixes,
                )
            cursor.execute(
                f'DELETE FROM code_prefix_enrichments WHERE prefix IN ({placeholders})',
                normalized_prefixes,
            )
            conn.commit()
        return {
            'blacklisted_count': len(normalized_prefixes),
            'candidate_removed_count': candidate_removed_count,
        }

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
    def _local_video_where_sql(where_sql=''):
        local_clause = "COALESCE(p.storage_location, '') <> ''"
        normalized_where = str(where_sql or '').strip()
        if not normalized_where:
            return f'WHERE {local_clause}'
        if normalized_where[:5].upper() != 'WHERE':
            raise ValueError('Video filters must start with WHERE')
        return f'WHERE {local_clause} AND ({normalized_where[5:].strip()})'

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
        rule_set=None,
    ):
        if refresh_categories:
            self.refresh_video_categories_from_filter_rules()
        where_sql, parameters = self._append_rule_set_where(
            where_sql,
            parameters,
            rule_set=rule_set,
            table_alias='p',
        )
        where_sql = self._local_video_where_sql(where_sql)
        parameters = tuple(parameters or ())
        normalized_limit, normalized_offset = self._normalize_limit_offset(limit, offset)
        limit_sql = ''
        query_parameters = list(parameters)
        if normalized_limit is not None:
            limit_sql = ' LIMIT ? OFFSET ?'
            query_parameters.extend([normalized_limit, normalized_offset])
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_read_sql = self._processed_video_read_sql(cursor)
            cursor.execute(
                f'''
                SELECT code, title, author, duration, size, storage_location,
                       avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_tags,
                       video_category, release_date, maker, publisher,
                       avfan_enrichment_status, javtxt_enrichment_status
                FROM ({processed_read_sql}) AS p
                {where_sql}
                ORDER BY {order_by_sql}
                {limit_sql}
                ''',
                tuple(query_parameters),
            )
            rows = cursor.fetchall()
        return [self._build_processed_video_row(row) for row in rows]

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

    def list_videos_for_enrichment(
        self,
        limit,
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        candidate_filter=None,
        rule_set=None,
    ):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_read_table = self._processed_video_storage_target(cursor)
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                pending_rows = []
                sql_rows = self.list_sql_javtxt_video_candidates(
                    max(int(limit) * 20, int(limit)),
                    rule_set=rule_set,
                )
                for record in sql_rows:
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
                where_sql = f'WHERE COALESCE(p.{status_column}, ?) IN (?, ?)'
                sql_params = [
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    FAILED_STATUS,
                ]
                where_sql, sql_params = self._append_rule_set_where(
                    where_sql,
                    sql_params,
                    rule_set=rule_set,
                    table_alias='p',
                    scope='pre_enrichment',
                )
                if candidate_filter is None:
                    sql_params.append(int(limit))
                    sql_limit = 'LIMIT ?'
                else:
                    sql_limit = ''
                cursor.execute(
                    f'''
                    SELECT code, title, author
                    FROM {processed_read_table} AS p
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

    _ENRICHMENT_BATCH_ITEM_TABLES = {
        'video': 'video_enrichment_batch_items',
        'code_prefix': 'code_prefix_enrichment_batch_items',
        'actor': 'actor_enrichment_batch_items',
        'actor_birthday': 'actor_birthday_enrichment_batch_items',
    }
    _ENRICHMENT_PENDING_SOURCE_TABLES = {
        ('video', JAVTXT_VIDEO_SOURCE): 'pending_video_javtxt',
        ('video', AVFAN_VIDEO_SOURCE): 'pending_video_avfan',
        ('video', SUPPLEMENT_TASK_SOURCE): 'pending_video_avfan',
        ('code_prefix', AVFAN_VIDEO_SOURCE): 'pending_code_prefix_avfan',
        ('code_prefix', JAVTXT_VIDEO_SOURCE): 'pending_code_prefix_javtxt',
        ('code_prefix', SUPPLEMENT_TASK_SOURCE): 'pending_code_prefix_supplement',
        ('actor', AVFAN_VIDEO_SOURCE): 'pending_actor_avfan',
        ('actor', JAVTXT_VIDEO_SOURCE): 'pending_actor_javtxt',
        ('actor', SUPPLEMENT_TASK_SOURCE): 'pending_actor_supplement',
        ('actor_birthday', BINGHUO_ACTOR_SOURCE): 'pending_actor_binghuo',
        ('actor_birthday', BAOMU_ACTOR_SOURCE): 'pending_actor_baomu',
    }
    _ENRICHMENT_ITEM_MAX_ATTEMPTS = 5

    def _ensure_enrichment_batch_plan_tables(self, cursor):
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS enrichment_batch_plans (
                plan_id TEXT PRIMARY KEY,
                task_kind TEXT NOT NULL,
                target_type TEXT NOT NULL,
                source_key TEXT NOT NULL,
                combo_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                batch_limit INTEGER NOT NULL,
                batch_count_limit INTEGER NOT NULL,
                completed_batch_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                completed_at TEXT,
                last_error TEXT NOT NULL DEFAULT '',
                paused_reason TEXT NOT NULL DEFAULT '',
                item_table TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_started_at TEXT,
                show_browser INTEGER NOT NULL DEFAULT 0,
                last_run_id TEXT NOT NULL DEFAULT '',
                last_run_started_at TEXT,
                last_run_completed_at TEXT,
                last_run_result TEXT NOT NULL DEFAULT '{}'
            )
            '''
        )
        self._ensure_column(cursor, 'enrichment_batch_plans', 'paused_reason', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(cursor, 'enrichment_batch_plans', 'item_table', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(
            cursor,
            'enrichment_batch_plans',
            'completed_item_count',
            'INTEGER NOT NULL DEFAULT 0',
        )
        self._ensure_column(cursor, 'enrichment_batch_plans', 'updated_at', 'TEXT')
        self._ensure_column(cursor, 'enrichment_batch_plans', 'last_started_at', 'TEXT')
        self._ensure_column(cursor, 'enrichment_batch_plans', 'show_browser', 'INTEGER NOT NULL DEFAULT 0')
        self._ensure_column(cursor, 'enrichment_batch_plans', 'last_run_id', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(cursor, 'enrichment_batch_plans', 'last_run_started_at', 'TEXT')
        self._ensure_column(cursor, 'enrichment_batch_plans', 'last_run_completed_at', 'TEXT')
        self._ensure_column(cursor, 'enrichment_batch_plans', 'last_run_result', "TEXT NOT NULL DEFAULT '{}'")
        item_tables = set(self._ENRICHMENT_BATCH_ITEM_TABLES.values()) | set(
            self._ENRICHMENT_PENDING_SOURCE_TABLES.values()
        )
        for table_name in item_tables:
            cursor.execute(
                f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    plan_id TEXT NOT NULL,
                    sequence_index INTEGER NOT NULL,
                    target_key TEXT NOT NULL,
                    code TEXT NOT NULL DEFAULT '',
                    prefix TEXT NOT NULL DEFAULT '',
                    actor_name TEXT NOT NULL DEFAULT '',
                    source_key TEXT NOT NULL DEFAULT '',
                    supplement_mode TEXT NOT NULL DEFAULT '',
                    avfan_url TEXT NOT NULL DEFAULT '',
                    avfan_movie_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    completed_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (plan_id, sequence_index)
                )
                '''
            )
            self._ensure_column(cursor, table_name, 'attempt_count', 'INTEGER NOT NULL DEFAULT 0')
            self._ensure_column(cursor, table_name, 'claimed_at', 'TEXT')
            self._ensure_column(cursor, table_name, 'updated_at', 'TEXT')
            self._ensure_column(cursor, table_name, 'supplement_mode', "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(cursor, table_name, 'avfan_url', "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(cursor, table_name, 'avfan_movie_id', "TEXT NOT NULL DEFAULT ''")
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS idx_{table_name}_plan_status '
                f'ON {table_name} (plan_id, status, sequence_index)'
            )
            if 'video' in table_name:
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS idx_{table_name}_candidate_key '
                    f'ON {table_name} (code, status)'
                )
            elif 'actor' in table_name:
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS idx_{table_name}_candidate_key '
                    f'ON {table_name} (actor_name, code, status)'
                )
            elif 'code_prefix' in table_name:
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS idx_{table_name}_candidate_key '
                    f'ON {table_name} (prefix, code, status)'
                )
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS enrichment_running_items (
                plan_id TEXT NOT NULL,
                sequence_index INTEGER NOT NULL,
                task_kind TEXT NOT NULL,
                origin_table TEXT NOT NULL,
                target_key TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                prefix TEXT NOT NULL DEFAULT '',
                actor_name TEXT NOT NULL DEFAULT '',
                source_key TEXT NOT NULL DEFAULT '',
                supplement_mode TEXT NOT NULL DEFAULT '',
                avfan_url TEXT NOT NULL DEFAULT '',
                avfan_movie_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                last_error TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                completed_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (plan_id, sequence_index)
            )
            '''
        )
        self._ensure_column(cursor, 'enrichment_running_items', 'avfan_url', "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(cursor, 'enrichment_running_items', 'avfan_movie_id', "TEXT NOT NULL DEFAULT ''")
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_enrichment_running_plan '
            'ON enrichment_running_items (plan_id, sequence_index)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_enrichment_running_candidate_key '
            'ON enrichment_running_items (task_kind, origin_table, actor_name, prefix, code, status)'
        )

    @classmethod
    def _enrichment_batch_item_table(cls, task_kind):
        normalized_kind = str(task_kind or '').strip()
        table_name = cls._ENRICHMENT_BATCH_ITEM_TABLES.get(normalized_kind)
        if not table_name:
            raise ValueError(f'未知补全批次任务类型: {task_kind}')
        return table_name

    @classmethod
    def _enrichment_pending_source_table(cls, task_kind, source_key):
        normalized_kind = str(task_kind or '').strip()
        normalized_source = str(source_key or '').strip()
        table_name = cls._ENRICHMENT_PENDING_SOURCE_TABLES.get((normalized_kind, normalized_source))
        if table_name:
            return table_name
        raise ValueError(f'不支持的补全任务来源组合: {normalized_kind}/{normalized_source}')

    def _enrichment_plan_item_table(self, plan_id, task_kind):
        normalized_plan_id = str(plan_id or '').strip()
        if normalized_plan_id:
            with self._connect() as conn:
                row = conn.execute(
                    'SELECT item_table, source_key FROM enrichment_batch_plans WHERE plan_id = ?',
                    (normalized_plan_id,),
                ).fetchone()
            if row is not None:
                stored_table = str(row[0] or '').strip()
                if stored_table in (
                    set(self._ENRICHMENT_BATCH_ITEM_TABLES.values())
                    | set(self._ENRICHMENT_PENDING_SOURCE_TABLES.values())
                ):
                    return stored_table
                legacy_table = self._enrichment_batch_item_table(task_kind)
                with self._connect() as conn:
                    legacy_row = conn.execute(
                        f'SELECT 1 FROM {legacy_table} WHERE plan_id = ? LIMIT 1',
                        (normalized_plan_id,),
                    ).fetchone()
                if legacy_row is not None:
                    return legacy_table
                return self._enrichment_pending_source_table(task_kind, row[1])
        return self._enrichment_batch_item_table(task_kind)

    @staticmethod
    def _build_enrichment_batch_item(candidate, source_key):
        row = dict(candidate or {})
        code = standardize_video_code(row.get('code', ''))
        prefix = str(row.get('prefix', '') or '').strip().upper()
        actor_name = str(row.get('actor_name', '') or row.get('name', '') or '').strip()
        target_key = str(row.get('target_key', '') or '').strip()
        if not target_key:
            target_key = code or prefix or actor_name
        normalized_source = str(row.get('source_key', '') or source_key or '').strip()
        is_supplement = normalized_source == SUPPLEMENT_TASK_SOURCE
        return {
            'target_key': target_key,
            'code': code,
            'prefix': prefix,
            'actor_name': actor_name,
            'source_key': normalized_source,
            'supplement_mode': str(row.get('supplement_mode', '') or '').strip(),
            'avfan_url': str(row.get('avfan_url', '') or '').strip() if is_supplement else '',
            'avfan_movie_id': str(row.get('avfan_movie_id', '') or '').strip() if is_supplement else '',
        }

    def create_enrichment_batch_plan(
        self,
        task_kind,
        target_type,
        source_key,
        batch_limit,
        batch_count_limit,
        combo_key='',
        candidates=None,
        initial_status='running',
        show_browser=False,
    ):
        table_name = self._enrichment_pending_source_table(task_kind, source_key)
        normalized_batch_limit = max(1, int(batch_limit or 1))
        normalized_batch_count = max(1, int(batch_count_limit or 1))
        max_items = normalized_batch_limit * normalized_batch_count
        normalized_initial_status = str(initial_status or 'running').strip()
        if normalized_initial_status not in {'running', 'selected'}:
            raise ValueError(f'非法补全计划初始状态: {initial_status}')
        plan_id = uuid.uuid4().hex
        item_rows = [
            self._build_enrichment_batch_item(candidate, source_key)
            for candidate in list(candidates or [])[:max_items]
        ]

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO enrichment_batch_plans (
                    plan_id, task_kind, target_type, source_key, combo_key, item_table,
                    status, batch_limit, batch_count_limit, started_at, show_browser
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                ''',
                (
                    plan_id,
                    str(task_kind or '').strip(),
                    str(target_type or '').strip(),
                    str(source_key or '').strip(),
                    str(combo_key or '').strip(),
                    table_name,
                    normalized_initial_status,
                    normalized_batch_limit,
                    normalized_batch_count,
                    1 if show_browser else 0,
                ),
            )
            cursor.executemany(
                f'''
                INSERT INTO {table_name} (
                    plan_id, sequence_index, target_key, code, prefix, actor_name, source_key,
                    supplement_mode, avfan_url, avfan_movie_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        plan_id,
                        index,
                        row['target_key'],
                        row['code'],
                        row['prefix'],
                        row['actor_name'],
                        row['source_key'],
                        row['supplement_mode'],
                        row['avfan_url'],
                        row['avfan_movie_id'],
                    )
                    for index, row in enumerate(item_rows, start=1)
                ],
            )
            if not item_rows:
                cursor.execute(
                    '''
                    UPDATE enrichment_batch_plans
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE plan_id = ?
                    ''',
                    (plan_id,),
                )
            conn.commit()

        return {
            'plan_id': plan_id,
            'task_kind': str(task_kind or '').strip(),
            'target_type': str(target_type or '').strip(),
            'source_key': str(source_key or '').strip(),
            'batch_limit': normalized_batch_limit,
            'batch_count_limit': normalized_batch_count,
            'item_count': len(item_rows),
            'item_table': table_name,
            'show_browser': bool(show_browser),
        }

    def append_enrichment_batch_plan_candidates(self, plan_id, task_kind, candidates):
        """Append one selection page to an existing plan without loading all pages in memory."""
        normalized_plan_id = str(plan_id or '').strip()
        normalized_task_kind = str(task_kind or '').strip()
        if not normalized_plan_id or not normalized_task_kind:
            return 0
        table_name = self._enrichment_plan_item_table(normalized_plan_id, normalized_task_kind)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            plan_row = cursor.execute(
                '''
                SELECT status, source_key, batch_limit, batch_count_limit
                FROM enrichment_batch_plans
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_plan_id, normalized_task_kind),
            ).fetchone()
            if plan_row is None or str(plan_row[0] or '').strip() in {'cancelled', 'completed'}:
                conn.commit()
                return 0
            source_key = str(plan_row[1] or '').strip()
            max_items = max(0, int(plan_row[2] or 0) * int(plan_row[3] or 0))
            current_count = int(cursor.execute(
                f'SELECT COUNT(*) FROM {table_name} WHERE plan_id = ?',
                (normalized_plan_id,),
            ).fetchone()[0] or 0)
            current_count += int(cursor.execute(
                '''
                SELECT COUNT(*)
                FROM enrichment_running_items
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_plan_id, normalized_task_kind),
            ).fetchone()[0] or 0)
            remaining = max(0, max_items - current_count)
            item_rows = [
                self._build_enrichment_batch_item(candidate, source_key)
                for candidate in list(candidates or [])[:remaining]
            ]
            if not item_rows:
                conn.commit()
                return 0
            next_sequence = int(cursor.execute(
                f'SELECT COALESCE(MAX(sequence_index), 0) FROM {table_name} WHERE plan_id = ?',
                (normalized_plan_id,),
            ).fetchone()[0] or 0) + 1
            cursor.executemany(
                f'''
                INSERT OR IGNORE INTO {table_name} (
                    plan_id, sequence_index, target_key, code, prefix, actor_name, source_key,
                    supplement_mode, avfan_url, avfan_movie_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        normalized_plan_id,
                        next_sequence + index,
                        row['target_key'],
                        row['code'],
                        row['prefix'],
                        row['actor_name'],
                        row['source_key'],
                        row['supplement_mode'],
                        row['avfan_url'],
                        row['avfan_movie_id'],
                    )
                    for index, row in enumerate(item_rows)
                ],
            )
            added_count = int(cursor.rowcount or 0)
            conn.commit()
            return added_count

    def list_enrichment_batch_items(self, plan_id, task_kind, status='pending', limit=None):
        table_name = self._enrichment_plan_item_table(plan_id, task_kind)
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return []
        normalized_limit = None if limit is None else max(0, int(limit or 0))
        normalized_status = None if status is None else str(status or '').strip()
        rows = []
        with self._connect() as conn:
            cursor = conn.cursor()
            source_params = [normalized_plan_id]
            source_status_sql = ''
            if normalized_status is not None:
                source_status_sql = ' AND status = ?'
                source_params.append(normalized_status)
            cursor.execute(
                f'''
                SELECT plan_id, sequence_index, target_key, code, prefix, actor_name,
                       source_key, supplement_mode, avfan_url, avfan_movie_id, status, last_error, started_at,
                       completed_at, attempt_count, claimed_at, updated_at
                FROM {table_name}
                WHERE plan_id = ?{source_status_sql}
                ''',
                source_params,
            )
            rows.extend((row, table_name, str(task_kind or '').strip()) for row in cursor.fetchall())
            if normalized_status is None or normalized_status == 'running':
                cursor.execute(
                    '''
                    SELECT plan_id, sequence_index, target_key, code, prefix, actor_name,
                           source_key, supplement_mode, avfan_url, avfan_movie_id, status, last_error, started_at,
                           completed_at, attempt_count, claimed_at, updated_at,
                           origin_table, task_kind
                    FROM enrichment_running_items
                    WHERE plan_id = ? AND task_kind = ?
                    ''',
                    (normalized_plan_id, str(task_kind or '').strip()),
                )
            rows.extend((row[:17], row[17], row[18]) for row in cursor.fetchall())
        items = [
            {
                'plan_id': row[0],
                'sequence_index': row[1],
                'target_key': row[2],
                'code': row[3],
                'prefix': row[4],
                'actor_name': row[5],
                'source_key': row[6],
                'supplement_mode': row[7] or '',
                'avfan_url': row[8] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                'avfan_movie_id': row[9] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                'status': row[10],
                'last_error': row[11],
                'started_at': row[12],
                'completed_at': row[13],
                'attempt_count': int(row[14] or 0),
                'claimed_at': row[15] or '',
                'updated_at': row[16] or '',
                'origin_table': origin_table,
                'task_kind': row_task_kind,
            }
            for row, origin_table, row_task_kind in rows
        ]
        items.sort(key=lambda item: int(item.get('sequence_index', 0) or 0))
        return items if normalized_limit is None else items[:normalized_limit]

    def claim_enrichment_batch_items(self, plan_id, task_kind, batch_limit):
        table_name = self._enrichment_plan_item_table(plan_id, task_kind)
        normalized_plan_id = str(plan_id or '').strip()
        normalized_limit = max(0, int(batch_limit or 0))
        if not normalized_plan_id or normalized_limit <= 0:
            return []

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                'SELECT DISTINCT plan_id, task_kind FROM enrichment_running_items LIMIT 2'
            )
            active_tasks = cursor.fetchall()
            if active_tasks:
                if active_tasks == [(normalized_plan_id, str(task_kind or '').strip())]:
                    cursor.execute(
                        '''
                        SELECT plan_id, sequence_index, task_kind, origin_table, target_key,
                               code, prefix, actor_name, source_key, supplement_mode, avfan_url,
                               avfan_movie_id, status,
                               last_error, started_at, completed_at, attempt_count, claimed_at,
                               updated_at
                        FROM enrichment_running_items
                        WHERE plan_id = ? AND task_kind = ?
                        ORDER BY sequence_index ASC
                        ''',
                        (
                            normalized_plan_id,
                            str(task_kind or '').strip(),
                        ),
                    )
                    existing_rows = cursor.fetchall()
                    conn.commit()
                    return [
                        {
                            'plan_id': row[0],
                            'sequence_index': row[1],
                            'task_kind': row[2],
                            'origin_table': row[3],
                            'target_key': row[4],
                            'code': row[5],
                            'prefix': row[6],
                            'actor_name': row[7],
                            'source_key': row[8],
                            'supplement_mode': row[9] or '',
                            'avfan_url': row[10] or '' if row[8] == SUPPLEMENT_TASK_SOURCE else '',
                            'avfan_movie_id': row[11] or '' if row[8] == SUPPLEMENT_TASK_SOURCE else '',
                            'status': row[12],
                            'last_error': row[13] or '',
                            'started_at': row[14] or '',
                            'completed_at': row[15] or '',
                            'attempt_count': int(row[16] or 0),
                            'claimed_at': row[17] or '',
                            'updated_at': row[18] or '',
                        }
                        for row in existing_rows
                    ]
                conn.rollback()
                raise RuntimeError('当前已有补全任务正在执行')
            cursor.execute(
                '''
                SELECT status, batch_limit, batch_count_limit, completed_batch_count, source_key
                FROM enrichment_batch_plans
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_plan_id, str(task_kind or '').strip()),
            )
            plan_row = cursor.fetchone()
            if plan_row is None:
                conn.commit()
                return []
            if str(plan_row[0] or '').strip() == 'cancelled':
                conn.commit()
                return []
            normalized_limit = min(normalized_limit, max(0, int(plan_row[1] or 0)))
            if normalized_limit <= 0:
                conn.commit()
                return []
            mode_filter = ''
            mode_params = []
            if str(plan_row[4] or '').strip() == SUPPLEMENT_TASK_SOURCE:
                mode_row = cursor.execute(
                    f'''
                    SELECT supplement_mode
                    FROM {table_name}
                    WHERE plan_id = ?
                      AND (status = 'pending' OR (status = 'failed' AND attempt_count < ?))
                    ORDER BY CASE supplement_mode
                               WHEN 'actors_only' THEN 0
                               WHEN 'full' THEN 1
                               ELSE 2
                             END,
                             sequence_index ASC
                    LIMIT 1
                    ''',
                    (normalized_plan_id, self._ENRICHMENT_ITEM_MAX_ATTEMPTS),
                ).fetchone()
                if mode_row is not None:
                    mode_filter = ' AND supplement_mode = ?'
                    mode_params.append(str(mode_row[0] or '').strip())
            cursor.execute(
                f'''
                SELECT plan_id, sequence_index, target_key, code, prefix, actor_name,
                       source_key, supplement_mode, avfan_url, avfan_movie_id, status, last_error, started_at, completed_at,
                       attempt_count, claimed_at, updated_at
                FROM {table_name}
                WHERE plan_id = ?
                  AND (status = 'pending' OR (status = 'failed' AND attempt_count < ?)){mode_filter}
                ORDER BY sequence_index ASC
                LIMIT ?
                ''',
                (normalized_plan_id, self._ENRICHMENT_ITEM_MAX_ATTEMPTS, *mode_params, normalized_limit),
            )
            rows = cursor.fetchall()
            claimed = []
            for row in rows:
                cursor.execute(
                    '''
                    INSERT INTO enrichment_running_items (
                        plan_id, sequence_index, task_kind, origin_table, target_key,
                        code, prefix, actor_name, source_key, supplement_mode, status,
                        avfan_url, avfan_movie_id,
                        last_error, started_at, completed_at, attempt_count, claimed_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, CURRENT_TIMESTAMP,
                            NULL, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ''',
                    (
                        row[0], int(row[1]), str(task_kind or '').strip(), table_name,
                        row[2], row[3], row[4], row[5], row[6], row[7] or '',
                        row[8] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                        row[9] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '', row[11] or '',
                        int(row[14] or 0) + 1,
                    ),
                )
                cursor.execute(
                    f'''
                    DELETE FROM {table_name}
                    WHERE plan_id = ? AND sequence_index = ?
                      AND (status = 'pending' OR (status = 'failed' AND attempt_count < ?))
                    ''',
                    (normalized_plan_id, int(row[1]), self._ENRICHMENT_ITEM_MAX_ATTEMPTS),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError('领取待补全任务时原队列记录发生变化')
                claimed.append({
                    'plan_id': row[0],
                    'sequence_index': row[1],
                    'task_kind': str(task_kind or '').strip(),
                    'origin_table': table_name,
                    'target_key': row[2],
                    'code': row[3],
                    'prefix': row[4],
                    'actor_name': row[5],
                    'source_key': row[6],
                    'supplement_mode': row[7] or '',
                    'avfan_url': row[8] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                    'avfan_movie_id': row[9] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                    'status': 'running',
                    'last_error': row[11] or '',
                    'started_at': datetime.now().isoformat(timespec='seconds'),
                    'completed_at': '',
                    'attempt_count': int(row[14] or 0) + 1,
                    'claimed_at': datetime.now().isoformat(timespec='seconds'),
                    'updated_at': datetime.now().isoformat(timespec='seconds'),
                })
            if claimed:
                cursor.execute(
                    '''
                    UPDATE enrichment_batch_plans
                    SET status = 'running',
                        paused_reason = '',
                        last_started_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE plan_id = ?
                    ''',
                    (normalized_plan_id,),
                )
            conn.commit()
            return claimed

    def _restore_running_enrichment_batch_items(self, cursor, plan_id, task_kind, error=''):
        normalized_plan_id = str(plan_id or '').strip()
        normalized_task_kind = str(task_kind or '').strip()
        cursor.execute(
            '''
            SELECT sequence_index, origin_table, target_key, code, prefix, actor_name,
                   source_key, supplement_mode, avfan_url, avfan_movie_id, started_at, attempt_count
            FROM enrichment_running_items
            WHERE plan_id = ? AND task_kind = ?
            ORDER BY sequence_index ASC
            ''',
            (normalized_plan_id, normalized_task_kind),
        )
        rows = cursor.fetchall()
        allowed_tables = set(self._ENRICHMENT_BATCH_ITEM_TABLES.values()) | set(
            self._ENRICHMENT_PENDING_SOURCE_TABLES.values()
        )
        for row in rows:
            origin_table = str(row[1] or '').strip()
            if origin_table not in allowed_tables:
                raise ValueError(f'非法补全任务来源表: {origin_table}')
            cursor.execute(
                f'''
                INSERT INTO {origin_table} (
                    plan_id, sequence_index, target_key, code, prefix, actor_name,
                    source_key, supplement_mode, status, last_error, started_at,
                    avfan_url, avfan_movie_id, completed_at, attempt_count, claimed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, NULL, ?, NULL,
                        CURRENT_TIMESTAMP)
                ON CONFLICT(plan_id, sequence_index) DO UPDATE SET
                    target_key = excluded.target_key,
                    code = excluded.code,
                    prefix = excluded.prefix,
                    actor_name = excluded.actor_name,
                    source_key = excluded.source_key,
                    supplement_mode = excluded.supplement_mode,
                    avfan_url = excluded.avfan_url,
                    avfan_movie_id = excluded.avfan_movie_id,
                    status = excluded.status,
                    last_error = excluded.last_error,
                    started_at = excluded.started_at,
                    completed_at = NULL,
                    attempt_count = excluded.attempt_count,
                    claimed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (
                    normalized_plan_id, int(row[0]), row[2], row[3], row[4], row[5],
                    row[6], row[7] or '', str(error or '').strip(), row[10],
                    row[8] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                    row[9] or '' if row[6] == SUPPLEMENT_TASK_SOURCE else '',
                    int(row[11] or 0),
                ),
            )
        cursor.execute(
            '''
            DELETE FROM enrichment_running_items
            WHERE plan_id = ? AND task_kind = ?
            ''',
            (normalized_plan_id, normalized_task_kind),
        )
        return int(cursor.rowcount or 0)

    def release_enrichment_batch_items(self, plan_id, task_kind, error=''):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            count = self._restore_running_enrichment_batch_items(
                cursor, normalized_plan_id, task_kind, error=error
            )
            conn.commit()
            return count

    def pause_enrichment_batch_plan(self, plan_id, task_kind, reason='补全任务异常暂停'):
        normalized_plan_id = str(plan_id or '').strip()
        normalized_task_kind = str(task_kind or '').strip()
        if not normalized_plan_id or not normalized_task_kind:
            return 0
        normalized_reason = str(reason or '').strip() or '补全任务异常暂停'
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            restored_count = self._restore_running_enrichment_batch_items(
                cursor,
                normalized_plan_id,
                normalized_task_kind,
                error=normalized_reason,
            )
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET status = 'paused',
                    paused_reason = ?,
                    last_error = ?,
                    completed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_reason, normalized_reason, normalized_plan_id, normalized_task_kind),
            )
            conn.commit()
            return restored_count

    def cancel_enrichment_batch_plan(self, plan_id, task_kind, reason='用户删除任务'):
        normalized_plan_id = str(plan_id or '').strip()
        normalized_task_kind = str(task_kind or '').strip()
        if not normalized_plan_id or not normalized_task_kind:
            return {
                'plan_id': normalized_plan_id,
                'status': 'cancelled',
                'released_count': 0,
                'deleted_item_count': 0,
            }
        normalized_reason = str(reason or '').strip() or '用户删除任务'
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                '''
                SELECT status
                FROM enrichment_batch_plans
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_plan_id, normalized_task_kind),
            )
            plan_row = cursor.fetchone()
            if plan_row is None:
                conn.commit()
                return {
                    'plan_id': normalized_plan_id,
                    'status': 'cancelled',
                    'released_count': 0,
                    'deleted_item_count': 0,
                }
            released_count = self._restore_running_enrichment_batch_items(
                cursor,
                normalized_plan_id,
                normalized_task_kind,
                error=normalized_reason,
            )
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET status = 'cancelled',
                    last_error = ?,
                    paused_reason = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_reason, normalized_reason, normalized_plan_id, normalized_task_kind),
            )
            conn.commit()
        return {
            'plan_id': normalized_plan_id,
            'status': 'cancelled',
            'released_count': released_count,
            'deleted_item_count': 0,
            'source_item_count': 0,
        }

    def get_enrichment_batch_plan_progress(self, plan_id, task_kind):
        table_name = self._enrichment_plan_item_table(plan_id, task_kind)
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return {}
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN')
            cursor.execute(
                '''
                SELECT plan_id, task_kind, target_type, source_key, combo_key, status,
                       batch_limit, batch_count_limit, completed_batch_count,
                       created_at, started_at, completed_at, last_error,
                       paused_reason, updated_at, last_started_at, completed_item_count, show_browser,
                       last_run_id, last_run_started_at, last_run_completed_at, last_run_result
                FROM enrichment_batch_plans
                WHERE plan_id = ?
                ''',
                (normalized_plan_id,),
            )
            plan_row = cursor.fetchone()
            if plan_row is None:
                return {}
            cursor.execute(
                f'''
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = 'failed' AND attempt_count < ? THEN 1 ELSE 0 END)
                FROM {table_name}
                WHERE plan_id = ?
                ''',
                (self._ENRICHMENT_ITEM_MAX_ATTEMPTS, normalized_plan_id),
            )
            counts = cursor.fetchone()
            cursor.execute(
                '''
                SELECT COUNT(*)
                FROM enrichment_running_items
                WHERE plan_id = ? AND task_kind = ?
                ''',
                (normalized_plan_id, str(task_kind or '').strip()),
            )
            executing_count = int(cursor.fetchone()[0] or 0)
        source_total, pending_count, legacy_running_count, legacy_completed_count, failed_count, retryable_failed_count = [
            int(value or 0) for value in counts
        ]
        completed_count = legacy_completed_count + int(plan_row[16] or 0)
        running_count = legacy_running_count + executing_count
        total_count = source_total + executing_count + int(plan_row[16] or 0)
        try:
            last_run_result = json.loads(plan_row[21] or '{}')
        except (TypeError, ValueError):
            last_run_result = {}
        return {
            'plan_id': plan_row[0],
            'task_kind': plan_row[1],
            'target_type': plan_row[2],
            'source_key': plan_row[3],
            'combo_key': plan_row[4],
            'status': plan_row[5],
            'current_status': plan_row[5],
            'batch_limit': int(plan_row[6] or 0),
            'batch_count_limit': int(plan_row[7] or 0),
            'completed_batch_count': int(plan_row[8] or 0),
            'created_at': plan_row[9] or '',
            'started_at': plan_row[10] or '',
            'completed_at': plan_row[11] or '',
            'last_error': plan_row[12] or '',
            'paused_reason': plan_row[13] or '',
            'updated_at': plan_row[14] or '',
            'last_started_at': plan_row[15] or '',
            'show_browser': bool(plan_row[17]),
            'last_run_id': plan_row[18] or '',
            'last_run_started_at': plan_row[19] or '',
            'last_run_completed_at': plan_row[20] or '',
            'last_run_result': last_run_result,
            'total_count': total_count,
            'pending_count': pending_count,
            'running_count': running_count,
            'completed_count': completed_count,
            'success_count': completed_count,
            'failed_count': failed_count,
            'retryable_failed_count': retryable_failed_count,
        }

    def update_enrichment_plan_progress(
        self,
        plan_id,
        task_kind,
        completed_batch=False,
        status=None,
        paused_reason='',
        last_error='',
    ):
        progress = self.get_enrichment_batch_plan_progress(plan_id, task_kind)
        if not progress:
            return {}
        if progress.get('status') == 'cancelled':
            return progress
        if status is None:
            has_unfinished = bool(
                progress['pending_count']
                or progress['running_count']
                or progress['retryable_failed_count']
            )
            status = 'running' if has_unfinished else ('failed' if progress['failed_count'] else 'completed')
        normalized_status = str(status or '').strip() or 'running'
        next_batch_count = min(
            progress['batch_count_limit'],
            progress['completed_batch_count'] + (1 if completed_batch else 0),
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET completed_batch_count = ?,
                    status = ?,
                    paused_reason = ?,
                    last_error = ?,
                    completed_at = CASE WHEN ? IN ('completed', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ?
                ''',
                (
                    next_batch_count,
                    normalized_status,
                    str(paused_reason or '').strip(),
                    str(last_error or '').strip(),
                    normalized_status,
                    str(plan_id or '').strip(),
                ),
            )
            conn.commit()
        return self.get_enrichment_batch_plan_progress(plan_id, task_kind)

    def save_enrichment_plan_run_result(self, plan_id, task_kind, result):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return {}
        payload = dict(result or {})
        run_id = str(payload.get('run_id', '') or '').strip()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str)
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE enrichment_batch_plans
                SET last_run_id = ?,
                    last_run_started_at = COALESCE(?, last_run_started_at),
                    last_run_completed_at = CURRENT_TIMESTAMP,
                    last_run_result = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ?
                ''',
                (
                    run_id,
                    str(payload.get('started_at', '') or '').strip() or None,
                    serialized,
                    normalized_plan_id,
                ),
            )
            conn.commit()
        return self.get_enrichment_batch_plan_progress(normalized_plan_id, task_kind)

    def update_enrichment_batch_plan_options(self, plan_id, show_browser=False):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return False
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET show_browser = ?, updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ?
                ''',
                (1 if show_browser else 0, normalized_plan_id),
            )
            conn.commit()
            return bool(cursor.rowcount)

    def list_enrichment_batch_plans(self, statuses=None):
        normalized_statuses = [
            str(status or '').strip() for status in (statuses or []) if str(status or '').strip()
        ]
        with self._connect() as conn:
            cursor = conn.cursor()
            sql = 'SELECT plan_id, task_kind FROM enrichment_batch_plans'
            params = []
            if normalized_statuses:
                sql += ' WHERE status IN (' + ','.join('?' for _ in normalized_statuses) + ')'
                params.extend(normalized_statuses)
            sql += ' ORDER BY created_at ASC, plan_id ASC'
            cursor.execute(sql, params)
            identities = cursor.fetchall()
        return [self.get_enrichment_batch_plan_progress(plan_id, task_kind) for plan_id, task_kind in identities]

    def find_selected_enrichment_plan(self, task_kind, target_type, source_key):
        table_name = self._enrichment_pending_source_table(task_kind, source_key)
        with self._connect() as conn:
            row = conn.execute(
                f'''
                SELECT plan_id, task_kind
                FROM enrichment_batch_plans
                WHERE status IN ('selected', 'paused')
                  AND task_kind = ?
                  AND target_type = ?
                  AND source_key = ?
                  AND EXISTS (
                      SELECT 1
                      FROM {table_name} AS pending_items
                      WHERE pending_items.plan_id = enrichment_batch_plans.plan_id
                        AND (
                            pending_items.status = 'pending'
                            OR (
                                pending_items.status = 'failed'
                                AND pending_items.attempt_count < ?
                            )
                        )
                  )
                ORDER BY CASE WHEN status = 'selected' THEN 0 ELSE 1 END,
                         created_at ASC,
                         plan_id ASC
                LIMIT 1
                ''',
                (
                    str(task_kind or '').strip(),
                    str(target_type or '').strip(),
                    str(source_key or '').strip(),
                    self._ENRICHMENT_ITEM_MAX_ATTEMPTS,
                ),
            ).fetchone()
        if row is None:
            return None
        return self.get_enrichment_batch_plan_progress(row[0], row[1])

    def get_enrichment_queue_keys(self, task_kind, source_key):
        table_name = self._enrichment_pending_source_table(task_kind, source_key)
        with self._connect() as conn:
            pending = conn.execute(
                f'''
                SELECT target_key, prefix, actor_name, code
                FROM {table_name}
                WHERE status IN ('pending', 'failed')
                ''',
            ).fetchall()
            running = conn.execute(
                '''
                SELECT target_key, prefix, actor_name, code
                FROM enrichment_running_items
                WHERE task_kind = ? AND origin_table = ?
                ''',
                (str(task_kind or '').strip(), table_name),
            ).fetchall()
        rows = pending + running
        return {
            'target_keys': {str(row[0] or '').strip() for row in rows if str(row[0] or '').strip()},
            'prefixes': {str(row[1] or '').strip().upper() for row in rows if str(row[1] or '').strip()},
            'actor_names': {str(row[2] or '').strip() for row in rows if str(row[2] or '').strip()},
            'codes': {str(row[3] or '').strip().upper() for row in rows if str(row[3] or '').strip()},
        }

    @staticmethod
    def _aggregate_supplement_statuses(statuses):
        normalized = [str(status or '').strip() for status in statuses if str(status or '').strip()]
        if not normalized:
            return UNENRICHED_STATUS
        if FAILED_STATUS in normalized:
            return FAILED_STATUS
        if NO_VIDEO_DETAIL_STATUS in normalized:
            return NO_VIDEO_DETAIL_STATUS
        if NO_SEARCH_RESULTS_STATUS in normalized:
            return NO_SEARCH_RESULTS_STATUS
        if all(status == ENRICHED_STATUS for status in normalized):
            return ENRICHED_STATUS
        return UNENRICHED_STATUS

    def get_actor_supplement_statuses(self, actor_names):
        names = [str(name or '').strip() for name in actor_names or [] if str(name or '').strip()]
        if not names:
            return {}
        placeholders = ','.join('?' for _ in names)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT relation.actor_name, entity.supplement_enrichment_status
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                WHERE relation.actor_name IN ({placeholders})
                  AND TRIM(COALESCE(entity.supplement_enrichment_status, '')) <> ''
                ''',
                names,
            ).fetchall()
        grouped = {name: [] for name in names}
        for actor_name, status in rows:
            grouped.setdefault(str(actor_name or '').strip(), []).append(status)
        return {name: self._aggregate_supplement_statuses(statuses) for name, statuses in grouped.items()}

    def get_code_prefix_supplement_statuses(self, prefixes):
        normalized = [str(prefix or '').strip().upper() for prefix in prefixes or [] if str(prefix or '').strip()]
        if not normalized:
            return {}
        placeholders = ','.join('?' for _ in normalized)
        with self._connect() as conn:
            rows = conn.execute(
                f'''
                SELECT UPPER(relation.prefix), entity.supplement_enrichment_status
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                WHERE UPPER(relation.prefix) IN ({placeholders})
                  AND TRIM(COALESCE(entity.supplement_enrichment_status, '')) <> ''
                ''',
                normalized,
            ).fetchall()
        grouped = {prefix: [] for prefix in normalized}
        for prefix, status in rows:
            grouped.setdefault(str(prefix or '').strip().upper(), []).append(status)
        return {prefix: self._aggregate_supplement_statuses(statuses) for prefix, statuses in grouped.items()}

    def list_resumable_enrichment_plans(self):
        rows = self.list_enrichment_batch_plans(statuses=['running', 'paused'])
        return [
            row for row in rows
            if row.get('pending_count', 0) or row.get('running_count', 0) or row.get('retryable_failed_count', 0)
        ]

    def has_running_enrichment_items(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM enrichment_running_items WHERE status = 'running' LIMIT 1"
            ).fetchone() is not None

    def recover_running_enrichment_plans(self, reason='程序重启恢复'):
        normalized_reason = str(reason or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            recovered_items = 0
            item_tables = set(self._ENRICHMENT_BATCH_ITEM_TABLES.values()) | set(
                self._ENRICHMENT_PENDING_SOURCE_TABLES.values()
            )
            cursor.execute(
                '''
                SELECT plan_id, sequence_index, origin_table, target_key, code, prefix,
                       actor_name, source_key, supplement_mode, avfan_url, avfan_movie_id,
                       started_at, attempt_count
                FROM enrichment_running_items
                ORDER BY plan_id ASC, sequence_index ASC
                '''
            )
            running_rows = cursor.fetchall()
            for row in running_rows:
                origin_table = str(row[2] or '').strip()
                if origin_table not in item_tables:
                    conn.rollback()
                    raise ValueError(f'非法补全任务来源表: {origin_table}')
                cursor.execute(
                    f'''
                    INSERT INTO {origin_table} (
                        plan_id, sequence_index, target_key, code, prefix, actor_name,
                        source_key, supplement_mode, status, last_error, started_at,
                        avfan_url, avfan_movie_id, completed_at, attempt_count, claimed_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, NULL, ?, NULL,
                            CURRENT_TIMESTAMP)
                    ON CONFLICT(plan_id, sequence_index) DO UPDATE SET
                        target_key = excluded.target_key,
                        code = excluded.code,
                        prefix = excluded.prefix,
                        actor_name = excluded.actor_name,
                        source_key = excluded.source_key,
                        supplement_mode = excluded.supplement_mode,
                        avfan_url = excluded.avfan_url,
                        avfan_movie_id = excluded.avfan_movie_id,
                        status = excluded.status,
                        last_error = excluded.last_error,
                        started_at = excluded.started_at,
                        completed_at = NULL,
                        attempt_count = excluded.attempt_count,
                        claimed_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        row[0], int(row[1]), row[3], row[4], row[5], row[6], row[7],
                        row[8] or '', normalized_reason, row[11],
                        row[9] or '' if row[7] == SUPPLEMENT_TASK_SOURCE else '',
                        row[10] or '' if row[7] == SUPPLEMENT_TASK_SOURCE else '',
                        int(row[12] or 0),
                    ),
                )
            cursor.execute('DELETE FROM enrichment_running_items')
            recovered_items += int(cursor.rowcount or 0)
            for table_name in item_tables:
                cursor.execute(
                    f'''
                    UPDATE {table_name}
                    SET status = 'pending',
                        claimed_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'running'
                    ''',
                )
                recovered_items += int(cursor.rowcount or 0)
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET status = 'paused',
                    paused_reason = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                ''',
                (normalized_reason,),
            )
            recovered_plans = int(cursor.rowcount or 0)
            conn.commit()
        return recovered_plans if recovered_plans else recovered_items

    def mark_enrichment_batch_item(self, plan_id, task_kind, sequence_index, status, error=''):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return 0
        normalized_task_kind = str(task_kind or '').strip()
        normalized_status = str(status or '').strip() or 'completed'
        normalized_error = str(error or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                '''
                SELECT origin_table, target_key, code, prefix, actor_name, source_key,
                       supplement_mode, avfan_url, avfan_movie_id, started_at, attempt_count
                FROM enrichment_running_items
                WHERE plan_id = ? AND sequence_index = ? AND task_kind = ?
                ''',
                (normalized_plan_id, int(sequence_index or 0), normalized_task_kind),
            )
            row = cursor.fetchone()
            if row is None:
                conn.commit()
                return 0
            origin_table = str(row[0] or '').strip()
            allowed_tables = set(self._ENRICHMENT_BATCH_ITEM_TABLES.values()) | set(
                self._ENRICHMENT_PENDING_SOURCE_TABLES.values()
            )
            if origin_table not in allowed_tables:
                conn.rollback()
                raise ValueError(f'非法补全任务来源表: {origin_table}')
            if normalized_status == 'failed':
                cursor.execute(
                    f'''
                    INSERT INTO {origin_table} (
                        plan_id, sequence_index, target_key, code, prefix, actor_name,
                        source_key, supplement_mode, status, last_error, started_at,
                        avfan_url, avfan_movie_id, completed_at, attempt_count, claimed_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, NULL,
                            CURRENT_TIMESTAMP)
                    ON CONFLICT(plan_id, sequence_index) DO UPDATE SET
                        target_key = excluded.target_key,
                        code = excluded.code,
                        prefix = excluded.prefix,
                        actor_name = excluded.actor_name,
                        source_key = excluded.source_key,
                        supplement_mode = excluded.supplement_mode,
                        avfan_url = excluded.avfan_url,
                        avfan_movie_id = excluded.avfan_movie_id,
                        status = excluded.status,
                        last_error = excluded.last_error,
                        started_at = excluded.started_at,
                        completed_at = excluded.completed_at,
                        attempt_count = excluded.attempt_count,
                        claimed_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    (
                        normalized_plan_id, int(sequence_index or 0), row[1], row[2], row[3],
                        row[4], row[5], row[6] or '', normalized_error,
                        row[7] or '' if row[5] == SUPPLEMENT_TASK_SOURCE else '',
                        row[8] or '' if row[5] == SUPPLEMENT_TASK_SOURCE else '',
                        row[9], int(row[10] or 0),
                    ),
                )
            else:
                cursor.execute(
                    '''
                    UPDATE enrichment_batch_plans
                    SET completed_item_count = completed_item_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE plan_id = ?
                    ''',
                    (normalized_plan_id,),
                )
            cursor.execute(
                '''
                DELETE FROM enrichment_running_items
                WHERE plan_id = ? AND sequence_index = ? AND task_kind = ?
                ''',
                (normalized_plan_id, int(sequence_index or 0), normalized_task_kind),
            )
            updated_count = int(cursor.rowcount or 0)
            conn.commit()
            return updated_count

    def finish_enrichment_batch_plan(self, plan_id, status='completed', error=''):
        normalized_plan_id = str(plan_id or '').strip()
        if not normalized_plan_id:
            return 0
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE enrichment_batch_plans
                SET status = ?,
                    last_error = ?,
                    paused_reason = CASE WHEN ? = 'paused' THEN ? ELSE paused_reason END,
                    completed_at = CASE WHEN ? IN ('completed', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ?
                ''',
                (
                    str(status or '').strip() or 'completed',
                    str(error or '').strip(),
                    str(status or '').strip() or 'completed',
                    str(error or '').strip(),
                    str(status or '').strip() or 'completed',
                    normalized_plan_id,
                ),
            )
            updated_count = int(cursor.rowcount or 0)
            conn.commit()
            return updated_count

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
            processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
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

    def _list_processed_video_javtxt_records(self, cursor):
        processed_read_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
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
            FROM {processed_read_table}
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
            processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
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
                    UPDATE {processed_write_table}
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
                    UPDATE {processed_write_table}
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
            processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
            cursor.execute(
                f'''
                UPDATE {processed_write_table}
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
        processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
        cursor.execute(
            f'''
            SELECT avfan_enrichment_status, javtxt_enrichment_status
            FROM {processed_write_table}
            WHERE code = ?
            ''',
            (code,),
        )
        row = cursor.fetchone() or (UNENRICHED_STATUS, UNENRICHED_STATUS)
        cursor.execute(
            f'''
            UPDATE {processed_write_table}
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
            processed_read_table = self._processed_video_storage_target(cursor)
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM {processed_read_table}
                WHERE COALESCE({status_column}, ?) = ?
                ''',
                (UNENRICHED_STATUS, status),
            )
            return int(cursor.fetchone()[0] or 0)

    def count_pending_video_enrichments(
        self,
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        candidate_filter=None,
        rule_set=None,
    ):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            processed_read_table = self._processed_video_storage_target(cursor)
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
                where_sql = f'WHERE COALESCE(p.{status_column}, ?) IN (?, ?)'
                query_parameters = [
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    FAILED_STATUS,
                ]
                where_sql, query_parameters = self._append_rule_set_where(
                    where_sql,
                    query_parameters,
                    rule_set=rule_set,
                    table_alias='p',
                    scope='pre_enrichment',
                )
                cursor.execute(
                    f'''
                    SELECT COUNT(*)
                    FROM {processed_read_table} AS p
                    {where_sql}
                    ''',
                    query_parameters,
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
                    FROM ({processed_read_sql}) AS p
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
            processed_write_table = self._processed_video_storage_target(cursor)
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE {processed_write_table}
                    SET javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_title = '',
                        javtxt_actors = '',
                        javtxt_tags = '',
                        video_category = '',
                        supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = '',
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
                    UPDATE {processed_write_table}
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
                    UPDATE {processed_write_table}
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = '',
                        supplement_enriched_at = ''
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_codes],
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE {processed_write_table}
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
                        supplement_enriched_at = '',
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
            cursor.execute('SELECT COUNT(*) FROM video_entities')
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
                SELECT e.code, e.title, e.author, COALESCE(l.duration, ''), COALESCE(l.size, ''),
                       COALESCE(l.storage_location, ''), e.release_date, e.video_category,
                       e.javtxt_tags, e.javtxt_release_date, e.javtxt_enrichment_status, e.javtxt_movie_id, e.javtxt_url,
                       e.avfan_movie_id, e.maker, e.publisher
                FROM video_entities AS e
                LEFT JOIN local_video_records AS l ON l.code = e.code
                WHERE e.code IN ({placeholders})
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
            processed_read_table = self._processed_video_storage_target(cursor)
            cursor.execute(
                f'''
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
                LEFT JOIN {processed_read_table} AS p
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
            processed_read_table = self._processed_video_storage_target(cursor)
            cursor.execute(
                f'''
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
                LEFT JOIN {processed_read_table} AS p
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
        if not str(processed_detail.get('storage_location', '') or '').strip():
            processed_detail = {}
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
            cursor.execute('DELETE FROM local_video_records WHERE code = ?', (normalized_code,))
            cursor.execute(
                '''
                INSERT INTO video_entities (
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
                    title = excluded.title,
                    author = excluded.author,
                    release_date = excluded.release_date,
                    avfan_movie_id = excluded.avfan_movie_id,
                    javtxt_movie_id = excluded.javtxt_movie_id,
                    javtxt_url = excluded.javtxt_url,
                    javtxt_title = excluded.javtxt_title,
                    javtxt_actors = excluded.javtxt_actors,
                    javtxt_actors_raw = excluded.javtxt_actors_raw,
                    javtxt_release_date = excluded.javtxt_release_date,
                    avfan_enrichment_status = excluded.avfan_enrichment_status,
                    javtxt_enrichment_status = excluded.javtxt_enrichment_status,
                    enrichment_status = excluded.enrichment_status,
                    updated_at = CURRENT_TIMESTAMP
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
        if not str(processed_detail.get('storage_location', '') or '').strip():
            processed_detail = {}

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

                UNION

                SELECT name AS actor_name
                FROM hidden_actors
                '''
            )
            rows = cursor.fetchall()
        return {str((row or [''])[0] or '').strip() for row in rows if str((row or [''])[0] or '').strip()}

    def refresh_masterpiece_actor_registry(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT actor_name
                FROM masterpiece_actors
                WHERE COALESCE(handle_mark, 0) = 2
                  AND COALESCE(actor_name, '') <> ''
                '''
            ).fetchall()
            actor_names = [str((row or [''])[0] or '').strip() for row in rows if str((row or [''])[0] or '').strip()]
            for actor_name in actor_names:
                conn.execute(
                    'INSERT OR IGNORE INTO hidden_actors (name) VALUES (?)',
                    (actor_name,),
                )
            removed_count = conn.execute(
                'DELETE FROM masterpiece_actors WHERE COALESCE(handle_mark, 0) = 2'
            ).rowcount
            conn.commit()

        pending_summary = self._sync_pending_masterpiece_actor_registrations()
        return {
            **pending_summary,
            'blacklisted_count': len(actor_names),
            'removed_count': int(removed_count or 0),
        }

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
        if processed_detail and str(processed_detail.get('storage_location', '') or '').strip():
            references.append(self._build_processed_masterpiece_reference(processed_detail))

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT relation.prefix,
                       entity.code,
                       COALESCE(entity.title, ''),
                       COALESCE(NULLIF(entity.author, ''), NULLIF(entity.javtxt_actors_raw, ''), ''),
                       COALESCE(entity.release_date, ''),
                       COALESCE(meta.avfan_url, entity.avfan_url, ''),
                       COALESCE(entity.javtxt_movie_id, ''),
                       COALESCE(entity.javtxt_url, '')
                FROM video_code_prefix_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_prefix_relation_meta AS meta
                    ON meta.video_code = relation.video_code AND meta.prefix = relation.prefix
                WHERE entity.code = ?
                ORDER BY entity.release_date DESC, relation.prefix ASC
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
                SELECT relation.actor_name,
                       entity.code,
                       COALESCE(entity.title, ''),
                       COALESCE(NULLIF(entity.author, ''), NULLIF(entity.javtxt_actors_raw, ''), ''),
                       COALESCE(entity.release_date, ''),
                       COALESCE(meta.avfan_url, entity.avfan_url, ''),
                       COALESCE(entity.javtxt_movie_id, ''),
                       COALESCE(entity.javtxt_url, '')
                FROM video_actor_relations AS relation
                JOIN video_entities AS entity ON entity.code = relation.video_code
                LEFT JOIN video_actor_relation_meta AS meta
                    ON meta.video_code = relation.video_code AND meta.actor_name = relation.actor_name
                WHERE entity.code = ?
                ORDER BY entity.release_date DESC, relation.actor_name ASC
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
        error = ''
        if status == 0 and handle_mark == 1:
            try:
                self.add_actor(normalized_name, birthday='', age='')
            except ValueError as exc:
                error = str(exc)
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

        return {
            'actor_name': normalized_name,
            'status': status,
            'handle_mark': handle_mark,
            'error': error if status == 0 else '',
        }

    def sync_pending_masterpiece_actor_registrations(self):
        return self.refresh_masterpiece_actor_registry()

    def _sync_pending_masterpiece_actor_registrations(self):
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT actor_name
                FROM masterpiece_actors
                WHERE COALESCE(status, 0) = 0
                  AND COALESCE(handle_mark, 0) = 1
                ORDER BY actor_name
                '''
            ).fetchall()

        actor_names = [str((row or [''])[0] or '').strip() for row in rows]
        results = [
            self._sync_masterpiece_actor_registration(actor_name)
            for actor_name in actor_names
            if actor_name
        ]
        failures = [
            {
                'actor_name': result.get('actor_name', ''),
                'error': result.get('error', '') or '加入演员库后仍未找到演员记录',
            }
            for result in results
            if int(result.get('status', 0) or 0) == 0
        ]
        return {
            'pending_total': len(actor_names),
            'added_count': len(results) - len(failures),
            'failed_count': len(failures),
            'failures': failures,
        }

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
                       COALESCE(medal_type, 'special'),
                       COALESCE(created_at, ''),
                       COALESCE(updated_at, '')
                FROM global_medals
                ORDER BY created_at ASC, UPPER(name) ASC
                '''
            )
            rows = cursor.fetchall()

        return sort_medal_rows([
            {
                'name': row[0] or '',
                'description': row[1] or '',
                'medal_type': normalize_medal_type(row[2]),
                'created_at': row[3] or '',
                'updated_at': row[4] or '',
            }
            for row in rows
        ])

    def add_global_medal(self, name, description='', medal_type='special'):
        normalized_name = str(name or '').strip()
        normalized_description = str(description or '').strip()
        normalized_medal_type = normalize_medal_type(medal_type)
        if not normalized_name:
            raise ValueError('缺少勋章名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM global_medals WHERE name = ?', (normalized_name,))
            if cursor.fetchone():
                raise ValueError(f'勋章已存在: {normalized_name}')
            cursor.execute(
                '''
                INSERT INTO global_medals (name, description, medal_type)
                VALUES (?, ?, ?)
                ''',
                (normalized_name, normalized_description, normalized_medal_type),
            )
            conn.commit()

        return self._get_global_medal(normalized_name)

    def update_global_medal(self, name, description='', medal_type=None):
        normalized_name = str(name or '').strip()
        normalized_description = str(description or '').strip()
        normalized_medal_type = None if medal_type is None else normalize_medal_type(medal_type)
        if not normalized_name:
            raise ValueError('缺少勋章名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE global_medals
                SET description = ?, medal_type = COALESCE(?, medal_type), updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
                ''',
                (normalized_description, normalized_medal_type, normalized_name),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f'勋章不存在: {normalized_name}')
            conn.commit()

        return self._get_global_medal(normalized_name)

    def update_global_medal_description(self, name, description=''):
        return self.update_global_medal(name, description, medal_type=None)

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
            legacy_table = self._legacy_table_name(cursor, 'processed_videos')
            if legacy_table:
                detail_from_sql = f'FROM {legacy_table}'
                detail_code_column = 'code'
            else:
                detail_from_sql = 'FROM video_entities AS e LEFT JOIN local_video_records AS l ON l.code = e.code'
                detail_code_column = 'e.code'
            cursor.execute(
                f'''
                SELECT {detail_code_column},
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
                {detail_from_sql}
                WHERE {detail_code_column} = ?
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

    def bulk_update_processed_videos_for_supplement(self, updates, status_updates=None):
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
                    str((row or {}).get('_supplement_status', '') or '').strip() or UNENRICHED_STATUS,
                    str((row or {}).get('_supplement_error', '') or '').strip(),
                    code,
                )
            )

        if not normalized_updates and not status_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            processed_write_table = self._legacy_table_name(cursor, 'processed_videos') or 'video_entities'
            cursor.executemany(
                f'''
                UPDATE {processed_write_table}
                SET title = ?,
                    author = ?,
                    javtxt_actors = ?,
                    javtxt_actors_raw = ?,
                    release_date = ?,
                    maker = ?,
                    publisher = ?,
                    avfan_movie_id = ?,
                    supplement_enrichment_status = ?,
                    supplement_enrichment_error = ?,
                    supplement_enriched_at = ''
                WHERE code = ?
                ''',
                normalized_updates,
            )
            status_rows = [
                (
                    str(status or '').strip() or UNENRICHED_STATUS,
                    str(error or '').strip(),
                    standardize_video_code((row or {}).get('code', '')),
                )
                for row, status, error in status_updates or []
                if standardize_video_code((row or {}).get('code', ''))
            ]
            if status_rows:
                cursor.executemany(
                    f'''
                    UPDATE {processed_write_table}
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?,
                        supplement_enriched_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    status_rows,
                )
            entity_rows = [
                (row[0], row[1], row[4], row[5], row[6], row[7], row[8], row[9], row[10])
                for row in normalized_updates
            ]
            if entity_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET title = ?, author = ?, release_date = ?, maker = ?, publisher = ?,
                        avfan_movie_id = ?, supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_rows,
                )
            entity_status_rows = [(row[8], row[9], row[10]) for row in normalized_updates]
            entity_status_rows.extend((status, error, code) for status, error, code in status_rows)
            if entity_status_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?,
                        supplement_enriched_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_status_rows,
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
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            cursor.executemany(
                '''
                UPDATE video_entities
                SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                    javtxt_enrichment_status = ?, javtxt_movie_id = ?, javtxt_url = ?,
                    javtxt_tags = ?, javtxt_release_date = ?, javtxt_actors_raw = ?,
                    video_category = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                [(*row[:11], row[12]) for row in normalized_updates],
            )
            cursor.executemany(
                '''
                INSERT INTO video_prefix_relation_meta (video_code, prefix, avfan_url, avfan_movie_id, page_number)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(video_code, prefix) DO UPDATE SET
                    avfan_url = excluded.avfan_url,
                    avfan_movie_id = excluded.avfan_movie_id
                ''',
                [(row[12], row[11], row[3], row[5]) for row in normalized_updates],
            )
            if legacy_code_prefix_movies:
                cursor.executemany(
                    f'''
                    UPDATE {legacy_code_prefix_movies}
                    SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                        javtxt_enrichment_status = ?, javtxt_movie_id = ?, javtxt_url = ?,
                        javtxt_tags = ?, javtxt_release_date = ?, author_raw = ?, video_category = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    normalized_updates,
                )
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def bulk_update_code_prefix_movies_for_supplement(self, updates, status_updates=None):
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
                    str((row or {}).get('_supplement_status', '') or '').strip() or UNENRICHED_STATUS,
                    str((row or {}).get('_supplement_error', '') or '').strip(),
                    prefix,
                    code,
                )
            )

        if not normalized_updates and not status_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            status_rows = [
                (
                    str(status or '').strip() or UNENRICHED_STATUS,
                    str(error or '').strip(),
                    str((row or {}).get('prefix', '') or '').strip().upper(),
                    standardize_video_code((row or {}).get('code', '')),
                )
                for row, status, error in status_updates or []
                if str((row or {}).get('prefix', '') or '').strip()
                and standardize_video_code((row or {}).get('code', ''))
            ]
            entity_rows = [
                (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[9])
                for row in normalized_updates
            ]
            if entity_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                        javtxt_actors_raw = ?, video_category = ?,
                        supplement_enrichment_status = ?, supplement_enrichment_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_rows,
                )
            entity_status_rows = [(row[6], row[7], row[9]) for row in normalized_updates]
            entity_status_rows.extend(
                (status, error, code)
                for status, error, _prefix, code in status_rows
            )
            if entity_status_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?,
                        supplement_enriched_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_status_rows,
                )
            if normalized_updates:
                cursor.executemany(
                    '''
                    INSERT INTO video_prefix_relation_meta (video_code, prefix, avfan_url, avfan_movie_id, page_number)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(video_code, prefix) DO UPDATE SET
                        avfan_url = excluded.avfan_url
                    ''',
                    [(row[9], row[8], row[3], '') for row in normalized_updates],
                )
            if legacy_code_prefix_movies:
                if normalized_updates:
                    cursor.executemany(
                        f'''
                        UPDATE {legacy_code_prefix_movies}
                        SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                            author_raw = ?, video_category = ?, supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?, supplement_enriched_at = ''
                        WHERE prefix = ? AND code = ?
                        ''',
                        normalized_updates,
                    )
                if status_rows:
                    cursor.executemany(
                        f'''
                        UPDATE {legacy_code_prefix_movies}
                        SET supplement_enrichment_status = ?, supplement_enrichment_error = ?,
                            supplement_enriched_at = CURRENT_TIMESTAMP
                        WHERE prefix = ? AND code = ?
                        ''',
                        status_rows,
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
            legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
            cursor.executemany(
                '''
                UPDATE video_entities
                SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                    javtxt_enrichment_status = ?, javtxt_movie_id = ?, javtxt_url = ?,
                    javtxt_tags = ?, javtxt_release_date = ?, javtxt_actors_raw = ?,
                    video_category = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                [(*row[:11], row[12]) for row in normalized_updates],
            )
            cursor.executemany(
                '''
                INSERT INTO video_actor_relation_meta (video_code, actor_name, avfan_url, avfan_movie_id, page_number)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(video_code, actor_name) DO UPDATE SET
                    avfan_url = excluded.avfan_url,
                    avfan_movie_id = excluded.avfan_movie_id
                ''',
                [
                    (row[12], row[11], row[3], row[5])
                    for row in normalized_updates
                ],
            )
            if legacy_actor_movies:
                cursor.executemany(
                    f'''
                    UPDATE {legacy_actor_movies}
                    SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                        javtxt_enrichment_status = ?, javtxt_movie_id = ?, javtxt_url = ?,
                        javtxt_tags = ?, javtxt_release_date = ?, author_raw = ?, video_category = ?
                    WHERE actor_name = ? AND code = ?
                    ''',
                    normalized_updates,
                )
            conn.commit()
        self.refresh_actor_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def bulk_update_actor_movies_for_supplement(self, updates, status_updates=None):
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
                    str((row or {}).get('_supplement_status', '') or '').strip() or UNENRICHED_STATUS,
                    str((row or {}).get('_supplement_error', '') or '').strip(),
                    actor_name,
                    code,
                )
            )

        if not normalized_updates and not status_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
            status_rows = [
                (
                    str(status or '').strip() or UNENRICHED_STATUS,
                    str(error or '').strip(),
                    str((row or {}).get('actor_name', '') or '').strip(),
                    standardize_video_code((row or {}).get('code', '')),
                )
                for row, status, error in status_updates or []
                if str((row or {}).get('actor_name', '') or '').strip()
                and standardize_video_code((row or {}).get('code', ''))
            ]
            entity_rows = [
                (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[9])
                for row in normalized_updates
            ]
            if entity_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                        javtxt_actors_raw = ?, video_category = ?,
                        supplement_enrichment_status = ?, supplement_enrichment_error = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_rows,
                )
            entity_status_rows = [(row[6], row[7], row[9]) for row in normalized_updates]
            entity_status_rows.extend(
                (status, error, code)
                for status, error, _actor_name, code in status_rows
            )
            if entity_status_rows:
                cursor.executemany(
                    '''
                    UPDATE video_entities
                    SET supplement_enrichment_status = ?,
                        supplement_enrichment_error = ?,
                        supplement_enriched_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    entity_status_rows,
                )
            if normalized_updates:
                cursor.executemany(
                    '''
                    INSERT INTO video_actor_relation_meta (video_code, actor_name, avfan_url, avfan_movie_id, page_number)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(video_code, actor_name) DO UPDATE SET
                        avfan_url = excluded.avfan_url
                    ''',
                    [(row[9], row[8], row[3], '') for row in normalized_updates],
                )
            if legacy_actor_movies:
                if normalized_updates:
                    cursor.executemany(
                        f'''
                        UPDATE {legacy_actor_movies}
                        SET title = ?, author = ?, release_date = ?, avfan_url = ?,
                            author_raw = ?, video_category = ?,
                            supplement_enrichment_status = ?, supplement_enrichment_error = ?,
                            supplement_enriched_at = ''
                        WHERE actor_name = ? AND code = ?
                        ''',
                        normalized_updates,
                    )
                if status_rows:
                    cursor.executemany(
                        f'''
                        UPDATE {legacy_actor_movies}
                        SET supplement_enrichment_status = ?,
                            supplement_enrichment_error = ?,
                            supplement_enriched_at = CURRENT_TIMESTAMP
                        WHERE actor_name = ? AND code = ?
                        ''',
                        status_rows,
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
            prefix_codes_to_clear = []
            actor_codes_to_clear = []

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
                FROM video_entities
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
                SELECT code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       javtxt_actors_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM video_entities
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[0] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[1] or '',
                        'release_date': row[6] or '',
                        'javtxt_tags': row[7] or '',
                        'video_category': normalize_video_category(row[8]),
                    }
                ):
                    if str(row[3] or '').strip() or str(row[4] or '').strip() or str(row[5] or '').strip():
                        prefix_codes_to_clear.append(code)
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[1],
                    avfan_url=row[2],
                    javtxt_url=row[3],
                    author=row[4],
                    author_raw=row[5],
                    release_date=row[6],
                    javtxt_tags=row[7],
                    video_category=row[8],
                )

            cursor.execute(
                '''
                SELECT code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       javtxt_actors_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM video_entities
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[0] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[1] or '',
                        'release_date': row[6] or '',
                        'javtxt_tags': row[7] or '',
                        'video_category': normalize_video_category(row[8]),
                    }
                ):
                    if str(row[3] or '').strip() or str(row[4] or '').strip() or str(row[5] or '').strip():
                        actor_codes_to_clear.append(code)
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[1],
                    avfan_url=row[2],
                    javtxt_url=row[3],
                    author=row[4],
                    author_raw=row[5],
                    release_date=row[6],
                    javtxt_tags=row[7],
                    video_category=row[8],
                )

            if processed_codes_to_clear:
                self._clear_processed_video_javtxt_codes(cursor, processed_codes_to_clear)
            if prefix_codes_to_clear:
                self._clear_web_movie_javtxt_codes(cursor, prefix_codes_to_clear)
            if actor_codes_to_clear:
                self._clear_web_movie_javtxt_codes(cursor, actor_codes_to_clear)
            if processed_codes_to_clear or prefix_codes_to_clear or actor_codes_to_clear:
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
            processed_write_table = self._processed_video_storage_target(cursor)
            cursor.executemany(
                f'''
                UPDATE {processed_write_table}
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE video_entities
                SET video_category = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            if legacy_code_prefix_movies:
                cursor.executemany(
                    f'UPDATE {legacy_code_prefix_movies} SET video_category = ? WHERE code = ?',
                    update_payload,
                )
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
            legacy_code_prefix_movies = self._legacy_table_name(cursor, 'code_prefix_movies')
            legacy_actor_movies = self._legacy_table_name(cursor, 'actor_movies')
            processed_write_table = self._processed_video_storage_target(cursor)
            cursor.executemany(
                f'''
                UPDATE {processed_write_table}
                SET video_category = ?
                WHERE code = ?
                ''',
                payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE video_entities
                SET video_category = ?, updated_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                payload,
            )
            updated_count += int(cursor.rowcount or 0)
            if legacy_code_prefix_movies:
                cursor.executemany(
                    f'UPDATE {legacy_code_prefix_movies} SET video_category = ? WHERE code = ?',
                    payload,
                )
            if legacy_actor_movies:
                cursor.executemany(
                    f'UPDATE {legacy_actor_movies} SET video_category = ? WHERE code = ?',
                    payload,
                )

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

    def list_staged_video_category_codes(self):
        with self._connect() as conn:
            return set(self._list_staged_video_categories(conn.cursor()))

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

        rows = []
        with self._connect() as conn:
            cursor = conn.cursor()
            legacy_table = self._legacy_table_name(cursor, 'processed_videos')
            for offset in range(0, len(normalized_codes), 900):
                code_batch = normalized_codes[offset:offset + 900]
                placeholders = ','.join('?' for _ in code_batch)
                if legacy_table:
                    source_sql = f'''
                        SELECT code, javtxt_actors, javtxt_actors_raw, javtxt_movie_id, javtxt_url,
                               javtxt_tags, javtxt_enrichment_status, javtxt_release_date, release_date
                        FROM {legacy_table}
                    '''
                else:
                    source_sql = '''
                        SELECT code, javtxt_actors, javtxt_actors_raw, javtxt_movie_id, javtxt_url,
                               javtxt_tags, javtxt_enrichment_status, javtxt_release_date, release_date
                        FROM video_entities
                    '''
                cursor.execute(
                    f'''
                    SELECT code, javtxt_actors, javtxt_actors_raw, javtxt_movie_id, javtxt_url,
                           javtxt_tags, javtxt_enrichment_status, javtxt_release_date, release_date
                    FROM ({source_sql}) AS source
                    WHERE code IN ({placeholders})
                    ''',
                    code_batch,
                )
                rows.extend(cursor.fetchall())

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

        legacy_table = self._legacy_table_name(cursor, 'processed_videos')
        if legacy_table:
            source_sql = f'''
                SELECT javtxt_title, title, code, release_date, javtxt_tags,
                       video_category, javtxt_release_date
                FROM {legacy_table}
            '''
        else:
            source_sql = '''
                SELECT javtxt_title, title, code, release_date, javtxt_tags,
                       video_category, javtxt_release_date
                FROM video_entities
            '''
        cursor.execute(
            f'''
            SELECT COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date
            FROM ({source_sql}) AS source
            WHERE source.code = ?
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
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            UPDATE {storage_table}
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
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            UPDATE {storage_table}
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
        storage_table = self._processed_video_storage_target(cursor)
        cursor.execute(
            f'''
            UPDATE {storage_table}
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
            processed_write_table = self._processed_video_storage_target(cursor)
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
                f'''
                UPDATE {processed_write_table}
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
            legacy_processed_videos = self._legacy_table_name(cursor, 'processed_videos')

            if new_records:
                cursor.executemany(
                    '''
                    INSERT INTO video_entities (
                        code, enrichment_status, avfan_enrichment_status, javtxt_enrichment_status
                    ) VALUES (?, ?, ?, ?)
                    ''',
                    [
                        (
                            record['code'],
                            build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                            UNENRICHED_STATUS,
                            UNENRICHED_STATUS,
                        )
                        for record in new_records
                    ],
                )
                if legacy_processed_videos:
                    cursor.executemany(
                        f'''
                        INSERT OR REPLACE INTO {legacy_processed_videos} (
                            code, title, author, duration, size, storage_location,
                            enrichment_status, avfan_enrichment_status, javtxt_enrichment_status
                        ) VALUES (?, '', '', ?, ?, ?, ?, ?, ?)
                        ''',
                        [
                            (
                                record['code'], record['duration'], record['size'], record['storage_location'],
                                build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                                UNENRICHED_STATUS, UNENRICHED_STATUS,
                            )
                            for record in new_records
                        ],
                    )
                cursor.executemany(
                    '''
                    INSERT INTO local_video_records (code, duration, size, storage_location)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        duration = excluded.duration,
                        size = excluded.size,
                        storage_location = excluded.storage_location,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    [
                        (record['code'], record['duration'], record['size'], record['storage_location'])
                        for record in new_records
                    ],
                )
                if legacy_processed_videos:
                    cursor.executemany(
                        f'''
                        UPDATE {legacy_processed_videos}
                        SET duration = CASE WHEN ? <> '' THEN ? ELSE duration END,
                            size = CASE WHEN ? <> '' THEN ? ELSE size END,
                            storage_location = CASE WHEN ? <> '' THEN ? ELSE storage_location END
                        WHERE code = ?
                        ''',
                        [
                            (
                                record['duration'], record['duration'], record['size'], record['size'],
                                record['storage_location'], record['storage_location'], record['code'],
                            )
                            for record in existing_updates
                        ],
                    )

            if existing_updates:
                cursor.executemany(
                    '''
                    INSERT INTO local_video_records (code, duration, size, storage_location)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        duration = CASE WHEN excluded.duration <> '' THEN excluded.duration ELSE local_video_records.duration END,
                        size = CASE WHEN excluded.size <> '' THEN excluded.size ELSE local_video_records.size END,
                        storage_location = CASE WHEN excluded.storage_location <> '' THEN excluded.storage_location ELSE local_video_records.storage_location END,
                        updated_at = CURRENT_TIMESTAMP
                    ''',
                    [
                        (
                            record['code'],
                            record['duration'],
                            record['size'],
                            record['storage_location'],
                        )
                        for record in existing_updates
                    ],
                )

            conn.commit()

        return len(new_records)
