import os
import json
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
import threading
from time import perf_counter
from urllib.parse import quote, unquote

from app.core.backend_protocol import BACKEND_API_REVISION, BACKEND_PROCESS_CODE_FINGERPRINT
from app.core.combo_enrichment import get_combo_label, normalize_combo_key
from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, VIDEO_LIBRARY_TARGET
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.ladder_board import LADDER_BOARD_ACTOR, LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_ACTOR
from app.core.project_paths import DATABASE_FILE, PROJECT_ROOT
from app.core.project_paths import (
    ACTOR_DETAIL_SNAPSHOT_DIR,
    ACTOR_SNAPSHOT_FILE,
    CODE_PREFIX_DETAIL_SNAPSHOT_DIR,
    CODE_PREFIX_SNAPSHOT_FILE,
    DATA_CENTER_SNAPSHOT_FILE,
    LEGACY_CODE_PREFIX_SNAPSHOT_FILE,
    LEGACY_DATA_CENTER_SNAPSHOT_FILE,
    MASTERPIECE_SNAPSHOT_FILE,
    SNAPSHOT_REFRESH_LOG_FILE,
    VIDEO_CATEGORY_SNAPSHOT_FILE,
)
from app.data.database_handler import VideoDatabase
from app.scraper.avfan_scraper import reset_avfan_browser_profile
from app.services.auth import AutoLoginService
from app.services.detail import ActorDetailLibrary, CodePrefixDetailLibrary, resolve_update_status
from app.services.enrichment import (
    ComboEnrichmentService,
    ComboProgressService,
    ComboTaskLogger,
    EnrichmentProgressService,
    EnrichmentTaskState,
    LibraryEnrichmentService,
    TaskTraceLogger,
)
from app.services.identity import split_actor_names
from app.services.ladder import LadderBoardService, VideoLadderTagService
from app.services.library import (
    ActorLibrarySyncService,
    CanglanggeCandidateService,
    CodePrefixLibrary,
    CodePrefixVideoCategoryBulkService,
    DataCenterService,
    LibraryAdminService,
    LibraryStatusSyncService,
    PathLibrary,
    summarize_paths,
)
from app.services.local_video import LocalVideoLibraryService
from app.services.queen_library_service import QueenLibraryService
from app.services.video import VideoFilterService
from app.core.project_paths import QUEEN_LIBRARY_DB_FILE


