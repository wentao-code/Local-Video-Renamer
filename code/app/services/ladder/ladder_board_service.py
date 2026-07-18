import re

from app.core.ladder_board import (
    LADDER_ENTITY_ACTOR,
    LADDER_ENTITY_CODE_PREFIX,
    get_ladder_board_config,
    ladder_tier_sort_key,
    normalize_ladder_medal_text,
    normalize_ladder_tier,
    split_ladder_medals,
)
from app.core.medal_types import sort_medal_names
from app.services.identity import is_ignored_actor_name, split_actor_names
from app.services.library import extract_code_prefix


DEFAULT_LADDER_CANDIDATE_LIMIT = 20
ACTOR_LADDER_CANDIDATE_LIMIT = 188


class LadderBoardService:
    def __init__(self, database):
        self.database = database

    def get_board(self, board_key):
        config = get_ladder_board_config(board_key)
        local_counts = self._build_local_counts(config['entity_type'])
        return self._build_board_from_local_counts(config, local_counts)

    def _build_board_from_local_counts(self, config, local_counts):
        selected_entries = self.database.list_ladder_entries(config['board_key'], config['entity_type'])
        list_global_medals = getattr(self.database, 'list_global_medals', None)
        global_medals = list_global_medals() if callable(list_global_medals) else []
        medal_types_by_name = {
            str((row or {}).get('name', '') or '').strip(): str((row or {}).get('medal_type', '') or '').strip()
            for row in global_medals
            if str((row or {}).get('name', '') or '').strip()
        }
        selected_names = {
            str((entry or {}).get('entity_name', '') or '').strip()
            for entry in selected_entries
            if str((entry or {}).get('entity_name', '') or '').strip()
        }

        if config['entity_type'] == LADDER_ENTITY_ACTOR:
            candidates = self._build_actor_candidates(selected_names, local_counts)
        else:
            candidates = self._build_count_candidates(
                selected_names,
                local_counts,
                DEFAULT_LADDER_CANDIDATE_LIMIT,
            )

        selected = []
        for entry in selected_entries:
            entity_name = str((entry or {}).get('entity_name', '') or '').strip()
            tier = str((entry or {}).get('tier', '') or '').strip().upper()
            if tier == 'D':
                continue
            medals = sort_medal_names(split_ladder_medals((entry or {}).get('medal', '')), medal_types_by_name)
            medal_text = normalize_ladder_medal_text('\n'.join(medals))
            selected.append(
                {
                    'entity_name': entity_name,
                    'display_name': entity_name,
                    'tier': tier,
                    'medal': medal_text,
                    'medals': medals,
                    'local_video_count': int(dict(local_counts).get(entity_name, 0) or 0),
                }
            )

        selected.sort(
            key=lambda item: (
                ladder_tier_sort_key(item.get('tier')),
                -int(item.get('local_video_count', 0) or 0),
                str(item.get('display_name', '') or '').upper(),
            )
        )

        return {
            'board_key': config['board_key'],
            'entity_type': config['entity_type'],
            'candidates': candidates,
            'selected': selected,
        }

    def admit_entry(self, board_key, entity_name, tier):
        config = get_ladder_board_config(board_key)
        normalized_name = str(entity_name or '').strip()
        normalized_tier = normalize_ladder_tier(tier)
        if not normalized_name:
            raise ValueError('缺少入选名称')
        if not normalized_tier:
            raise ValueError('请选择有效等级')

        local_counts = self._build_local_counts(config['entity_type'])
        if config['entity_type'] == LADDER_ENTITY_ACTOR:
            selected_entries = self.database.list_ladder_entries(config['board_key'], config['entity_type'])
            selected_names = {
                str((entry or {}).get('entity_name', '') or '').strip()
                for entry in selected_entries
                if str((entry or {}).get('entity_name', '') or '').strip()
            }
            available_names = {
                item['entity_name']
                for item in self._build_actor_candidates(selected_names, local_counts)
            } | selected_names
        else:
            available_names = {name for name, _count in local_counts}
        if normalized_name not in available_names:
            raise ValueError('未找到对应候选项')

        self.database.save_ladder_entry(
            config['board_key'],
            config['entity_type'],
            normalized_name,
            normalized_tier,
        )
        return self._build_board_from_local_counts(config, local_counts)

    def admit_entry_fast(self, board_key, entity_name, tier):
        config = get_ladder_board_config(board_key)
        normalized_name = str(entity_name or '').strip()
        normalized_tier = normalize_ladder_tier(tier)
        if not normalized_name:
            raise ValueError('缺少入选名称')
        if not normalized_tier:
            raise ValueError('请选择有效等级')

        self.database.save_ladder_entry(
            config['board_key'],
            config['entity_type'],
            normalized_name,
            normalized_tier,
            timeout_seconds=3,
        )
        return {
            'board_key': config['board_key'],
            'entity_type': config['entity_type'],
            'entity_name': normalized_name,
            'tier': normalized_tier,
        }

    def update_medal(self, board_key, entity_name, medal):
        config = get_ladder_board_config(board_key)
        normalized_name = str(entity_name or '').strip()
        if not normalized_name:
            raise ValueError('缺少入选名称')
        self.database.update_ladder_entry_medal(
            config['board_key'],
            config['entity_type'],
            normalized_name,
            normalize_ladder_medal_text(medal),
        )
        return self.get_board(config['board_key'])

    def _build_local_counts(self, entity_type):
        if entity_type == LADDER_ENTITY_ACTOR:
            return self._build_actor_local_counts()
        if entity_type == LADDER_ENTITY_CODE_PREFIX:
            return self._build_code_prefix_local_counts()
        return []

    def _build_actor_local_counts(self):
        grouped = {}
        for row in self.database.list_videos():
            for actor_name in split_actor_names((row or {}).get('author', '')):
                normalized_name = str(actor_name or '').strip()
                if not normalized_name or is_ignored_actor_name(normalized_name):
                    continue
                grouped[normalized_name] = grouped.get(normalized_name, 0) + 1
        return self._sort_grouped_counts(grouped)

    def _build_code_prefix_local_counts(self):
        grouped = {}
        for row in self.database.list_videos():
            prefix = extract_code_prefix((row or {}).get('code', ''))
            if not prefix:
                continue
            grouped[prefix] = grouped.get(prefix, 0) + 1
        return self._sort_grouped_counts(grouped)

    def _build_actor_candidates(self, selected_names, local_counts):
        selected_names = set(selected_names or set())
        hidden_actor_names = self._list_hidden_actor_names()
        local_count_map = {
            str(name or '').strip(): int(count or 0)
            for name, count in (local_counts or [])
            if str(name or '').strip()
        }
        profiles = {}

        for actor_name, local_video_count in local_count_map.items():
            if not self._is_allowed_actor_candidate(actor_name, hidden_actor_names):
                continue
            profiles[actor_name] = {
                'entity_name': actor_name,
                'display_name': actor_name,
                'local_video_count': int(local_video_count or 0),
                'age': None,
                'masterpiece_unrated': False,
            }

        for row in self._list_actor_library_rows():
            actor_name = str((row or {}).get('name', (row or {}).get('actor_name', '')) or '').strip()
            if not self._is_allowed_actor_candidate(actor_name, hidden_actor_names):
                continue
            profile = profiles.setdefault(
                actor_name,
                {
                    'entity_name': actor_name,
                    'display_name': actor_name,
                    'local_video_count': int(local_count_map.get(actor_name, 0) or 0),
                    'age': None,
                    'masterpiece_unrated': False,
                },
            )
            profile['age'] = self._parse_actor_age((row or {}).get('raw_age', (row or {}).get('age', '')))

        for row in self._list_masterpiece_ladder_actor_candidates():
            actor_name = str((row or {}).get('actor_name', (row or {}).get('name', '')) or '').strip()
            if not self._is_allowed_actor_candidate(actor_name, hidden_actor_names):
                continue
            profile = profiles.setdefault(
                actor_name,
                {
                    'entity_name': actor_name,
                    'display_name': actor_name,
                    'local_video_count': int(local_count_map.get(actor_name, 0) or 0),
                    'age': None,
                    'masterpiece_unrated': False,
                },
            )
            profile['masterpiece_unrated'] = True

        sorted_profiles = sorted(
            (
                profile
                for profile in profiles.values()
                if profile['entity_name'] not in selected_names
            ),
            key=self._actor_candidate_sort_key,
        )
        return [
            {
                'entity_name': profile['entity_name'],
                'display_name': profile['display_name'],
                'local_video_count': int(profile.get('local_video_count', 0) or 0),
            }
            for profile in sorted_profiles[:ACTOR_LADDER_CANDIDATE_LIMIT]
        ]

    def _list_actor_library_rows(self):
        list_actors = getattr(self.database, 'list_actors', None)
        if not callable(list_actors):
            return []
        return list_actors()

    def _list_masterpiece_ladder_actor_candidates(self):
        list_candidates = getattr(self.database, 'list_masterpiece_ladder_actor_candidates', None)
        if not callable(list_candidates):
            return []
        return list_candidates()

    def _list_hidden_actor_names(self):
        list_hidden_actors = getattr(self.database, 'list_hidden_actors', None)
        if not callable(list_hidden_actors):
            return set()
        return {
            str(actor_name or '').strip()
            for actor_name in (list_hidden_actors() or set())
            if str(actor_name or '').strip()
        }

    @staticmethod
    def _is_allowed_actor_candidate(actor_name, hidden_actor_names):
        normalized_name = str(actor_name or '').strip()
        return (
            bool(normalized_name)
            and normalized_name not in (hidden_actor_names or set())
            and not is_ignored_actor_name(normalized_name)
        )

    @staticmethod
    def _parse_actor_age(value):
        match = re.search(r'\d+', str(value or '').strip())
        if not match:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    @classmethod
    def _actor_candidate_sort_key(cls, profile):
        name_key = cls._actor_name_sort_key(profile.get('entity_name', ''))
        local_video_count = int(profile.get('local_video_count', 0) or 0)
        age = profile.get('age')

        if profile.get('masterpiece_unrated'):
            return (0, -local_video_count, name_key)
        if age is not None and age > 40 and local_video_count > 0:
            return (1, -local_video_count, name_key)
        if age is not None and age > 40:
            return (2, -age, name_key)
        if age is None:
            return (3, name_key)
        if local_video_count > 0:
            return (4, -local_video_count, name_key)
        return (5, -age, name_key)

    @staticmethod
    def _actor_name_sort_key(actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return (2, '')
        if normalized_name[0].isascii():
            return (0, normalized_name.upper())
        return (1, tuple(normalized_name.encode('gb18030', errors='ignore')), normalized_name)

    @staticmethod
    def _build_count_candidates(selected_names, local_counts, candidate_limit):
        candidates = []
        for entity_name, local_video_count in local_counts:
            if entity_name in selected_names:
                continue
            candidates.append(
                {
                    'entity_name': entity_name,
                    'display_name': entity_name,
                    'local_video_count': int(local_video_count or 0),
                }
            )
            if len(candidates) >= candidate_limit:
                break
        return candidates

    @staticmethod
    def _sort_grouped_counts(grouped):
        return sorted(
            grouped.items(),
            key=lambda item: (-int(item[1] or 0), str(item[0] or '').upper()),
        )
