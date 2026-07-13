from app.core.enrichment_status import (
    ENRICHED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
)
from app.services.detail.update_status_service import resolve_update_status
from app.services.identity import split_actor_names
from app.services.video import VIDEO_CATEGORY_SINGLE


_TERMINAL_REFRESH_STATUSES = {
    ENRICHED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
}

_ENTITY_CONFIG = {
    'actor': {
        'expired_method': 'list_expired_actor_enrichment_entities',
        'movies_method': 'list_actor_movies',
        'completion_method': 'record_actor_enrichment_refresh_completion',
        'history_method': 'record_actor_expired_refresh_history',
    },
    'code_prefix': {
        'expired_method': 'list_expired_code_prefix_enrichment_entities',
        'movies_method': 'list_code_prefix_movies',
        'completion_method': 'record_code_prefix_enrichment_refresh_completion',
        'history_method': 'record_code_prefix_expired_refresh_history',
    },
}


def sync_actor_refresh_update_statuses(database):
    list_refresh_times = getattr(database, 'list_actor_enrichment_refresh_times', None)
    update_statuses = getattr(database, 'update_actor_enrichment_refresh_statuses', None)
    if not callable(list_refresh_times) or not callable(update_statuses):
        return

    refresh_times = list_refresh_times() or {}
    actor_names = sorted(
        {
            str((key[0] if isinstance(key, tuple) else (record or {}).get('actor_name', '')) or '').strip()
            for key, record in refresh_times.items()
            if str((key[0] if isinstance(key, tuple) else (record or {}).get('actor_name', '')) or '').strip()
        }
    )
    if not actor_names:
        return

    actor_name_set = set(actor_names)
    local_movies_by_actor = {actor_name: [] for actor_name in actor_names}
    list_local_videos = getattr(database, 'list_local_videos_by_actor_names', None)
    if callable(list_local_videos):
        try:
            local_rows = list_local_videos(actor_names, refresh_categories=False) or []
        except TypeError:
            local_rows = list_local_videos(actor_names) or []
        for row in local_rows:
            current_names = {
                str(actor_name or '').strip()
                for actor_name in split_actor_names((row or {}).get('author', ''))
                if str(actor_name or '').strip()
            }
            for actor_name in actor_name_set.intersection(current_names):
                local_movies_by_actor[actor_name].append(dict(row or {}))

    latest_release_dates = {}
    list_latest_release_dates = getattr(database, 'list_latest_actor_movie_release_dates_by_names', None)
    if callable(list_latest_release_dates):
        latest_release_dates = list_latest_release_dates(actor_names) or {}

    current_statuses = {}
    for actor_name in actor_names:
        status_rows = list(local_movies_by_actor.get(actor_name, []))
        latest_release_date = str(latest_release_dates.get(actor_name, '') or '').strip()
        if latest_release_date:
            status_rows.append(
                {
                    'release_date': latest_release_date,
                    'video_category': VIDEO_CATEGORY_SINGLE,
                }
            )
        current_statuses[actor_name] = resolve_update_status(status_rows)
    update_statuses(current_statuses)


def sync_code_prefix_refresh_update_statuses(database, prefix_library):
    if not callable(getattr(database, 'list_code_prefix_enrichment_refresh_times', None)):
        return
    if not callable(getattr(database, 'update_code_prefix_enrichment_refresh_statuses', None)):
        return
    list_prefixes = getattr(prefix_library, 'list_prefixes', None)
    if callable(list_prefixes):
        list_prefixes()


class LibraryExpiredRefreshTracker:
    def __init__(self, database, entity_type, source_key):
        self.database = database
        self.entity_type = str(entity_type or '').strip()
        self.source_key = str(source_key or '').strip()
        self.config = _ENTITY_CONFIG[self.entity_type]
        expired_method = getattr(database, self.config['expired_method'], None)
        self.expired_entities = set(expired_method(self.source_key) or []) if callable(expired_method) else set()
        self._previous_counts = {}

    def is_expired(self, entity):
        return self._normalize_entity(entity) in self.expired_entities

    def start(self, entity):
        normalized_entity = self._normalize_entity(entity)
        if normalized_entity in self.expired_entities:
            self._previous_counts[normalized_entity] = self._video_count(normalized_entity)

    def complete(self, entity, status):
        if str(status or '').strip() not in _TERMINAL_REFRESH_STATUSES:
            return {}
        normalized_entity = self._normalize_entity(entity)
        completion_method = getattr(self.database, self.config['completion_method'], None)
        if callable(completion_method):
            completion_method(normalized_entity, self.source_key)

        if normalized_entity not in self.expired_entities:
            return {'expired_refresh': False, 'new_video_count': 0}

        previous_count = self._previous_counts.get(normalized_entity, self._video_count(normalized_entity))
        current_count = self._video_count(normalized_entity)
        history_method = getattr(self.database, self.config['history_method'], None)
        if callable(history_method):
            history_method(
                normalized_entity,
                self.source_key,
                previous_count,
                current_count,
            )
        return {
            'expired_refresh': True,
            'new_video_count': max(0, current_count - previous_count),
        }

    def _video_count(self, entity):
        movies_method = getattr(self.database, self.config['movies_method'], None)
        if not callable(movies_method):
            return 0
        return len(
            {
                str((row or {}).get('code', '') or '').strip().upper()
                for row in movies_method(entity) or []
                if str((row or {}).get('code', '') or '').strip()
            }
        )

    def _normalize_entity(self, entity):
        normalized = str(entity or '').strip()
        return normalized.upper() if self.entity_type == 'code_prefix' else normalized