class BackendService:
    def __init__(self, base_dir=None, instance_token=''):
        self.base_dir = Path(base_dir or PROJECT_ROOT)
        self.instance_token = str(instance_token or '').strip()
        self.process_id = os.getpid()
        self._ensure_snapshot_runtime_dir()
        self._migrate_legacy_snapshot_file(LEGACY_DATA_CENTER_SNAPSHOT_FILE, DATA_CENTER_SNAPSHOT_FILE)
        self._migrate_legacy_snapshot_file(LEGACY_CODE_PREFIX_SNAPSHOT_FILE, CODE_PREFIX_SNAPSHOT_FILE)
        self.db = VideoDatabase(DATABASE_FILE)
        self.video_filter_service = VideoFilterService()
        self.video_ladder_tag_service = VideoLadderTagService(self.db)
        self.local_video_library = LocalVideoLibraryService(self.db)
        self.actor_detail_library = ActorDetailLibrary(self.db, self.video_ladder_tag_service, self.video_filter_service)
        self.actor_library_sync_service = ActorLibrarySyncService(self.db)
        self.code_prefix_detail_library = CodePrefixDetailLibrary(
            self.db,
            self.video_ladder_tag_service,
            self.video_filter_service,
        )
        self.code_prefix_library = CodePrefixLibrary(self.db, self.video_filter_service)
        self.code_prefix_video_category_bulk_service = CodePrefixVideoCategoryBulkService(self.db)
        self.canglangge_candidate_service = CanglanggeCandidateService(self.db)
        self.data_center_service = DataCenterService(
            self.db,
            self.video_filter_service,
            snapshot_file=DATA_CENTER_SNAPSHOT_FILE,
            refresh_logger=self._append_snapshot_refresh_log,
        )
        self.library_admin_service = LibraryAdminService(self.db)
        self.library_status_sync_service = LibraryStatusSyncService(self.db)
        self.ladder_board_service = LadderBoardService(self.db)
        self.path_library = PathLibrary()
        self.queen_library_service = QueenLibraryService(QUEEN_LIBRARY_DB_FILE)
        self.enrichment_progress = EnrichmentProgressService()
        self.combo_progress = ComboProgressService()
        self.enrichment_task_state = EnrichmentTaskState()
        self._snapshot_lock = threading.Lock()
        self._ladder_board_snapshots = {}
        self._path_library_snapshot = None
        self._canglangge_snapshot = None
        self._snapshot_refresh_log_file = SNAPSHOT_REFRESH_LOG_FILE
        self._snapshot_refresh_log_lock = threading.Lock()
        self._actor_snapshot_file = ACTOR_SNAPSHOT_FILE
        self._actor_detail_snapshot_dir = ACTOR_DETAIL_SNAPSHOT_DIR
        self._actor_snapshot_file_lock = threading.Lock()
        self._actor_snapshot_filter_fingerprint = self._build_actor_snapshot_filter_fingerprint(
            self._load_actor_snapshot_filter_settings()
        )
        self._actor_library_snapshots = {}
        self._actor_detail_snapshots = {}
        self._code_prefix_snapshot_file = CODE_PREFIX_SNAPSHOT_FILE
        self._code_prefix_detail_snapshot_dir = CODE_PREFIX_DETAIL_SNAPSHOT_DIR
        self._code_prefix_snapshot_file_lock = threading.Lock()
        self._code_prefix_snapshot_filter_fingerprint = self._build_code_prefix_snapshot_filter_fingerprint(
            self._load_code_prefix_snapshot_filter_settings()
        )
        self._code_prefix_library_snapshots = {}
        self._code_prefix_detail_snapshots = {}
        self._masterpiece_snapshot_file = MASTERPIECE_SNAPSHOT_FILE
        self._masterpiece_snapshot_file_lock = threading.Lock()
        self._masterpiece_detail_snapshots = {}
        self._video_category_snapshot_file = VIDEO_CATEGORY_SNAPSHOT_FILE
        self._video_category_snapshot_file_lock = threading.Lock()
        self._video_category_snapshot_filter_fingerprint = self._build_video_category_snapshot_filter_fingerprint(
            self._load_video_category_snapshot_filter_settings()
        )
        self._video_category_overview_snapshot = None
        self._load_actor_snapshots()
        self._load_code_prefix_snapshots()
        self._load_masterpiece_snapshots()
        self._load_video_category_snapshot()
        self.database_loaded = False

    def load_database(self):
        self.db.ensure_startup_maintenance()
        self.actor_library_sync_service.sync_from_video_library()
        self.database_loaded = True
        return {
            'count': self.db.get_video_count(),
            'actor_count': self.db.get_actor_count(),
            'db_path': str(self.db.db_path),
        }

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'backend_revision': BACKEND_API_REVISION,
            'backend_code_fingerprint': BACKEND_PROCESS_CODE_FINGERPRINT,
            'backend_instance_token': self.instance_token,
            'backend_process_id': self.process_id,
            'project_root': str(self.base_dir),
            'database_loaded': self.database_loaded,
            'db_path': str(self.db.db_path),
            'enrichment_running': self.enrichment_task_state.is_running,
            'active_task_kind': self.enrichment_task_state.active_kind,
        }

    def scan(self, folder_path):
        self.ensure_database_loaded()
        return self.local_video_library.scan_folder(folder_path)

    def rename(self, plans_data):
        return self.local_video_library.execute_renames(plans_data)

    def import_videos(self, plans_data):
        self.ensure_database_loaded()
        return {'success_count': self.local_video_library.import_videos(plans_data)}

    def list_videos(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_search = str(search_text or '').strip()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_video_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)

        medal_maps = None
        expanded_rows = []
        if normalized_search:
            medal_maps = self.video_ladder_tag_service.load_medal_maps()
            expanded_rows = self._expand_video_search_candidates_by_ladder_tags(normalized_search, medal_maps=medal_maps)

        if expanded_rows:
            rows_by_code = {
                str((row or {}).get('code', '') or '').strip(): dict(row or {})
                for row in self._list_videos_query(
                    normalized_search,
                    sort_field=normalized_sort_field,
                    sort_order=normalized_sort_order,
                )
                if str((row or {}).get('code', '') or '').strip()
            }
            for row in expanded_rows:
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})

            visible_rows = self.video_filter_service.filter_video_rows(list(rows_by_code.values()))
            enriched_rows = self.video_ladder_tag_service.enrich_video_rows(visible_rows, medal_maps=medal_maps)
            filtered_rows = self.video_ladder_tag_service.filter_video_rows(enriched_rows, normalized_search)
            sorted_rows = self._sort_video_rows_for_listing(filtered_rows, normalized_sort_field, normalized_sort_order)
            paged_rows = self._slice_rows(sorted_rows, normalized_limit, normalized_offset)
            return {
                'videos': paged_rows,
                'total_count': len(sorted_rows),
                'offset': normalized_offset,
                'limit': normalized_limit,
            }

        rows = self._list_videos_query(
            normalized_search,
            sort_field=normalized_sort_field,
            sort_order=normalized_sort_order,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return {
            'videos': self.video_filter_service.filter_video_rows(rows),
            'total_count': self._count_videos_for_listing(normalized_search, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def get_video_enrichment_summary(self):
        return {'summary': self.db.get_video_enrichment_summary()}

    def list_masterpiece_entries(self):
        self.ensure_database_loaded()
        return {'entries': self.db.list_masterpiece_entries()}

    def add_masterpiece_entry(self, code):
        self.ensure_database_loaded()
        result = {'entry': self.db.add_masterpiece_entry(code)}
        self._invalidate_masterpiece_snapshots()
        return result

    def update_masterpiece_entry_medal(self, code, medal):
        self.ensure_database_loaded()
        result = {'entry': self.db.update_masterpiece_entry_medal(code, medal)}
        self._invalidate_masterpiece_snapshots()
        return result

    def get_masterpiece_detail(self, code):
        self.ensure_database_loaded()
        detail = self.db.get_masterpiece_detail_record(code)
        if not detail:
            raise FileNotFoundError(f'鍚嶄綔鍫傛潯鐩笉瀛樺湪: {code}')
        return {'detail': detail}

    def get_masterpiece_detail_snapshot(self, code, force_refresh=False):
        self.ensure_database_loaded()
        normalized_code = str(code or '').strip().upper()
        if not normalized_code:
            raise ValueError('缺少名作堂番号')
        with self._snapshot_guard():
            snapshot = (self._masterpiece_detail_snapshots or {}).get(normalized_code)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_masterpiece_detail_snapshot(snapshot),
                    'cache_hit': True,
                }

        started_at = perf_counter()
        payload = self.get_masterpiece_detail(normalized_code)
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            detail=dict(payload.get('detail', {}) or {}),
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._masterpiece_detail_snapshots[normalized_code] = snapshot
            self._persist_masterpiece_snapshots()
        self._append_snapshot_refresh_log(
            snapshot_key='masterpiece_detail',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='detail',
        )
        return {
            **self._clone_masterpiece_detail_snapshot(snapshot),
            'cache_hit': False,
        }

    def list_global_medals(self):
        self.ensure_database_loaded()
        return {'medals': self.db.list_global_medals()}

    def add_global_medal(self, name, description=''):
        self.ensure_database_loaded()
        return {'medal': self.db.add_global_medal(name, description)}

    def update_global_medal_description(self, name, description=''):
        self.ensure_database_loaded()
        return {'medal': self.db.update_global_medal_description(name, description)}

    def delete_global_medal(self, name):
        self.ensure_database_loaded()
        return self.db.delete_global_medal(name)

    def get_video_detail(self, code):
        self.ensure_database_loaded()
        detail = self.db.get_video_detail_record(code)
        if not detail:
            raise FileNotFoundError(f'视频不存在: {code}')
        return {'video': detail}

    def get_data_center_summary(self, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_summary_snapshot(force_refresh=force_refresh)

    def get_actor_metric_analysis(self, metric_key, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_actor_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)

    def get_actor_metric_bucket(self, metric_key, bucket_value, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_actor_metric_bucket_snapshot(
            metric_key,
            bucket_value,
            force_refresh=force_refresh,
        )

    def get_code_prefix_metric_analysis(self, metric_key, force_refresh=False):
        self.ensure_database_loaded()
        return self.data_center_service.get_code_prefix_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)

    def get_metric_analysis(self, analysis_type, metric_key, force_refresh=False):
        normalized_type = str(analysis_type or 'actor').strip().lower() or 'actor'
        if normalized_type == 'actor':
            return self.get_actor_metric_analysis(metric_key, force_refresh=force_refresh)
        if normalized_type == 'code_prefix':
            return self.get_code_prefix_metric_analysis(metric_key, force_refresh=force_refresh)
        raise ValueError(f'Unknown analysis type: {normalized_type}')

    def get_enrichment_progress(self):
        if self.enrichment_task_state.active_kind == 'combo':
            return {'progress': self.combo_progress.snapshot()}
        combo_snapshot = self.combo_progress.snapshot()
        if (
            combo_snapshot.get('task_kind') == 'combo'
            and (
                combo_snapshot.get('is_running')
                or combo_snapshot.get('total_count', 0)
                or combo_snapshot.get('message')
            )
        ):
            return {'progress': combo_snapshot}
        return {'progress': self.enrichment_progress.snapshot()}

    def reset_video_enrichments(self, codes, source_key=None):
        self.ensure_database_loaded()
        return {'reset_count': self.db.reset_video_enrichments(codes, source_key=source_key)}

    def list_videos_requiring_manual_category(self):
        self.ensure_database_loaded()
        overview = self.db.list_videos_requiring_manual_category()
        return {
            **dict(overview or {}),
            'videos': self.video_filter_service.filter_video_rows((overview or {}).get('videos', []) or []),
        }

    def list_videos_requiring_manual_category_snapshot(self, force_refresh=False):
        self.ensure_database_loaded()
        self._refresh_video_category_snapshot_filter_state()
        with self._snapshot_guard():
            snapshot = getattr(self, '_video_category_overview_snapshot', None)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_video_category_snapshot(snapshot),
                    'cache_hit': True,
                }

        started_at = perf_counter()
        overview = self.list_videos_requiring_manual_category()
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            videos=[dict(row or {}) for row in (overview or {}).get('videos', []) or []],
            staged_count=int((overview or {}).get('staged_count', 0) or 0),
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._video_category_overview_snapshot = snapshot
            self._persist_video_category_snapshot()
        self._append_snapshot_refresh_log(
            snapshot_key='video_category_overview',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='list',
        )
        return {
            **self._clone_video_category_snapshot(snapshot),
            'cache_hit': False,
        }

    def stage_video_category(self, code, category):
        self.ensure_database_loaded()
        result = self.db.stage_video_category(code, category)
        self._invalidate_video_category_snapshot()
        return result

    def stage_video_categories(self, entries):
        self.ensure_database_loaded()
        result = self.db.stage_video_categories(entries)
        self._invalidate_video_category_snapshot()
        return result

    def sync_staged_video_categories(self):
        self.ensure_database_loaded()
        result = self.db.sync_staged_video_categories()
        self._invalidate_video_category_snapshot()
        return result

    def update_video_category(self, code, category):
        self.ensure_database_loaded()
        result = {'updated_count': self.db.update_video_category(code, category)}
        self._invalidate_video_category_snapshot()
        return result

    def list_actors(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_actor_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        rows = list(
            self._list_actors_query(
                search_text,
                sort_field=normalized_sort_field,
                sort_order=normalized_sort_order,
                limit=normalized_limit,
                offset=normalized_offset,
            )
        )
        self._attach_actor_ladder_tiers(rows)
        self._attach_actor_update_status(rows)
        return {
            'actors': rows,
            'total_count': self._count_actors_for_listing(search_text, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def list_actors_snapshot(
        self,
        search_text='',
        sort_field='name',
        sort_order='asc',
        limit=None,
        offset=0,
        force_refresh=False,
    ):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_actor_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        self._refresh_actor_snapshot_filter_state()
        snapshot_key = self._build_actor_list_snapshot_key(
            search_text,
            normalized_sort_field,
            normalized_sort_order,
            normalized_limit,
            normalized_offset,
        )
        with self._snapshot_guard():
            snapshot = (self._actor_library_snapshots or {}).get(snapshot_key)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_actor_list_snapshot(snapshot),
                    'cache_hit': True,
                }

        started_at = perf_counter()
        payload = self.list_actors(
            search_text,
            sort_field=normalized_sort_field,
            sort_order=normalized_sort_order,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            actors=[dict(row or {}) for row in payload.get('actors', []) or []],
            total_count=int(payload.get('total_count', 0) or 0),
            offset=normalized_offset,
            limit=normalized_limit,
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._actor_library_snapshots[snapshot_key] = snapshot
            self._persist_actor_snapshots()
        self._append_snapshot_refresh_log(
            snapshot_key='actor_library',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='list',
        )
        return {
            **self._clone_actor_list_snapshot(snapshot),
            'cache_hit': False,
        }

    def get_actor_detail(self, actor_name):
        self.ensure_database_loaded()
        return {'actor': self.actor_detail_library.get_actor_detail(actor_name)}

    def get_actor_detail_snapshot(self, actor_name, force_refresh=False):
        self.ensure_database_loaded()
        normalized_actor_name = str(actor_name or '').strip()
        if not normalized_actor_name:
            raise ValueError('缺少演员名称')
        self._refresh_actor_snapshot_filter_state()
        snapshot_key = normalized_actor_name.casefold()
        with self._snapshot_guard():
            snapshot = (self._actor_detail_snapshots or {}).get(snapshot_key)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_actor_detail_snapshot(snapshot),
                    'cache_hit': True,
                }
            if not force_refresh:
                disk_snapshot = self._load_single_actor_detail_snapshot_file(normalized_actor_name)
                if disk_snapshot is not None:
                    return {
                        **self._clone_actor_detail_snapshot(disk_snapshot),
                        'cache_hit': True,
                    }

        started_at = perf_counter()
        payload = self.get_actor_detail(normalized_actor_name)
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            actor=dict(payload.get('actor', {}) or {}),
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._actor_detail_snapshots[snapshot_key] = snapshot
            self._persist_single_actor_detail_snapshot_file(normalized_actor_name, snapshot)
        self._append_snapshot_refresh_log(
            snapshot_key='actor_detail',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='detail',
        )
        return {
            **self._clone_actor_detail_snapshot(snapshot),
            'cache_hit': False,
        }

    def add_actor(self, actor_name, birthday='', age=''):
        self.ensure_database_loaded()
        result = {'created_count': self.library_admin_service.add_actor(actor_name, birthday=birthday, age=age)}
        self._invalidate_actor_snapshots()
        return result

    def list_canglangge_candidates(self, force_refresh=False):
        self.ensure_database_loaded()
        return self._get_canglangge_snapshot(force_refresh=force_refresh)

    def admit_canglangge_candidates(self, actor_names):
        self.ensure_database_loaded()
        admitted_count = 0
        for actor_name in actor_names or []:
            admitted_count += int(self.library_admin_service.add_actor(actor_name, birthday='', age='') or 0)
        self._remove_from_canglangge_snapshot(actor_names)
        return {
            'admitted_count': admitted_count,
            'refreshed_at': self._snapshot_refreshed_at(getattr(self, '_canglangge_snapshot', None)),
        }

    def delete_canglangge_candidates(self, actor_names):
        self.ensure_database_loaded()
        deleted_count = 0
        for actor_name in actor_names or []:
            deleted_count += int(self.db.hide_actor(actor_name) or 0)
        self._remove_from_canglangge_snapshot(actor_names)
        return {
            'deleted_count': deleted_count,
            'refreshed_at': self._snapshot_refreshed_at(getattr(self, '_canglangge_snapshot', None)),
        }

    def reset_actor_enrichments(self, actor_names, source_key=None):
        self.ensure_database_loaded()
        result = {'reset_count': self.db.reset_actor_enrichments(actor_names, source_key=source_key)}
        self._invalidate_actor_snapshots()
        return result

    def rename_actor(self, old_name, new_name, birthday='', age=''):
        result = {'updated_count': self.library_admin_service.rename_actor(old_name, new_name, birthday=birthday, age=age)}
        self._invalidate_actor_snapshots()
        return result

    def delete_actor(self, actor_name):
        result = {'deleted_count': self.library_admin_service.delete_actor(actor_name)}
        self._invalidate_actor_snapshots()
        return result

    def list_code_prefixes(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_code_prefix_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        rows = list(
            self._list_code_prefix_query(
                search_text,
                sort_field=normalized_sort_field,
                sort_order=normalized_sort_order,
                limit=normalized_limit,
                offset=normalized_offset,
            )
        )
        return {
            'prefixes': rows,
            'total_count': self._count_code_prefixes_for_listing(search_text, fallback_rows=rows),
            'offset': normalized_offset,
            'limit': normalized_limit,
        }

    def list_code_prefixes_snapshot(
        self,
        search_text='',
        sort_field='prefix',
        sort_order='asc',
        limit=None,
        offset=0,
        force_refresh=False,
    ):
        self.ensure_database_loaded()
        normalized_limit = self._normalize_list_limit(limit)
        normalized_offset = self._normalize_list_offset(offset)
        normalized_sort_field = self._normalize_code_prefix_sort_field(sort_field)
        normalized_sort_order = self._normalize_sort_order(sort_order)
        self._refresh_code_prefix_snapshot_filter_state()
        snapshot_key = self._build_code_prefix_list_snapshot_key(
            search_text,
            normalized_sort_field,
            normalized_sort_order,
            normalized_limit,
            normalized_offset,
        )
        with self._snapshot_guard():
            snapshot = (self._code_prefix_library_snapshots or {}).get(snapshot_key)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_code_prefix_list_snapshot(snapshot),
                    'cache_hit': True,
                }

        started_at = perf_counter()
        payload = self.list_code_prefixes(
            search_text,
            sort_field=normalized_sort_field,
            sort_order=normalized_sort_order,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            prefixes=[dict(row or {}) for row in payload.get('prefixes', []) or []],
            total_count=int(payload.get('total_count', 0) or 0),
            offset=normalized_offset,
            limit=normalized_limit,
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._code_prefix_library_snapshots[snapshot_key] = snapshot
            self._persist_code_prefix_snapshots()
        self._append_snapshot_refresh_log(
            snapshot_key='code_prefix_library',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='list',
        )
        return {
            **self._clone_code_prefix_list_snapshot(snapshot),
            'cache_hit': False,
        }

    def get_code_prefix_detail(self, prefix):
        self.ensure_database_loaded()
        return {'prefix_detail': self.code_prefix_detail_library.get_prefix_detail(prefix)}

    def get_code_prefix_detail_snapshot(self, prefix, force_refresh=False):
        self.ensure_database_loaded()
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            raise ValueError('缺少番号前缀')
        self._refresh_code_prefix_snapshot_filter_state()
        with self._snapshot_guard():
            snapshot = (self._code_prefix_detail_snapshots or {}).get(normalized_prefix)
            if snapshot is not None and not force_refresh:
                return {
                    **self._clone_code_prefix_detail_snapshot(snapshot),
                    'cache_hit': True,
                }
            if not force_refresh:
                disk_snapshot = self._load_single_code_prefix_detail_snapshot_file(normalized_prefix)
                if disk_snapshot is not None:
                    return {
                        **self._clone_code_prefix_detail_snapshot(disk_snapshot),
                        'cache_hit': True,
                    }

        started_at = perf_counter()
        payload = self.get_code_prefix_detail(normalized_prefix)
        refresh_duration_ms = self._build_refresh_duration_ms(started_at)
        snapshot = self._build_snapshot_payload(
            prefix_detail=dict(payload.get('prefix_detail', {}) or {}),
            refresh_duration_ms=refresh_duration_ms,
        )
        with self._snapshot_guard():
            self._code_prefix_detail_snapshots[normalized_prefix] = snapshot
            self._persist_single_code_prefix_detail_snapshot_file(normalized_prefix, snapshot)
        self._append_snapshot_refresh_log(
            snapshot_key='code_prefix_detail',
            refreshed_at=self._snapshot_refreshed_at(snapshot),
            refresh_duration_ms=refresh_duration_ms,
            cache_kind='detail',
        )
        return {
            **self._clone_code_prefix_detail_snapshot(snapshot),
            'cache_hit': False,
        }

    def rebuild_detail_snapshots(self):
        self.ensure_database_loaded()
        actor_summary = self._rebuild_actor_detail_snapshots()
        code_prefix_summary = self._rebuild_code_prefix_detail_snapshots()
        return {
            **actor_summary,
            **code_prefix_summary,
        }

    def add_code_prefix(self, prefix):
        self.ensure_database_loaded()
        result = {'created_count': self.library_admin_service.add_code_prefix(prefix)}
        self._invalidate_code_prefix_snapshots()
        return result

    def update_code_prefix_uncategorized_video_category(self, prefix, category):
        self.ensure_database_loaded()
        result = self.code_prefix_video_category_bulk_service.update_uncategorized_videos(prefix, category)
        self._invalidate_code_prefix_snapshots()
        return result

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        self.ensure_database_loaded()
        result = {'reset_count': self.db.reset_code_prefix_enrichments(prefixes, source_key=source_key)}
        self._invalidate_code_prefix_snapshots()
        return result

    def rename_code_prefix(self, old_prefix, new_prefix):
        result = {'updated_count': self.library_admin_service.rename_code_prefix(old_prefix, new_prefix)}
        self._invalidate_code_prefix_snapshots()
        return result

    def delete_code_prefix(self, prefix):
        result = {'deleted_count': self.library_admin_service.delete_code_prefix(prefix)}
        self._invalidate_code_prefix_snapshots()
        return result

    def get_ladder_board(self, board_key, force_refresh=False):
        self.ensure_database_loaded()
        return self._get_ladder_board_snapshot(board_key, force_refresh=force_refresh)

    def admit_ladder_entry(self, board_key, entity_name, tier):
        self.ensure_database_loaded()
        board = self.ladder_board_service.admit_entry(board_key, entity_name, tier)
        if str(board_key or '').strip() == LADDER_BOARD_CODE_PREFIX:
            self._invalidate_code_prefix_snapshots()
        if str(board_key or '').strip() == LADDER_BOARD_ACTOR:
            self._invalidate_actor_ladder_snapshots(entity_name)
        return self._store_ladder_board_snapshot(board_key, board)

    def update_ladder_entry_medal(self, board_key, entity_name, medal):
        self.ensure_database_loaded()
        board = self.ladder_board_service.update_medal(board_key, entity_name, medal)
        if str(board_key or '').strip() == LADDER_BOARD_CODE_PREFIX:
            self._invalidate_code_prefix_snapshots()
        return self._store_ladder_board_snapshot(board_key, board)

    def _expand_video_search_candidates_by_ladder_tags(self, search_text, medal_maps=None):
        normalized_search = str(search_text or '').strip().lower()
        if not normalized_search:
            return []

        active_medal_maps = dict(medal_maps or self.video_ladder_tag_service.load_medal_maps())
        actor_names = [
            actor_name
            for actor_name, medals in (active_medal_maps.get('actor_medal_map', {}) or {}).items()
            if any(normalized_search in str(medal or '').strip().lower() for medal in medals or [])
        ]
        prefixes = [
            prefix
            for prefix, medals in (active_medal_maps.get('prefix_medal_map', {}) or {}).items()
            if any(normalized_search in str(medal or '').strip().lower() for medal in medals or [])
        ]

        rows_by_code = {}
        if actor_names and hasattr(self.db, 'list_local_videos_by_actor_names'):
            for row in self.db.list_local_videos_by_actor_names(actor_names):
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})
        if prefixes and hasattr(self.db, 'list_local_videos_by_prefixes'):
            for row in self.db.list_local_videos_by_prefixes(prefixes):
                code = str((row or {}).get('code', '') or '').strip()
                if code:
                    rows_by_code[code] = dict(row or {})
        return list(rows_by_code.values())

    @staticmethod
    def _normalize_sort_order(sort_order):
        return 'desc' if str(sort_order or '').strip().lower() == 'desc' else 'asc'

    @staticmethod
    def _normalize_video_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return normalized if normalized in ('code', 'video_category', 'duration', 'size', 'release_date') else 'code'

    @staticmethod
    def _normalize_actor_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return normalized if normalized in ('name', 'birthday', 'age') else 'name'

    @staticmethod
    def _normalize_code_prefix_sort_field(sort_field):
        normalized = str(sort_field or '').strip()
        return (
            normalized
            if normalized in ('prefix', 'video_count', 'avfan_total_videos', 'earliest_release_date', 'latest_release_date')
            else 'prefix'
        )

    @staticmethod
    def _normalize_list_limit(limit):
        if limit is None:
            return None
        normalized_limit = int(limit or 0)
        return normalized_limit if normalized_limit > 0 else None

    @staticmethod
    def _normalize_list_offset(offset):
        return max(int(offset or 0), 0)

    @staticmethod
    def _slice_rows(rows, limit=None, offset=0):
        normalized_rows = list(rows or [])
        normalized_offset = max(int(offset or 0), 0)
        if limit is None:
            return normalized_rows[normalized_offset:]
        normalized_limit = max(int(limit or 0), 0)
        return normalized_rows[normalized_offset: normalized_offset + normalized_limit]

    def _list_videos_query(self, search_text='', sort_field='code', sort_order='asc', limit=None, offset=0):
        try:
            return self.db.list_videos(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.db.list_videos(search_text)

    def _list_actors_query(self, search_text='', sort_field='name', sort_order='asc', limit=None, offset=0):
        try:
            return self.db.list_actors(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.db.list_actors(search_text)

    def _list_code_prefix_query(self, search_text='', sort_field='prefix', sort_order='asc', limit=None, offset=0):
        try:
            return self.code_prefix_library.list_prefixes(
                search_text,
                sort_field=sort_field,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except TypeError:
            return self.code_prefix_library.list_prefixes(search_text)

    def _sort_video_rows_for_listing(self, rows, sort_field, sort_order):
        reverse = self._normalize_sort_order(sort_order) == 'desc'

        def _video_sort_key(row):
            current_row = dict(row or {})
            if sort_field == 'release_date':
                return (str(current_row.get('release_date', '') or ''), str(current_row.get('code', '') or ''))
            if sort_field == 'video_category':
                return (str(current_row.get('video_category', '') or ''), str(current_row.get('code', '') or ''))
            if sort_field == 'size':
                return (self._safe_float(current_row.get('size', '')), str(current_row.get('code', '') or ''))
            if sort_field == 'duration':
                return (self._duration_to_seconds(current_row.get('duration', '')), str(current_row.get('code', '') or ''))
            return self._natural_code_key(current_row.get('code', ''))

        return sorted(list(rows or []), key=_video_sort_key, reverse=reverse)

    def _count_videos_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.db, 'count_videos'):
            return int(self.db.count_videos(search_text) or 0)
        return len(list(fallback_rows or []))

    def _count_actors_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.db, 'count_actors'):
            return int(self.db.count_actors(search_text) or 0)
        return len(list(fallback_rows or []))

    def _count_code_prefixes_for_listing(self, search_text='', fallback_rows=None):
        if hasattr(self.code_prefix_library, 'count_prefixes'):
            return int(self.code_prefix_library.count_prefixes(search_text) or 0)
        return len(list(fallback_rows or []))

    @staticmethod
    def _safe_float(value):
        try:
            return float(str(value or '').strip() or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _duration_to_seconds(value):
        parts = [segment for segment in str(value or '').strip().split(':') if segment != '']
        if len(parts) != 3:
            return 0
        try:
            hours, minutes, seconds = [int(segment) for segment in parts]
        except ValueError:
            return 0
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _natural_code_key(value):
        normalized_value = str(value or '').strip().upper()
        if '-' in normalized_value:
            prefix, suffix = normalized_value.split('-', 1)
            try:
                return prefix, int(suffix), normalized_value
            except ValueError:
                return prefix, 0, normalized_value
        return normalized_value, 0, normalized_value

    def _attach_actor_update_status(self, rows):
        actor_names = [
            str((row or {}).get('name', '') or '').strip()
            for row in (rows or [])
            if str((row or {}).get('name', '') or '').strip()
        ]
        if not actor_names:
            return rows
        filter_settings = None
        if hasattr(self.video_filter_service, 'load_settings'):
            filter_settings = self.video_filter_service.load_settings()

        local_rows = []
        if hasattr(self.db, 'list_local_videos_by_actor_names'):
            try:
                local_rows = list(self.db.list_local_videos_by_actor_names(actor_names, refresh_categories=False))
            except TypeError:
                local_rows = list(self.db.list_local_videos_by_actor_names(actor_names))
        web_movies_by_actor = {}
        if hasattr(self.db, 'list_actor_movies_by_names'):
            web_movies_by_actor = self.db.list_actor_movies_by_names(actor_names)

        local_movies_by_actor = {name: [] for name in actor_names}
        actor_name_set = set(actor_names)
        for row in local_rows:
            current_names = {
                str(name or '').strip()
                for name in split_actor_names((row or {}).get('author', ''))
                if str(name or '').strip()
            }
            for actor_name in actor_name_set.intersection(current_names):
                local_movies_by_actor.setdefault(actor_name, []).append(dict(row or {}))

        for row in rows:
            actor_name = str((row or {}).get('name', '') or '').strip()
            local_movies = local_movies_by_actor.get(actor_name, [])
            web_movies = web_movies_by_actor.get(actor_name, [])
            visible_local_movies = (
                self.video_filter_service.filter_video_rows(local_movies, settings=filter_settings)
                if local_movies
                else []
            )
            eligible_web_movies = [
                movie
                for movie in (
                    self.video_filter_service.filter_video_rows(web_movies, settings=filter_settings)
                    if web_movies
                    else []
                )
                if is_javtxt_eligible_movie(movie)
            ]
            row['update_status'] = resolve_update_status(visible_local_movies + eligible_web_movies)
        return rows

    def _attach_actor_ladder_tiers(self, rows):
        tier_map = {}
        if hasattr(self.db, 'list_ladder_entries'):
            tier_map = {
                str((entry or {}).get('entity_name', '') or '').strip(): str((entry or {}).get('tier', '') or '').strip().upper()
                for entry in self.db.list_ladder_entries(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR)
                if str((entry or {}).get('entity_name', '') or '').strip()
            }
        for row in rows or []:
            actor_name = str((row or {}).get('name', '') or '').strip()
            row['ladder_tier'] = tier_map.get(actor_name, str((row or {}).get('ladder_tier', '') or '').strip().upper())
        return rows

    def list_paths(self, force_refresh=False):
        return self._get_path_library_snapshot(force_refresh=force_refresh)

    def list_queen_library_snapshot(self, force_refresh=False):
        return {
            'queens': self.queen_library_service.list_queens(),
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def list_queen_keywords_snapshot(self, force_refresh=False):
        return {
            'keywords': self.queen_library_service.list_keywords(),
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def search_queen_keyword(self, keyword, show_browser=True):
        result = self.queen_library_service.search_keyword(keyword, show_browser=show_browser)
        return {
            **dict(result or {}),
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def refresh_queen_library(self, show_browser=True):
        result = self.queen_library_service.refresh_all(show_browser=show_browser)
        return {
            **dict(result or {}),
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def get_queen_detail_snapshot(self, queen_name, force_refresh=False):
        return {
            **dict(self.queen_library_service.get_queen_detail(queen_name) or {}),
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def delete_queen_video(self, record_id):
        deleted_count = self.queen_library_service.delete_queen_video(record_id)
        return {
            'deleted_count': deleted_count,
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def delete_queen(self, queen_name):
        deleted_count = self.queen_library_service.delete_queen(queen_name)
        return {
            'deleted_count': deleted_count,
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def delete_queen_keyword(self, keyword):
        deleted_count = self.queen_library_service.delete_keyword(keyword)
        return {
            'deleted_count': deleted_count,
            'refreshed_at': self._current_snapshot_timestamp(),
        }

    def add_path(self, folder_path):
        path_record = self.path_library.build_path_record(folder_path)
        saved_record = self.db.add_path(path_record['path'])
        enriched_record = self.path_library.with_exists_status(saved_record)
        self.db.update_path_storage_info(enriched_record['id'], enriched_record)
        self._append_to_path_snapshot(enriched_record)
        return {'path': enriched_record, 'refreshed_at': self._snapshot_refreshed_at(self._path_library_snapshot)}

    def delete_path(self, path_id):
        if path_id is None:
            raise ValueError('缺少 path_id')
        deleted_count = self.db.delete_path(path_id)
        self._remove_from_path_snapshot(path_id)
        return {'deleted_count': deleted_count, 'refreshed_at': self._snapshot_refreshed_at(self._path_library_snapshot)}

    def _get_ladder_board_snapshot(self, board_key, force_refresh=False):
        normalized_board_key = str(board_key or '').strip()
        with self._snapshot_guard():
            snapshots = getattr(self, '_ladder_board_snapshots', None)
            if not isinstance(snapshots, dict):
                snapshots = {}
                self._ladder_board_snapshots = snapshots
            snapshot = snapshots.get(normalized_board_key)
            if snapshot is None or force_refresh:
                board = self.ladder_board_service.get_board(normalized_board_key)
                snapshot = self._build_snapshot_payload(board=self._clone_ladder_board(board))
                snapshots[normalized_board_key] = snapshot
            return {
                'board': self._clone_ladder_board((snapshot or {}).get('board', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _store_ladder_board_snapshot(self, board_key, board):
        normalized_board_key = str(board_key or '').strip()
        with self._snapshot_guard():
            snapshots = getattr(self, '_ladder_board_snapshots', None)
            if not isinstance(snapshots, dict):
                snapshots = {}
                self._ladder_board_snapshots = snapshots
            snapshot = self._build_snapshot_payload(board=self._clone_ladder_board(board))
            snapshots[normalized_board_key] = snapshot
            return {
                'board': self._clone_ladder_board((snapshot or {}).get('board', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _get_path_library_snapshot(self, force_refresh=False):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None or force_refresh:
                paths = [self.path_library.with_exists_status(row) for row in self.db.list_paths()]
                snapshot = self._build_snapshot_payload(
                    paths=[dict(path or {}) for path in paths],
                    summary=summarize_paths(paths),
                )
                self._path_library_snapshot = snapshot
            return {
                'paths': [dict(path or {}) for path in (snapshot or {}).get('paths', []) or []],
                'summary': dict((snapshot or {}).get('summary', {}) or {}),
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _append_to_path_snapshot(self, path_record):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None:
                return
            paths = [dict(path or {}) for path in (snapshot or {}).get('paths', []) or []]
            target_id = (path_record or {}).get('id')
            paths = [path for path in paths if path.get('id') != target_id]
            paths.append(dict(path_record or {}))
            paths.sort(
                key=lambda row: (
                    str((row or {}).get('created_at', '') or ''),
                    int((row or {}).get('id', 0) or 0),
                ),
                reverse=True,
            )
            self._path_library_snapshot = self._build_snapshot_payload(
                paths=paths,
                summary=summarize_paths(paths),
            )

    def _remove_from_path_snapshot(self, path_id):
        with self._snapshot_guard():
            snapshot = getattr(self, '_path_library_snapshot', None)
            if snapshot is None:
                return
            remaining_paths = [
                dict(path or {})
                for path in (snapshot or {}).get('paths', []) or []
                if (path or {}).get('id') != path_id
            ]
            self._path_library_snapshot = self._build_snapshot_payload(
                paths=remaining_paths,
                summary=summarize_paths(remaining_paths),
            )

    def _get_canglangge_snapshot(self, force_refresh=False):
        with self._snapshot_guard():
            snapshot = getattr(self, '_canglangge_snapshot', None)
            if snapshot is None or force_refresh:
                rows = self.canglangge_candidate_service.list_candidates()
                snapshot = self._build_snapshot_payload(candidates=[dict(row or {}) for row in rows])
                self._canglangge_snapshot = snapshot
            return {
                'candidates': [dict(row or {}) for row in (snapshot or {}).get('candidates', []) or []],
                'refreshed_at': self._snapshot_refreshed_at(snapshot),
            }

    def _remove_from_canglangge_snapshot(self, actor_names):
        with self._snapshot_guard():
            snapshot = getattr(self, '_canglangge_snapshot', None)
            if snapshot is None:
                return
            target_names = {str(actor_name or '').strip() for actor_name in actor_names or [] if str(actor_name or '').strip()}
            remaining_rows = [
                dict(row or {})
                for row in (snapshot or {}).get('candidates', []) or []
                if str((row or {}).get('actor_name', '') or '').strip() not in target_names
            ]
            self._canglangge_snapshot = self._build_snapshot_payload(candidates=remaining_rows)

    def _load_actor_snapshots(self):
        snapshot_file = getattr(self, '_actor_snapshot_file', None)
        self._actor_detail_snapshots = self._load_actor_detail_snapshot_files()
        legacy_detail_snapshots = {}
        if snapshot_file is not None:
            try:
                if not Path(snapshot_file).exists():
                    payload = {}
                else:
                    payload = json.loads(Path(snapshot_file).read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                payload = {}
            if isinstance(payload, dict) and int(payload.get('version', 0) or 0) == 1:
                persisted_fingerprint = str(payload.get('filter_settings_fingerprint', '') or '').strip()
                if (
                    not persisted_fingerprint
                    or persisted_fingerprint == getattr(self, '_actor_snapshot_filter_fingerprint', '')
                ):
                    self._actor_library_snapshots = self._normalize_actor_library_snapshots(
                        payload.get('library_snapshots', {})
                    )
                    legacy_detail_snapshots = self._normalize_actor_detail_snapshots(
                        payload.get('detail_snapshots', {})
                    )
        migrated = False
        for actor_name, snapshot in legacy_detail_snapshots.items():
            if actor_name not in self._actor_detail_snapshots:
                self._actor_detail_snapshots[actor_name] = snapshot
                self._persist_single_actor_detail_snapshot_file(actor_name, snapshot)
                migrated = True
        if migrated:
            self._persist_actor_snapshots()

    def _load_actor_detail_snapshot_files(self):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return {}
        detail_dir = Path(detail_dir)
        if not detail_dir.exists():
            return {}
        snapshots = {}
        for file_path in sorted(detail_dir.glob('*.json')):
            try:
                payload = json.loads(file_path.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                continue
            actor_name = self._actor_detail_snapshot_key(unquote(file_path.stem))
            normalized = self._normalize_actor_detail_snapshot(payload)
            if actor_name and normalized is not None:
                snapshots[actor_name] = normalized
        return snapshots

    def _load_single_actor_detail_snapshot_file(self, actor_name):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return None
        normalized_name = str(actor_name or '').strip().casefold()
        if not normalized_name:
            return None
        target_file = Path(detail_dir) / self._actor_detail_snapshot_filename(normalized_name)
        try:
            if not target_file.exists():
                return None
            payload = json.loads(target_file.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return None
        normalized = self._normalize_actor_detail_snapshot(payload)
        if normalized is None:
            return None
        self._actor_detail_snapshots[normalized_name] = normalized
        return normalized

    def _persist_actor_detail_snapshot_files(self):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        detail_dir = Path(detail_dir)
        try:
            detail_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for actor_name, snapshot in (self._actor_detail_snapshots or {}).items():
            normalized_name = self._actor_detail_snapshot_key(actor_name)
            normalized_snapshot = self._normalize_actor_detail_snapshot(snapshot)
            if not normalized_name or normalized_snapshot is None:
                continue
            target_file = detail_dir / self._actor_detail_snapshot_filename(normalized_name)
            temp_file = target_file.with_suffix(target_file.suffix + '.tmp')
            try:
                temp_file.write_text(
                    json.dumps(normalized_snapshot, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_file.replace(target_file)
            except OSError:
                continue

    def _persist_single_actor_detail_snapshot_file(self, actor_name, snapshot):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        normalized_name = self._actor_detail_snapshot_key(actor_name)
        normalized_snapshot = self._normalize_actor_detail_snapshot(snapshot)
        if not normalized_name or normalized_snapshot is None:
            return
        detail_dir = Path(detail_dir)
        try:
            detail_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        target_file = detail_dir / self._actor_detail_snapshot_filename(normalized_name)
        temp_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            temp_file.write_text(
                json.dumps(normalized_snapshot, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            temp_file.replace(target_file)
        except OSError:
            return

    def _clear_actor_detail_snapshot_files(self):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        detail_dir = Path(detail_dir)
        if not detail_dir.exists():
            return
        for file_path in sorted(detail_dir.glob('*.json')):
            try:
                file_path.unlink()
            except OSError:
                continue

    def _delete_actor_detail_snapshot_file(self, normalized_actor_name):
        detail_dir = getattr(self, '_actor_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        normalized_name = self._actor_detail_snapshot_key(normalized_actor_name)
        if not normalized_name:
            return
        target_file = Path(detail_dir) / self._actor_detail_snapshot_filename(normalized_name)
        try:
            if target_file.exists():
                target_file.unlink()
        except OSError:
            return

    def _prune_actor_detail_snapshots(self, valid_keys):
        normalized_valid_keys = {
            self._actor_detail_snapshot_key(key)
            for key in (valid_keys or set())
            if self._actor_detail_snapshot_key(key)
        }
        with self._snapshot_guard():
            current_keys = list((self._actor_detail_snapshots or {}).keys())
            for actor_name in current_keys:
                if actor_name not in normalized_valid_keys:
                    self._actor_detail_snapshots.pop(actor_name, None)
                    self._delete_actor_detail_snapshot_file(actor_name)

    def _persist_actor_snapshots(self):
        snapshot_file = getattr(self, '_actor_snapshot_file', None)
        if snapshot_file is None:
            return
        payload = {
            'version': 1,
            'filter_settings_fingerprint': getattr(self, '_actor_snapshot_filter_fingerprint', ''),
            'library_snapshots': self._build_persisted_actor_library_snapshots(),
        }
        target_file = Path(snapshot_file)
        temp_snapshot_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            with self._actor_snapshot_file_guard():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_snapshot_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_snapshot_file.replace(target_file)
        except OSError:
            return

    def _refresh_actor_snapshot_filter_state(self):
        current_fingerprint = self._build_actor_snapshot_filter_fingerprint(
            self._load_actor_snapshot_filter_settings()
        )
        if current_fingerprint == getattr(self, '_actor_snapshot_filter_fingerprint', ''):
            return
        with self._snapshot_guard():
            self._actor_snapshot_filter_fingerprint = current_fingerprint
            self._actor_library_snapshots = {}
            self._actor_detail_snapshots = {}
            self._clear_actor_detail_snapshot_files()
            self._persist_actor_snapshots()

    def _invalidate_actor_snapshots(self):
        with self._snapshot_guard():
            self._actor_library_snapshots = {}
            self._actor_detail_snapshots = {}
            self._clear_actor_detail_snapshot_files()
            self._persist_actor_snapshots()

    def _invalidate_actor_ladder_snapshots(self, actor_name):
        normalized_actor_name = str(actor_name or '').strip().casefold()
        with self._snapshot_guard():
            self._actor_library_snapshots = {}
            if normalized_actor_name:
                self._actor_detail_snapshots.pop(normalized_actor_name, None)
                self._delete_actor_detail_snapshot_file(normalized_actor_name)
            self._persist_actor_snapshots()

    def _build_persisted_actor_library_snapshots(self):
        snapshots = {}
        for snapshot_key, snapshot in dict(getattr(self, '_actor_library_snapshots', {}) or {}).items():
            normalized_key = str(snapshot_key or '').strip()
            normalized_snapshot = self._normalize_actor_list_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                snapshots[normalized_key] = normalized_snapshot
        return snapshots

    def _build_persisted_actor_detail_snapshots(self):
        snapshots = {}
        for actor_name, snapshot in dict(getattr(self, '_actor_detail_snapshots', {}) or {}).items():
            normalized_key = str(actor_name or '').strip().casefold()
            normalized_snapshot = self._normalize_actor_detail_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                snapshots[normalized_key] = normalized_snapshot
        return snapshots

    def _normalize_actor_library_snapshots(self, snapshots):
        normalized_snapshots = {}
        for snapshot_key, snapshot in dict(snapshots or {}).items():
            normalized_key = str(snapshot_key or '').strip()
            normalized_snapshot = self._normalize_actor_list_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                normalized_snapshots[normalized_key] = normalized_snapshot
        return normalized_snapshots

    def _normalize_actor_detail_snapshots(self, snapshots):
        normalized_snapshots = {}
        for actor_name, snapshot in dict(snapshots or {}).items():
            normalized_key = str(actor_name or '').strip().casefold()
            normalized_snapshot = self._normalize_actor_detail_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                normalized_snapshots[normalized_key] = normalized_snapshot
        return normalized_snapshots

    def _append_snapshot_refresh_log(
        self,
        snapshot_key,
        refreshed_at,
        refresh_duration_ms,
        cache_kind='',
        refresh_duration_text='',
    ):
        log_file = getattr(self, '_snapshot_refresh_log_file', None)
        if log_file is None:
            return
        payload = {
            'logged_at': self._current_snapshot_timestamp(),
            'snapshot_key': str(snapshot_key or '').strip(),
            'cache_kind': str(cache_kind or '').strip(),
            'refreshed_at': str(refreshed_at or '').strip(),
            'refresh_duration_ms': int(refresh_duration_ms or 0),
            'refresh_duration_text': str(refresh_duration_text or '').strip()
            or self._format_refresh_duration(int(refresh_duration_ms or 0)),
        }
        try:
            target_file = Path(log_file)
            with self._snapshot_refresh_log_guard():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                with target_file.open('a', encoding='utf-8') as file_obj:
                    file_obj.write(json.dumps(payload, ensure_ascii=False) + '\n')
        except OSError:
            return

    def _load_code_prefix_snapshots(self):
        snapshot_file = getattr(self, '_code_prefix_snapshot_file', None)
        self._code_prefix_detail_snapshots = self._load_code_prefix_detail_snapshot_files()
        legacy_detail_snapshots = {}
        if snapshot_file is not None:
            try:
                if Path(snapshot_file).exists():
                    payload = json.loads(Path(snapshot_file).read_text(encoding='utf-8'))
                    if isinstance(payload, dict) and int(payload.get('version', 0) or 0) == 1:
                        persisted_fingerprint = str(payload.get('filter_settings_fingerprint', '') or '').strip()
                        if (
                            not persisted_fingerprint
                            or persisted_fingerprint == getattr(self, '_code_prefix_snapshot_filter_fingerprint', '')
                        ):
                            self._code_prefix_library_snapshots = self._normalize_code_prefix_library_snapshots(
                                payload.get('library_snapshots', {})
                            )
                            legacy_detail_snapshots = self._normalize_code_prefix_detail_snapshots(
                                payload.get('detail_snapshots', {})
                            )
            except (OSError, ValueError, TypeError):
                pass
        migrated = False
        for prefix, snapshot in legacy_detail_snapshots.items():
            if prefix not in self._code_prefix_detail_snapshots:
                self._code_prefix_detail_snapshots[prefix] = snapshot
                self._persist_single_code_prefix_detail_snapshot_file(prefix, snapshot)
                migrated = True
        if migrated:
            self._persist_code_prefix_snapshots()

    def _load_masterpiece_snapshots(self):
        snapshot_file = getattr(self, '_masterpiece_snapshot_file', None)
        if snapshot_file is None:
            return
        try:
            if not Path(snapshot_file).exists():
                return
            payload = json.loads(Path(snapshot_file).read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        if int(payload.get('version', 0) or 0) != 1:
            return
        self._masterpiece_detail_snapshots = self._normalize_masterpiece_detail_snapshots(
            payload.get('detail_snapshots', {})
        )

    def _load_video_category_snapshot(self):
        snapshot_file = getattr(self, '_video_category_snapshot_file', None)
        if snapshot_file is None:
            return
        try:
            if not Path(snapshot_file).exists():
                return
            payload = json.loads(Path(snapshot_file).read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        if int(payload.get('version', 0) or 0) != 1:
            return
        persisted_fingerprint = str(payload.get('filter_settings_fingerprint', '') or '').strip()
        if (
            persisted_fingerprint
            and persisted_fingerprint != getattr(self, '_video_category_snapshot_filter_fingerprint', '')
        ):
            return
        self._video_category_overview_snapshot = self._normalize_video_category_snapshot(
            payload.get('overview_snapshot')
        )

    def _persist_code_prefix_snapshots(self):
        snapshot_file = getattr(self, '_code_prefix_snapshot_file', None)
        if snapshot_file is None:
            return
        payload = {
            'version': 1,
            'filter_settings_fingerprint': getattr(self, '_code_prefix_snapshot_filter_fingerprint', ''),
            'library_snapshots': self._build_persisted_code_prefix_library_snapshots(),
        }
        target_file = Path(snapshot_file)
        temp_snapshot_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            with self._code_prefix_snapshot_file_guard():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_snapshot_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_snapshot_file.replace(target_file)
        except OSError:
            return

    def _load_code_prefix_detail_snapshot_files(self):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return {}
        detail_dir = Path(detail_dir)
        if not detail_dir.exists():
            return {}
        snapshots = {}
        for file_path in sorted(detail_dir.glob('*.json')):
            try:
                payload = json.loads(file_path.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                continue
            prefix = self._code_prefix_detail_snapshot_key(unquote(file_path.stem))
            normalized = self._normalize_code_prefix_detail_snapshot(payload)
            if prefix and normalized is not None:
                snapshots[prefix] = normalized
        return snapshots

    def _load_single_code_prefix_detail_snapshot_file(self, prefix):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return None
        normalized_prefix = self._code_prefix_detail_snapshot_key(prefix)
        if not normalized_prefix:
            return None
        target_file = Path(detail_dir) / self._code_prefix_detail_snapshot_filename(normalized_prefix)
        try:
            if not target_file.exists():
                return None
            payload = json.loads(target_file.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return None
        normalized = self._normalize_code_prefix_detail_snapshot(payload)
        if normalized is None:
            return None
        self._code_prefix_detail_snapshots[normalized_prefix] = normalized
        return normalized

    def _persist_code_prefix_detail_snapshot_files(self):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        detail_dir = Path(detail_dir)
        try:
            detail_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for prefix, snapshot in (self._code_prefix_detail_snapshots or {}).items():
            normalized_prefix = self._code_prefix_detail_snapshot_key(prefix)
            normalized_snapshot = self._normalize_code_prefix_detail_snapshot(snapshot)
            if not normalized_prefix or normalized_snapshot is None:
                continue
            target_file = detail_dir / self._code_prefix_detail_snapshot_filename(normalized_prefix)
            temp_file = target_file.with_suffix(target_file.suffix + '.tmp')
            try:
                temp_file.write_text(
                    json.dumps(normalized_snapshot, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_file.replace(target_file)
            except OSError:
                continue

    def _persist_single_code_prefix_detail_snapshot_file(self, prefix, snapshot):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        normalized_prefix = self._code_prefix_detail_snapshot_key(prefix)
        normalized_snapshot = self._normalize_code_prefix_detail_snapshot(snapshot)
        if not normalized_prefix or normalized_snapshot is None:
            return
        detail_dir = Path(detail_dir)
        try:
            detail_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        target_file = detail_dir / self._code_prefix_detail_snapshot_filename(normalized_prefix)
        temp_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            temp_file.write_text(
                json.dumps(normalized_snapshot, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            temp_file.replace(target_file)
        except OSError:
            return

    def _clear_code_prefix_detail_snapshot_files(self):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        detail_dir = Path(detail_dir)
        if not detail_dir.exists():
            return
        for file_path in sorted(detail_dir.glob('*.json')):
            try:
                file_path.unlink()
            except OSError:
                continue

    def _delete_code_prefix_detail_snapshot_file(self, normalized_prefix):
        detail_dir = getattr(self, '_code_prefix_detail_snapshot_dir', None)
        if detail_dir is None:
            return
        normalized_prefix = self._code_prefix_detail_snapshot_key(normalized_prefix)
        if not normalized_prefix:
            return
        target_file = Path(detail_dir) / self._code_prefix_detail_snapshot_filename(normalized_prefix)
        try:
            if target_file.exists():
                target_file.unlink()
        except OSError:
            return

    def _prune_code_prefix_detail_snapshots(self, valid_keys):
        normalized_valid_keys = {
            self._code_prefix_detail_snapshot_key(key)
            for key in (valid_keys or set())
            if self._code_prefix_detail_snapshot_key(key)
        }
        with self._snapshot_guard():
            current_keys = list((self._code_prefix_detail_snapshots or {}).keys())
            for prefix in current_keys:
                if prefix not in normalized_valid_keys:
                    self._code_prefix_detail_snapshots.pop(prefix, None)
                    self._delete_code_prefix_detail_snapshot_file(prefix)

    def _persist_masterpiece_snapshots(self):
        snapshot_file = getattr(self, '_masterpiece_snapshot_file', None)
        if snapshot_file is None:
            return
        payload = {
            'version': 1,
            'detail_snapshots': self._build_persisted_masterpiece_detail_snapshots(),
        }
        target_file = Path(snapshot_file)
        temp_snapshot_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            with self._masterpiece_snapshot_file_guard():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_snapshot_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_snapshot_file.replace(target_file)
        except OSError:
            return

    def _persist_video_category_snapshot(self):
        snapshot_file = getattr(self, '_video_category_snapshot_file', None)
        if snapshot_file is None:
            return
        payload = {
            'version': 1,
            'filter_settings_fingerprint': getattr(self, '_video_category_snapshot_filter_fingerprint', ''),
            'overview_snapshot': self._normalize_video_category_snapshot(
                getattr(self, '_video_category_overview_snapshot', None)
            ),
        }
        target_file = Path(snapshot_file)
        temp_snapshot_file = target_file.with_suffix(target_file.suffix + '.tmp')
        try:
            with self._video_category_snapshot_file_guard():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_snapshot_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                temp_snapshot_file.replace(target_file)
        except OSError:
            return

    def _invalidate_code_prefix_snapshots(self):
        with self._snapshot_guard():
            self._code_prefix_library_snapshots = {}
            self._code_prefix_detail_snapshots = {}
            self._clear_code_prefix_detail_snapshot_files()
            self._persist_code_prefix_snapshots()

    def _invalidate_masterpiece_snapshots(self):
        with self._snapshot_guard():
            self._masterpiece_detail_snapshots = {}
            self._persist_masterpiece_snapshots()

    def _invalidate_video_category_snapshot(self):
        with self._snapshot_guard():
            self._video_category_overview_snapshot = None
            self._persist_video_category_snapshot()

    def _refresh_code_prefix_snapshot_filter_state(self):
        current_fingerprint = self._build_code_prefix_snapshot_filter_fingerprint(
            self._load_code_prefix_snapshot_filter_settings()
        )
        if current_fingerprint == getattr(self, '_code_prefix_snapshot_filter_fingerprint', ''):
            return
        with self._snapshot_guard():
            self._code_prefix_snapshot_filter_fingerprint = current_fingerprint
            self._code_prefix_library_snapshots = {}
            self._code_prefix_detail_snapshots = {}
            self._clear_code_prefix_detail_snapshot_files()
            self._persist_code_prefix_snapshots()

    def _rebuild_actor_detail_snapshots(self):
        actor_rows = self.list_actors(limit=None)
        actor_names = [str(row.get('name', '') or '').strip() for row in (actor_rows.get('actors', []) or [])]
        valid_keys = {
            self._actor_detail_snapshot_key(actor_name)
            for actor_name in actor_names
            if self._actor_detail_snapshot_key(actor_name)
        }
        refreshed = 0
        failed = 0
        first_error = ''
        for actor_name in actor_names:
            if not str(actor_name or '').strip():
                continue
            try:
                self.get_actor_detail_snapshot(actor_name, force_refresh=True)
                refreshed += 1
            except Exception as exc:
                failed += 1
                if not first_error:
                    first_error = f'{actor_name}: {exc}'
        self._prune_actor_detail_snapshots(valid_keys)
        return {
            'actor_total': len(actor_names),
            'actor_refreshed': refreshed,
            'actor_failed': failed,
            'actor_first_error': first_error,
        }

    def _rebuild_code_prefix_detail_snapshots(self):
        prefix_rows = self.list_code_prefixes(limit=None)
        prefixes = [str(row.get('prefix', '') or '').strip() for row in (prefix_rows.get('prefixes', []) or [])]
        valid_keys = {
            self._code_prefix_detail_snapshot_key(prefix)
            for prefix in prefixes
            if self._code_prefix_detail_snapshot_key(prefix)
        }
        refreshed = 0
        failed = 0
        first_error = ''
        for prefix in prefixes:
            if not str(prefix or '').strip():
                continue
            try:
                self.get_code_prefix_detail_snapshot(prefix, force_refresh=True)
                refreshed += 1
            except Exception as exc:
                failed += 1
                if not first_error:
                    first_error = f'{prefix}: {exc}'
        self._prune_code_prefix_detail_snapshots(valid_keys)
        return {
            'code_prefix_total': len(prefixes),
            'code_prefix_refreshed': refreshed,
            'code_prefix_failed': failed,
            'code_prefix_first_error': first_error,
        }

    def _refresh_video_category_snapshot_filter_state(self):
        current_fingerprint = self._build_video_category_snapshot_filter_fingerprint(
            self._load_video_category_snapshot_filter_settings()
        )
        if current_fingerprint == getattr(self, '_video_category_snapshot_filter_fingerprint', ''):
            return
        with self._snapshot_guard():
            self._video_category_snapshot_filter_fingerprint = current_fingerprint
            self._video_category_overview_snapshot = None
            self._persist_video_category_snapshot()

    def _load_actor_snapshot_filter_settings(self):
        if getattr(self, 'video_filter_service', None) is None:
            return {}
        if not hasattr(self.video_filter_service, 'load_settings'):
            return {}
        return self.video_filter_service.load_settings()

    @staticmethod
    def _build_actor_snapshot_filter_fingerprint(filter_settings):
        normalized_settings = filter_settings if isinstance(filter_settings, dict) else {}
        return json.dumps(normalized_settings, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_actor_list_snapshot_key(search_text, sort_field, sort_order, limit, offset):
        return json.dumps(
            {
                'search_text': str(search_text or '').strip(),
                'sort_field': str(sort_field or '').strip(),
                'sort_order': str(sort_order or '').strip(),
                'limit': None if limit is None else int(limit),
                'offset': int(offset or 0),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _actor_detail_snapshot_key(actor_name):
        return str(actor_name or '').strip().casefold()

    @staticmethod
    def _actor_detail_snapshot_filename(actor_name):
        snapshot_key = BackendService._actor_detail_snapshot_key(actor_name)
        if not snapshot_key:
            return ''
        return quote(snapshot_key, safe='') + '.json'

    def _load_code_prefix_snapshot_filter_settings(self):
        if getattr(self, 'video_filter_service', None) is None:
            return {}
        if not hasattr(self.video_filter_service, 'load_settings'):
            return {}
        return self.video_filter_service.load_settings()

    def _load_video_category_snapshot_filter_settings(self):
        if getattr(self, 'video_filter_service', None) is None:
            return {}
        if not hasattr(self.video_filter_service, 'load_settings'):
            return {}
        return self.video_filter_service.load_settings()

    @staticmethod
    def _build_code_prefix_snapshot_filter_fingerprint(filter_settings):
        normalized_settings = filter_settings if isinstance(filter_settings, dict) else {}
        return json.dumps(normalized_settings, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_video_category_snapshot_filter_fingerprint(filter_settings):
        normalized_settings = filter_settings if isinstance(filter_settings, dict) else {}
        return json.dumps(normalized_settings, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_code_prefix_list_snapshot_key(search_text, sort_field, sort_order, limit, offset):
        return json.dumps(
            {
                'search_text': str(search_text or '').strip(),
                'sort_field': str(sort_field or '').strip(),
                'sort_order': str(sort_order or '').strip(),
                'limit': None if limit is None else int(limit),
                'offset': int(offset or 0),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _code_prefix_detail_snapshot_key(prefix):
        return str(prefix or '').strip().upper()

    @staticmethod
    def _code_prefix_detail_snapshot_filename(prefix):
        snapshot_key = BackendService._code_prefix_detail_snapshot_key(prefix)
        if not snapshot_key:
            return ''
        return quote(snapshot_key, safe='') + '.json'

    @staticmethod
    def _clone_actor_list_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'actors': [dict(row or {}) for row in current.get('actors', []) or []],
            'total_count': int(current.get('total_count', 0) or 0),
            'offset': int(current.get('offset', 0) or 0),
            'limit': current.get('limit'),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    @staticmethod
    def _clone_actor_detail_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'actor': dict(current.get('actor', {}) or {}),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    @staticmethod
    def _clone_code_prefix_list_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'prefixes': [dict(row or {}) for row in current.get('prefixes', []) or []],
            'total_count': int(current.get('total_count', 0) or 0),
            'offset': int(current.get('offset', 0) or 0),
            'limit': current.get('limit'),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    @staticmethod
    def _clone_code_prefix_detail_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'prefix_detail': dict(current.get('prefix_detail', {}) or {}),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    @staticmethod
    def _clone_masterpiece_detail_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'detail': dict(current.get('detail', {}) or {}),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    @staticmethod
    def _clone_video_category_snapshot(snapshot):
        current = dict(snapshot or {})
        return {
            'videos': [dict(row or {}) for row in current.get('videos', []) or []],
            'staged_count': int(current.get('staged_count', 0) or 0),
            'refreshed_at': str(current.get('refreshed_at', '') or '').strip(),
            'refresh_duration_ms': int(current.get('refresh_duration_ms', 0) or 0),
            'refresh_duration_text': str(current.get('refresh_duration_text', '') or '').strip(),
        }

    def _build_persisted_code_prefix_library_snapshots(self):
        snapshots = {}
        for snapshot_key, snapshot in dict(getattr(self, '_code_prefix_library_snapshots', {}) or {}).items():
            normalized_key = str(snapshot_key or '').strip()
            normalized_snapshot = self._normalize_code_prefix_list_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                snapshots[normalized_key] = normalized_snapshot
        return snapshots

    def _build_persisted_code_prefix_detail_snapshots(self):
        snapshots = {}
        for prefix, snapshot in dict(getattr(self, '_code_prefix_detail_snapshots', {}) or {}).items():
            normalized_prefix = str(prefix or '').strip().upper()
            normalized_snapshot = self._normalize_code_prefix_detail_snapshot(snapshot)
            if normalized_prefix and normalized_snapshot is not None:
                snapshots[normalized_prefix] = normalized_snapshot
        return snapshots

    def _build_persisted_masterpiece_detail_snapshots(self):
        snapshots = {}
        for code, snapshot in dict(getattr(self, '_masterpiece_detail_snapshots', {}) or {}).items():
            normalized_code = str(code or '').strip().upper()
            normalized_snapshot = self._normalize_masterpiece_detail_snapshot(snapshot)
            if normalized_code and normalized_snapshot is not None:
                snapshots[normalized_code] = normalized_snapshot
        return snapshots

    def _normalize_code_prefix_library_snapshots(self, snapshots):
        normalized_snapshots = {}
        for snapshot_key, snapshot in dict(snapshots or {}).items():
            normalized_key = str(snapshot_key or '').strip()
            normalized_snapshot = self._normalize_code_prefix_list_snapshot(snapshot)
            if normalized_key and normalized_snapshot is not None:
                normalized_snapshots[normalized_key] = normalized_snapshot
        return normalized_snapshots

    def _normalize_code_prefix_detail_snapshots(self, snapshots):
        normalized_snapshots = {}
        for prefix, snapshot in dict(snapshots or {}).items():
            normalized_prefix = str(prefix or '').strip().upper()
            normalized_snapshot = self._normalize_code_prefix_detail_snapshot(snapshot)
            if normalized_prefix and normalized_snapshot is not None:
                normalized_snapshots[normalized_prefix] = normalized_snapshot
        return normalized_snapshots

    def _normalize_masterpiece_detail_snapshots(self, snapshots):
        normalized_snapshots = {}
        for code, snapshot in dict(snapshots or {}).items():
            normalized_code = str(code or '').strip().upper()
            normalized_snapshot = self._normalize_masterpiece_detail_snapshot(snapshot)
            if normalized_code and normalized_snapshot is not None:
                normalized_snapshots[normalized_code] = normalized_snapshot
        return normalized_snapshots

    @staticmethod
    def _normalize_actor_list_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        actors = snapshot.get('actors', [])
        if not refreshed_at or not isinstance(actors, list):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'actors': [dict(row or {}) for row in actors],
            'total_count': int(snapshot.get('total_count', 0) or 0),
            'offset': int(snapshot.get('offset', 0) or 0),
            'limit': snapshot.get('limit'),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _normalize_actor_detail_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        actor = snapshot.get('actor')
        if not refreshed_at or not isinstance(actor, dict):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'actor': dict(actor or {}),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _normalize_code_prefix_list_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        if not refreshed_at:
            return None
        prefixes = snapshot.get('prefixes', [])
        if not isinstance(prefixes, list):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'prefixes': [dict(row or {}) for row in prefixes],
            'total_count': int(snapshot.get('total_count', 0) or 0),
            'offset': int(snapshot.get('offset', 0) or 0),
            'limit': snapshot.get('limit'),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _normalize_code_prefix_detail_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        prefix_detail = snapshot.get('prefix_detail')
        if not refreshed_at or not isinstance(prefix_detail, dict):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'prefix_detail': dict(prefix_detail or {}),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _normalize_masterpiece_detail_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        detail = snapshot.get('detail')
        if not refreshed_at or not isinstance(detail, dict):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'detail': dict(detail or {}),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _normalize_video_category_snapshot(snapshot):
        if not isinstance(snapshot, dict):
            return None
        refreshed_at = str(snapshot.get('refreshed_at', '') or '').strip()
        videos = snapshot.get('videos', [])
        if not refreshed_at or not isinstance(videos, list):
            return None
        refresh_duration_ms = int(snapshot.get('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(snapshot.get('refresh_duration_text', '') or '').strip()
        return {
            'videos': [dict(row or {}) for row in videos],
            'staged_count': int(snapshot.get('staged_count', 0) or 0),
            'refreshed_at': refreshed_at,
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or BackendService._format_refresh_duration(refresh_duration_ms),
        }

    def _actor_snapshot_file_guard(self):
        return getattr(self, '_actor_snapshot_file_lock', None) or nullcontext()

    def _code_prefix_snapshot_file_guard(self):
        return getattr(self, '_code_prefix_snapshot_file_lock', None) or nullcontext()

    def _masterpiece_snapshot_file_guard(self):
        return getattr(self, '_masterpiece_snapshot_file_lock', None) or nullcontext()

    def _video_category_snapshot_file_guard(self):
        return getattr(self, '_video_category_snapshot_file_lock', None) or nullcontext()

    def _snapshot_refresh_log_guard(self):
        return getattr(self, '_snapshot_refresh_log_lock', None) or nullcontext()

    def _snapshot_guard(self):
        return getattr(self, '_snapshot_lock', None) or nullcontext()

    def _build_snapshot_payload(self, **fields):
        refresh_duration_ms = int(fields.pop('refresh_duration_ms', 0) or 0)
        refresh_duration_text = str(fields.pop('refresh_duration_text', '') or '').strip()
        return {
            **fields,
            'refreshed_at': self._current_snapshot_timestamp(),
            'refresh_duration_ms': refresh_duration_ms,
            'refresh_duration_text': refresh_duration_text or self._format_refresh_duration(refresh_duration_ms),
        }

    @staticmethod
    def _snapshot_refreshed_at(snapshot):
        return str((snapshot or {}).get('refreshed_at', '') or '').strip()

    @staticmethod
    def _current_snapshot_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _ensure_snapshot_runtime_dir():
        try:
            SNAPSHOT_REFRESH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

    @staticmethod
    def _migrate_legacy_snapshot_file(legacy_file, target_file):
        legacy_path = Path(legacy_file)
        target_path = Path(target_file)
        try:
            if target_path.exists() or not legacy_path.exists():
                return
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(legacy_path.read_text(encoding='utf-8'), encoding='utf-8')
        except OSError:
            return

    @staticmethod
    def _build_refresh_duration_ms(started_at):
        return max(0, int(round((perf_counter() - float(started_at or 0.0)) * 1000)))

    @staticmethod
    def _format_refresh_duration(duration_ms):
        total_seconds = max(0, int(round(int(duration_ms or 0) / 1000.0)))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours}小时{minutes}分{seconds}秒'
        if minutes > 0:
            return f'{minutes}分{seconds}秒'
        return f'{seconds}秒'

    @staticmethod
    def _clone_ladder_board(board):
        board = dict(board or {})
        return {
            **board,
            'candidates': [dict(row or {}) for row in board.get('candidates', []) or []],
            'selected': [dict(row or {}) for row in board.get('selected', []) or []],
        }

    @staticmethod
    def _format_refresh_duration(duration_ms):
        total_seconds = max(0, int(round(int(duration_ms or 0) / 1000.0)))
        return f'{total_seconds}\u79d2'

    def enrich_videos(
        self,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        target_type=None,
        source_key=None,
        batch_mode=False,
    ):
        self._begin_enrichment_task('single')
        logger = TaskTraceLogger(
            'single',
            self._build_single_task_key(target_type, source_key),
            self._build_single_task_label(target_type, source_key),
        )
        active_filter_settings = self.video_filter_service.load_settings()
        try:
            enrichment_service = LibraryEnrichmentService(
                self.db,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                should_stop=self.enrichment_task_state.cancel_event.is_set,
                progress_tracker=self.enrichment_progress,
                logger=logger,
                video_candidate_filter=self.video_filter_service.build_pre_enrichment_filter(
                    settings=active_filter_settings
                ),
                video_filter_settings=active_filter_settings,
            )
            if target_type == ACTOR_LIBRARY_TARGET:
                self.actor_library_sync_service.sync_from_video_library()

            result = enrichment_service.run(target_type, limit, source_key=source_key, batch_mode=batch_mode)
            result['log_path'] = str(logger.log_path)

            if (not target_type or target_type == VIDEO_LIBRARY_TARGET) and result.get('processed_count', 0) > 0:
                self.actor_library_sync_service.sync_from_video_library()

            return result
        except Exception:
            self.enrichment_progress.finish(message='补全任务异常结束。', stopped=True)
            logger.log('ERROR', '单任务补全异常结束', target_type=target_type or '', source_key=source_key or '')
            raise
        finally:
            self._end_enrichment_task()

    def enrich_combo(
        self,
        combo_key,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        combo_task_settings=None,
        batch_mode=False,
    ):
        normalized_combo_key = normalize_combo_key(combo_key)
        combo_label = get_combo_label(normalized_combo_key)
        self._begin_enrichment_task('combo')
        logger = ComboTaskLogger(normalized_combo_key, combo_label)
        try:
            combo_service = ComboEnrichmentService(
                self.db,
                self.combo_progress,
                logger,
                should_stop=self.enrichment_task_state.cancel_event.is_set,
            )
            result = combo_service.run(
                normalized_combo_key,
                limit,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                combo_task_settings=combo_task_settings,
                batch_mode=batch_mode,
            )
            result['log_path'] = str(logger.log_path)
            return result
        except Exception:
            self.combo_progress.finish(message='组合任务异常结束。', stopped=True)
            raise
        finally:
            self._end_enrichment_task()

    def cancel_enrichment(self):
        return self.enrichment_task_state.request_cancel(self._set_cancel_message)

    def auto_login(self):
        return AutoLoginService().run()

    def reset_browser_profile(self):
        return reset_avfan_browser_profile()

    def sync_library_statuses(self):
        self.ensure_database_loaded()
        if self.enrichment_task_state.is_running:
            raise RuntimeError('当前有补全任务正在运行，请稍后再执行状态同步。')
        return self.library_status_sync_service.sync()

    def _begin_enrichment_task(self, task_kind):
        self.enrichment_task_state.begin(
            task_kind,
            reset_progress=lambda: (
                self.enrichment_progress.reset(),
                self.combo_progress.reset(),
            ),
        )

    def _end_enrichment_task(self):
        self.enrichment_task_state.end()

    def _set_cancel_message(self, task_kind):
        if task_kind == 'combo':
            self.combo_progress.set_message('已请求停止组合任务，等待当前条目处理完成。')
            return
        self.enrichment_progress.set_message('已请求停止补全任务，等待当前条目处理完成。')

    @staticmethod
    def _build_single_task_key(target_type, source_key):
        target_text = str(target_type or VIDEO_LIBRARY_TARGET).strip() or VIDEO_LIBRARY_TARGET
        source_text = str(source_key or '').strip()
        if not source_text:
            return target_text
        return f'{target_text}_{source_text}'

    @staticmethod
    def _build_single_task_label(target_type, source_key):
        target_text = str(target_type or VIDEO_LIBRARY_TARGET).strip() or VIDEO_LIBRARY_TARGET
        source_text = str(source_key or '').strip()
        if not source_text:
            return f'单任务 / {target_text}'
        return f'单任务 / {target_text} / {source_text}'
