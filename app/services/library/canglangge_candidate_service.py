from datetime import datetime

from app.core.javtxt_video_state import JAVTXT_AUTHOR_MIN_RELEASE_DATE
from app.core.ladder_board import (
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_CODE_PREFIX,
    LADDER_TIER_S,
)
from app.services.identity import split_actor_names


class CanglanggeCandidateService:
    def __init__(self, database):
        self.database = database

    def list_candidates(self):
        s_prefixes = self._load_s_prefixes()
        if not s_prefixes:
            return []

        actor_library_names = self._load_actor_library_names()
        hidden_actor_names = self._load_hidden_actor_names()
        enrichment_records = self._load_actor_enrichment_records()
        grouped = {}

        for prefix, movies in self._load_web_movies_by_prefix(s_prefixes).items():
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix not in s_prefixes:
                continue
            for row in movies or []:
                if not self._is_recent_row(row):
                    continue

                seen_names = set()
                for actor_name in split_actor_names((row or {}).get('author', '')):
                    if actor_name in seen_names:
                        continue
                    seen_names.add(actor_name)
                    if actor_name in actor_library_names or actor_name in hidden_actor_names:
                        continue

                    current = grouped.setdefault(
                        actor_name,
                        {
                            'actor_name': actor_name,
                            'prefixes': set(),
                            'birthday': str((enrichment_records.get(actor_name, {}) or {}).get('binghuo_birthday', '') or '').strip(),
                            'age': str((enrichment_records.get(actor_name, {}) or {}).get('binghuo_age', '') or '').strip(),
                        },
                    )
                    current['prefixes'].add(normalized_prefix)

        return [
            {
                'actor_name': actor_name,
                'prefixes': sorted(data['prefixes']),
                'birthday': str(data.get('birthday', '') or '').strip(),
                'age': str(data.get('age', '') or '').strip(),
            }
            for actor_name, data in sorted(grouped.items(), key=lambda item: item[0])
        ]

    def _load_s_prefixes(self):
        if not hasattr(self.database, 'list_ladder_entries'):
            return set()
        return {
            str((entry or {}).get('entity_name', '') or '').strip().upper()
            for entry in self.database.list_ladder_entries(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX)
            if str((entry or {}).get('tier', '') or '').strip().upper() == LADDER_TIER_S
            and str((entry or {}).get('entity_name', '') or '').strip()
        }

    def _load_web_movies_by_prefix(self, prefixes):
        if hasattr(self.database, 'list_code_prefix_movies_by_prefixes'):
            raw_results = self.database.list_code_prefix_movies_by_prefixes(sorted(prefixes))
            normalized_results = {}
            for prefix, movies in (raw_results or {}).items():
                normalized_prefix = str(prefix or '').strip().upper()
                if not normalized_prefix:
                    continue
                normalized_results[normalized_prefix] = [dict(movie or {}) for movie in movies or []]
            return normalized_results
        if not hasattr(self.database, 'list_code_prefix_movies'):
            return {}
        return {
            str(prefix or '').strip().upper(): [
                dict(movie or {})
                for movie in self.database.list_code_prefix_movies(prefix)
            ]
            for prefix in sorted(prefixes)
            if str(prefix or '').strip()
        }

    def _load_actor_library_names(self):
        if not hasattr(self.database, 'list_actors'):
            return set()
        return {
            str((row or {}).get('name', '') or '').strip()
            for row in self.database.list_actors()
            if str((row or {}).get('name', '') or '').strip()
        }

    def _load_hidden_actor_names(self):
        if not hasattr(self.database, 'list_hidden_actors'):
            return set()
        return {
            str(name or '').strip()
            for name in (self.database.list_hidden_actors() or set())
            if str(name or '').strip()
        }

    def _load_actor_enrichment_records(self):
        if not hasattr(self.database, 'list_actor_enrichment_records'):
            return {}
        return {
            str(actor_name or '').strip(): dict(record or {})
            for actor_name, record in (self.database.list_actor_enrichment_records() or {}).items()
            if str(actor_name or '').strip()
        }

    def _is_recent_row(self, row):
        release_date_text = str(
            ((row or {}).get('javtxt_release_date') or (row or {}).get('release_date', '')) or ''
        ).strip()
        if not release_date_text:
            return False

        try:
            release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
        except ValueError:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE
