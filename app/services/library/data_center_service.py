from threading import Lock
from time import monotonic

from app.core.enrichment_sources import AVFAN_VIDEO_SOURCE, JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
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


class DataCenterService:
    SUMMARY_CACHE_TTL_SECONDS = 5.0

    def __init__(self, database, video_filter_service=None):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)
        self.video_filter_service = video_filter_service or VideoFilterService()
        self._summary_cache = None
        self._summary_cache_filter_settings = None
        self._summary_cache_expires_at = 0.0
        self._summary_cache_lock = Lock()

    def get_summary(self):
        filter_settings = self._load_filter_settings()
        now = monotonic()
        if self._is_cache_valid(now, filter_settings):
            return self._summary_cache

        with self._summary_cache_lock:
            filter_settings = self._load_filter_settings()
            now = monotonic()
            if self._is_cache_valid(now, filter_settings):
                return self._summary_cache

            summary = self._build_summary(filter_settings=filter_settings)
            self._summary_cache = summary
            self._summary_cache_filter_settings = filter_settings
            self._summary_cache_expires_at = now + self.SUMMARY_CACHE_TTL_SECONDS
            return summary

    def _is_cache_valid(self, now, filter_settings):
        return (
            self._summary_cache is not None
            and now < self._summary_cache_expires_at
            and self._summary_cache_filter_settings == filter_settings
        )

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
            }
        return self._build_video_status_summary(label, visible_rows, 'avfan_enrichment_status')

    def _build_video_status_summary(self, label, rows, status_field):
        statuses = [str((row or {}).get(status_field, '') or '').strip() or UNENRICHED_STATUS for row in rows or []]
        summary = self._build_status_summary(label, statuses)
        summary['count_label'] = COMPLETED_LABEL
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
            )

        records = self.database.list_code_prefix_enrichment_records()
        statuses = [
            self._get_source_status(records.get(row.get('prefix', ''), {}), source_key)
            for row in self.code_prefix_library.list_prefixes()
            if row.get('prefix')
        ]
        return self._build_status_summary(self._build_source_label(CODE_PREFIX_LIBRARY_LABEL, source_key), statuses)

    def _build_actor_source_summary(self, source_key, filter_settings=None):
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
            )

        records = self.database.list_actor_enrichment_records()
        statuses = [
            self._get_source_status(records.get(str(row.get('name', '')).strip(), {}), source_key)
            for row in self.database.list_actors()
            if str(row.get('name', '')).strip()
        ]
        return self._build_status_summary(self._build_source_label(ACTOR_LIBRARY_LABEL, source_key), statuses)

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

    def _build_javtxt_library_video_summary(self, label, movies_by_group, filter_settings=None):
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
        }

    def _load_filter_settings(self):
        if self.video_filter_service is None:
            return None
        return self.video_filter_service.load_settings()

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


def _build_progress_percent(enriched_count, total_count):
    if total_count <= 0:
        return 0
    return round((float(enriched_count) / float(total_count)) * 100, 1)
