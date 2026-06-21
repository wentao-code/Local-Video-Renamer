import re
from datetime import datetime
from threading import Lock

from app.core.actor_data_analysis import ACTOR_ANALYSIS_METRIC_MAP
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    BINGHUO_ACTOR_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.javtxt_video_state import summarize_javtxt_movies
from app.core.video_code import standardize_video_code
from app.services.library import CodePrefixLibrary, build_merged_movie_snapshot
from app.services.video import VideoFilterService


VIDEO_LIBRARY_LABEL = '\u89c6\u9891\u5e93'
CODE_PREFIX_LIBRARY_LABEL = '\u756a\u53f7\u5e93'
ACTOR_LIBRARY_LABEL = '\u6f14\u5458\u5e93'
COMPLETED_LABEL = '\u5df2\u5b8c\u6210'
COMPLETED_VIDEO_LABEL = '\u5df2\u5b8c\u6210\u89c6\u9891'
PENDING_VIDEO_LABEL = '\u5f85\u8865\u5168\u89c6\u9891'
NO_SEARCH_LABEL = '\u65e0\u7ed3\u679c'
NO_DETAIL_LABEL = '\u65e0\u8be6\u60c5'
MISSING_AGE_LABEL = '\u65e0\u5e74\u9f84'
MISSING_MEASUREMENTS_LABEL = '\u65e0\u4e09\u56f4'
MISSING_HEIGHT_LABEL = '\u65e0\u8eab\u9ad8'


class DataCenterService:
    def __init__(self, database, video_filter_service=None):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)
        self.video_filter_service = video_filter_service or VideoFilterService()
        self._summary_cache = None
        self._summary_cache_refreshed_at = ''
        self._summary_cache_lock = Lock()
        self._analysis_cache = {}
        self._analysis_cache_lock = Lock()

    def get_summary(self, force_refresh=False):
        return self.get_summary_snapshot(force_refresh=force_refresh)['summary']

    def get_summary_snapshot(self, force_refresh=False):
        with self._summary_cache_lock:
            if self._summary_cache is not None and not force_refresh:
                return {
                    'summary': self._summary_cache,
                    'refreshed_at': self._summary_cache_refreshed_at,
                }

            filter_settings = self._load_filter_settings()
            summary = self._build_summary(filter_settings=filter_settings)
            self._summary_cache = summary
            self._summary_cache_refreshed_at = self._current_cache_timestamp()
            return {
                'summary': summary,
                'refreshed_at': self._summary_cache_refreshed_at,
            }

    def get_actor_metric_analysis(self, metric_key, force_refresh=False):
        return self.get_actor_metric_analysis_snapshot(metric_key, force_refresh=force_refresh)['analysis']

    def get_actor_metric_analysis_snapshot(self, metric_key, force_refresh=False):
        config = self._get_actor_metric_config(metric_key)
        metric_key = config['key']
        with self._analysis_cache_lock:
            cached = self._analysis_cache.get(metric_key)
            if cached is not None and not force_refresh:
                return dict(cached)

            payload = {
                'analysis': self._build_actor_metric_analysis(config),
                'refreshed_at': self._current_cache_timestamp(),
            }
            self._analysis_cache[metric_key] = payload
            return dict(payload)

    def _build_summary(self, filter_settings=None):
        return {
            'video_library': {
                'label': VIDEO_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_video_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_video_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
            'code_prefix_library': {
                'label': CODE_PREFIX_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_code_prefix_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
            'actor_library': {
                'label': ACTOR_LIBRARY_LABEL,
                'sources': {
                    AVFAN_VIDEO_SOURCE: self._build_actor_source_summary(
                        AVFAN_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    JAVTXT_VIDEO_SOURCE: self._build_actor_source_summary(
                        JAVTXT_VIDEO_SOURCE,
                        filter_settings=filter_settings,
                    ),
                    BINGHUO_ACTOR_SOURCE: self._build_actor_source_summary(
                        BINGHUO_ACTOR_SOURCE,
                        filter_settings=filter_settings,
                    ),
                },
            },
        }

    def _build_video_source_summary(self, source_key, filter_settings=None):
        label = self._build_source_label(VIDEO_LIBRARY_LABEL, source_key)
        visible_rows = self._list_visible_video_summary_rows(filter_settings=filter_settings)
        if source_key == JAVTXT_VIDEO_SOURCE:
            summary = summarize_javtxt_movies(visible_rows)
            return {
                'label': label,
                'total_count': summary['total_count'],
                'enriched_count': summary['enriched_count'],
                'success_count': summary['success_count'],
                'pending_count': summary['pending_count'],
                'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
                'count_label': COMPLETED_LABEL,
                'failed_count': summary['failed_count'],
                'no_search_count': summary['no_search_count'],
                'no_detail_count': summary['no_detail_count'],
                'list_kind': 'video',
                'issue_groups': self._build_javtxt_video_issue_groups(visible_rows),
            }
        return self._build_video_status_summary(label, visible_rows, 'avfan_enrichment_status')

    def _build_video_status_summary(self, label, rows, status_field):
        statuses = [str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS for row in rows or []]
        summary = self._build_status_summary(label, statuses)
        summary['count_label'] = COMPLETED_LABEL
        summary['list_kind'] = 'video'
        summary['issue_groups'] = self._build_status_issue_groups(
            rows,
            lambda row: self._build_video_issue_item(row),
            lambda row: str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS,
        )
        return summary

    def _build_code_prefix_source_summary(self, source_key, filter_settings=None):
        if source_key == JAVTXT_VIDEO_SOURCE:
            prefixes = [
                str(row.get('prefix', '')).strip().upper()
                for row in self.code_prefix_library.list_prefixes()
                if str(row.get('prefix', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key),
                self.database.list_code_prefix_movies_by_prefixes(prefixes),
                filter_settings=filter_settings,
                list_kind='video',
            )

        records = self.database.list_code_prefix_enrichment_records()
        prefix_rows = [row for row in self.code_prefix_library.list_prefixes() if row.get('prefix')]
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in prefix_rows
        ]
        summary = self._build_status_summary(self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key), statuses)
        summary['list_kind'] = 'code_prefix'
        summary['issue_groups'] = self._build_status_issue_groups(
            prefix_rows,
            lambda row: self._build_code_prefix_issue_item(row.get('prefix', '')),
            lambda row: self._get_source_status(records.get(row.get('prefix', ''), {}), source_key),
        )
        return summary

    def _build_actor_source_summary(self, source_key, filter_settings=None):
        if source_key == BINGHUO_ACTOR_SOURCE:
            return self._build_actor_binghuo_source_summary()
        if source_key == JAVTXT_VIDEO_SOURCE:
            actor_names = [
                str(row.get('name', '')).strip()
                for row in self.database.list_actors()
                if str(row.get('name', '')).strip()
            ]
            return self._build_javtxt_library_video_summary(
                self._build_source_label(ACTOR_LIBRARY_LABEL, source_key),
                self.database.list_actor_movies_by_names(actor_names),
                filter_settings=filter_settings,
                list_kind='video',
            )

        records = self.database.list_actor_enrichment_records()
        actor_rows = [row for row in self.database.list_actors() if str(row.get('name', '')).strip()]
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in actor_rows
        ]
        summary = self._build_status_summary(self._build_source_label(ACTOR_LIBRARY_LABEL, source_key), statuses)
        summary['list_kind'] = 'actor'
        summary['issue_groups'] = self._build_status_issue_groups(
            actor_rows,
            lambda row: self._build_actor_issue_item(row.get('name', '')),
            lambda row: self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key),
        )
        return summary

    def _build_actor_binghuo_source_summary(self):
        records = self.database.list_actor_enrichment_records()
        total_count = 0
        success_count = 0
        failed_count = 0
        no_search_count = 0
        no_detail_count = 0
        missing_age_count = 0
        missing_measurements_count = 0
        missing_height_count = 0
        no_search_items = []
        missing_age_items = []
        missing_measurements_items = []
        missing_height_items = []

        for row in self.database.list_actors():
            actor_name = str((row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            total_count += 1
            record = records.get(actor_name, {})
            status = str((record or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            if status == NO_SEARCH_RESULTS_STATUS:
                no_search_count += 1
                no_search_items.append(self._build_actor_issue_item(actor_name))
            elif status == NO_VIDEO_DETAIL_STATUS or self._is_incomplete_binghuo_profile(record):
                no_detail_count += 1
                if self._is_missing_binghuo_age(record):
                    missing_age_count += 1
                    missing_age_items.append(self._build_actor_issue_item(actor_name))
                if self._is_missing_binghuo_measurements(record):
                    missing_measurements_count += 1
                    missing_measurements_items.append(self._build_actor_issue_item(actor_name))
                if self._is_missing_binghuo_height(record):
                    missing_height_count += 1
                    missing_height_items.append(self._build_actor_issue_item(actor_name))
            elif self._is_complete_binghuo_profile(record):
                success_count += 1
            elif status == FAILED_STATUS:
                failed_count += 1

        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': self._build_source_label(ACTOR_LIBRARY_LABEL, BINGHUO_ACTOR_SOURCE),
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'missing_age_count': missing_age_count,
            'missing_measurements_count': missing_measurements_count,
            'missing_height_count': missing_height_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': COMPLETED_LABEL,
            'list_kind': 'actor',
            'issue_groups': self._compact_issue_groups(
                [
                    self._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                    self._build_issue_group('missing_age', MISSING_AGE_LABEL, missing_age_items),
                    self._build_issue_group(
                        'missing_measurements',
                        MISSING_MEASUREMENTS_LABEL,
                        missing_measurements_items,
                    ),
                    self._build_issue_group('missing_height', MISSING_HEIGHT_LABEL, missing_height_items),
                ]
            ),
        }

    def _build_status_summary(self, label, statuses):
        total_count = len(statuses)
        success_count = sum(1 for status in statuses if status == ENRICHED_STATUS)
        failed_count = sum(1 for status in statuses if status == FAILED_STATUS)
        no_search_count = sum(1 for status in statuses if status == NO_SEARCH_RESULTS_STATUS)
        no_detail_count = sum(1 for status in statuses if status == NO_VIDEO_DETAIL_STATUS)
        enriched_count = success_count + no_search_count + no_detail_count
        pending_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'label': label,
            'total_count': total_count,
            'enriched_count': enriched_count,
            'success_count': success_count,
            'pending_count': pending_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'progress_percent': _build_progress_percent(enriched_count, total_count),
            'count_label': COMPLETED_LABEL,
        }

    def _build_javtxt_library_video_summary(self, label, movies_by_group, filter_settings=None, list_kind='video'):
        visible_movies = self._filter_visible_movies(
            [
                movie
                for movies in (movies_by_group or {}).values()
                for movie in (movies or [])
            ],
            filter_settings=filter_settings,
        )
        merged_movies = self._merge_movies_by_code(visible_movies)
        cache_rows = self.database.get_javtxt_actor_cache_by_codes(
            [standardize_video_code((movie or {}).get('code', '')) for movie in merged_movies]
        )
        summary = summarize_javtxt_movies(merged_movies, cache_rows=cache_rows)
        return {
            'label': label,
            'total_count': summary['total_count'],
            'enriched_count': summary['enriched_count'],
            'success_count': summary['success_count'],
            'pending_count': summary['pending_count'],
            'failed_count': summary['failed_count'],
            'no_search_count': summary['no_search_count'],
            'no_detail_count': summary['no_detail_count'],
            'progress_percent': _build_progress_percent(summary['enriched_count'], summary['total_count']),
            'count_label': COMPLETED_VIDEO_LABEL,
            'pending_label': PENDING_VIDEO_LABEL,
            'list_kind': list_kind,
            'issue_groups': self._build_javtxt_issue_groups_by_kind(
                movies_by_group,
                filter_settings=filter_settings,
                list_kind=list_kind,
            ),
        }

    def _load_filter_settings(self):
        if self.video_filter_service is None:
            return None
        return self.video_filter_service.load_settings()

    def _build_actor_metric_analysis(self, config):
        distribution_counts = {}
        ranking_rows = []
        unknown_count = 0
        enrichment_records = self.database.list_actor_enrichment_records()

        for actor_row in self.database.list_actors():
            actor_name = str((actor_row or {}).get('name', '') or '').strip()
            if not actor_name:
                continue
            numeric_value, display_value = self._resolve_actor_metric_value(
                config,
                actor_row,
                enrichment_records.get(actor_name, {}),
            )
            if numeric_value is None:
                unknown_count += 1
                continue
            distribution_counts[display_value] = distribution_counts.get(display_value, 0) + 1
            ranking_rows.append(
                {
                    'actor_name': actor_name,
                    'display_value': display_value,
                    'numeric_value': numeric_value,
                }
            )

        distribution_rows = [
            {'label': label, 'count': count}
            for label, count in sorted(
                distribution_counts.items(),
                key=lambda item: (-self._parse_metric_number(item[0]), item[0]),
            )
        ]
        if unknown_count > 0:
            distribution_rows.append({'label': '无数据', 'count': unknown_count})

        ranking_rows.sort(key=lambda item: (-item['numeric_value'], item['actor_name']))
        return {
            'metric_key': config['key'],
            'distribution_rows': distribution_rows,
            'ranking_rows': ranking_rows[:50],
        }

    @staticmethod
    def _resolve_actor_metric_value(config, actor_row, enrichment_record):
        source_name = str(config.get('source', '') or '').strip()
        field_name = str(config.get('field', '') or '').strip()
        suffix = str(config.get('suffix', '') or '')
        if source_name == 'enrichment':
            raw_value = str((enrichment_record or {}).get(field_name, '') or '').strip()
        else:
            raw_value = str(
                (actor_row or {}).get(f'raw_{field_name}', (actor_row or {}).get(field_name, '')) or ''
            ).strip()
        numeric_value = DataCenterService._parse_metric_number(raw_value)
        if numeric_value is None:
            return None, ''
        return numeric_value, f'{numeric_value}{suffix}'

    @staticmethod
    def _parse_metric_number(value):
        match = re.search(r'\d+', str(value or '').strip())
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _has_binghuo_physical_data(record):
        current = dict(record or {})
        return any(
            str(current.get(field_name, '') or '').strip()
            for field_name in ('binghuo_height', 'binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @staticmethod
    def _is_missing_binghuo_age(record):
        current = dict(record or {})
        return not str(current.get('binghuo_age', '') or '').strip()

    @staticmethod
    def _is_missing_binghuo_height(record):
        current = dict(record or {})
        return not str(current.get('binghuo_height', '') or '').strip()

    @staticmethod
    def _is_missing_binghuo_measurements(record):
        current = dict(record or {})
        return any(
            not str(current.get(field_name, '') or '').strip()
            for field_name in ('binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @classmethod
    def _is_complete_binghuo_profile(cls, record):
        current = dict(record or {})
        birthday = str(current.get('binghuo_birthday', '') or '').strip()
        return bool(birthday) and cls._has_binghuo_physical_data(current)

    @classmethod
    def _is_incomplete_binghuo_profile(cls, record):
        current = dict(record or {})
        has_any_profile_data = any(
            str(current.get(field_name, '') or '').strip()
            for field_name in (
                'binghuo_birthday',
                'binghuo_age',
                'binghuo_height',
                'binghuo_bust',
                'binghuo_waist',
                'binghuo_hip',
            )
        )
        return has_any_profile_data and not cls._is_complete_binghuo_profile(current)

    @staticmethod
    def _current_cache_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _get_actor_metric_config(metric_key):
        normalized_key = str(metric_key or '').strip()
        config = ACTOR_ANALYSIS_METRIC_MAP.get(normalized_key)
        if config is None:
            raise ValueError(f'Unknown actor analysis metric: {normalized_key}')
        return dict(config)

    def _list_visible_video_summary_rows(self, filter_settings=None):
        return self._filter_visible_movies(
            self.database.list_video_summary_rows(),
            filter_settings=filter_settings,
        )

    def _filter_visible_movies(self, rows, filter_settings=None):
        if self.video_filter_service is None:
            return list(rows or [])
        return self.video_filter_service.filter_video_rows(rows, settings=filter_settings)

    @staticmethod
    def _build_source_label(library_label, source_key):
        return f'{library_label} \u00b7 {get_video_enrichment_source_label(source_key)}'

    @staticmethod
    def _merge_movies_by_code(movies):
        movies_by_code = {}
        for movie in movies or []:
            normalized_code = standardize_video_code((movie or {}).get('code', ''))
            if not normalized_code:
                continue
            movies_by_code.setdefault(normalized_code, []).append(dict(movie or {}))

        merged_movies = []
        for normalized_code, rows in movies_by_code.items():
            merged_snapshot = build_merged_movie_snapshot(normalized_code, rows)
            if merged_snapshot:
                merged_movies.append(merged_snapshot)
            else:
                merged_movies.append(dict(rows[0] or {}))
        return merged_movies

    @staticmethod
    def _get_source_status(record, source_key):
        key = 'javtxt_enrichment_status' if source_key == JAVTXT_VIDEO_SOURCE else 'avfan_enrichment_status'
        return str((record or {}).get(key, '') or '').strip() or UNENRICHED_STATUS

    @staticmethod
    def _build_issue_group(key, label, items):
        normalized_items = [dict(item or {}) for item in items or [] if dict(item or {})]
        if not normalized_items:
            return {}
        return {
            'key': str(key or '').strip(),
            'label': str(label or '').strip(),
            'items': normalized_items,
        }

    @classmethod
    def _compact_issue_groups(cls, groups):
        return [group for group in (groups or []) if dict(group or {}).get('items')]

    @staticmethod
    def _build_video_issue_item(row):
        current = dict(row or {})
        return {
            'code': str(current.get('code', '') or '').strip(),
            'title': str(current.get('title', '') or '').strip(),
            'author': str(
                current.get('author', '')
                or current.get('local_author', '')
                or current.get('author_raw', '')
                or ''
            ).strip(),
        }

    @staticmethod
    def _build_code_prefix_issue_item(prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return {}
        return {'prefix': normalized_prefix}

    @staticmethod
    def _build_actor_issue_item(actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return {}
        return {'name': normalized_name}

    @classmethod
    def _build_status_issue_groups(cls, rows, item_builder, status_builder):
        no_search_items = []
        no_detail_items = []
        for row in rows or []:
            status = str(status_builder(row) or '').strip() or UNENRICHED_STATUS
            item = dict(item_builder(row) or {})
            if not item:
                continue
            if status == NO_SEARCH_RESULTS_STATUS:
                no_search_items.append(item)
            elif status == NO_VIDEO_DETAIL_STATUS:
                no_detail_items.append(item)
        return cls._compact_issue_groups(
            [
                cls._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                cls._build_issue_group('no_detail', NO_DETAIL_LABEL, no_detail_items),
            ]
        )

    def _build_javtxt_video_issue_groups(self, movies, filter_settings=None):
        issue_items = {
            'no_search': [],
            'no_detail': [],
        }
        local_rows_by_code = {
            standardize_video_code((row or {}).get('code', '')): dict(row or {})
            for row in self._list_visible_video_summary_rows(filter_settings=filter_settings)
            if standardize_video_code((row or {}).get('code', ''))
        }
        visible_movies = self._filter_visible_movies(movies or [], filter_settings=filter_settings)
        for movie in self._merge_movies_by_code(visible_movies):
            if not self._is_javtxt_issue_movie(movie):
                continue
            issue_key = self._resolve_javtxt_issue_key(movie)
            if not issue_key:
                continue
            issue_items[issue_key].append(
                self._build_video_issue_item(
                    self._merge_issue_movie_with_local_row(
                        movie,
                        local_rows_by_code.get(standardize_video_code((movie or {}).get('code', '')), {}),
                    )
                )
            )
        return self._compact_issue_groups(
            [
                self._build_issue_group('no_search', NO_SEARCH_LABEL, issue_items['no_search']),
                self._build_issue_group('no_detail', NO_DETAIL_LABEL, issue_items['no_detail']),
            ]
        )

    def _build_javtxt_issue_groups_by_kind(self, movies_by_group, filter_settings=None, list_kind='video'):
        if str(list_kind or '').strip() == 'video':
            flat_movies = [
                movie
                for movies in (movies_by_group or {}).values()
                for movie in (movies or [])
            ]
            return self._build_javtxt_video_issue_groups(flat_movies, filter_settings=filter_settings)

        no_search_items = []
        no_detail_items = []
        for group_key, movies in (movies_by_group or {}).items():
            visible_movies = self._filter_visible_movies(movies or [], filter_settings=filter_settings)
            if not visible_movies:
                continue
            has_no_search = False
            has_no_detail = False
            for movie in visible_movies:
                if not self._is_javtxt_issue_movie(movie):
                    continue
                issue_key = self._resolve_javtxt_issue_key(movie)
                if issue_key == 'no_search':
                    has_no_search = True
                elif issue_key == 'no_detail':
                    has_no_detail = True
            if str(list_kind or '').strip() == 'code_prefix':
                item = self._build_code_prefix_issue_item(group_key)
            else:
                item = self._build_actor_issue_item(group_key)
            if not item:
                continue
            if has_no_search:
                no_search_items.append(item)
            if has_no_detail:
                no_detail_items.append(item)

        return self._compact_issue_groups(
            [
                self._build_issue_group('no_search', NO_SEARCH_LABEL, no_search_items),
                self._build_issue_group('no_detail', NO_DETAIL_LABEL, no_detail_items),
            ]
        )

    @staticmethod
    def _is_javtxt_issue_movie(movie):
        if not summarize_javtxt_movies([movie]).get('total_count', 0):
            return False
        status = str((movie or {}).get('javtxt_enrichment_status', '') or '').strip()
        return status in (NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS)

    @staticmethod
    def _resolve_javtxt_issue_key(movie):
        status = str((movie or {}).get('javtxt_enrichment_status', '') or '').strip()
        if status == NO_SEARCH_RESULTS_STATUS:
            return 'no_search'
        if status == NO_VIDEO_DETAIL_STATUS:
            return 'no_detail'
        return ''

    @staticmethod
    def _merge_issue_movie_with_local_row(movie, local_row):
        merged_movie = dict(movie or {})
        current_local_row = dict(local_row or {})
        for field_name in ('title', 'author', 'author_raw', 'local_author'):
            if str(merged_movie.get(field_name, '') or '').strip():
                continue
            merged_movie[field_name] = current_local_row.get(field_name, '')
        return merged_movie


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
