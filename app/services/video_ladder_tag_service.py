from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_ENTITY_CODE_PREFIX,
    split_ladder_medals,
)
from app.core.video_ladder_tags import build_video_ladder_tag_text, build_video_ladder_tags


class VideoLadderTagService:
    _SEARCH_FIELDS = (
        'code',
        'title',
        'author',
        'javtxt_title',
        'javtxt_actors',
        'javtxt_tags',
        'ladder_tag_text',
        'video_category',
        'duration',
        'size',
        'storage_location',
        'avfan_movie_id',
        'javtxt_movie_id',
        'release_date',
        'maker',
        'publisher',
        'enrichment_status',
    )

    def __init__(self, database):
        self.database = database

    def load_medal_maps(self):
        actor_medal_map = {}
        prefix_medal_map = {}

        entries = []
        entries.extend(self.database.list_ladder_entries(LADDER_BOARD_ACTOR, LADDER_ENTITY_ACTOR))
        entries.extend(self.database.list_ladder_entries(LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX))

        for entry in entries:
            entity_type = str((entry or {}).get('entity_type', '') or '').strip().lower()
            entity_name = str((entry or {}).get('entity_name', '') or '').strip()
            medals = split_ladder_medals((entry or {}).get('medal', ''))
            if not entity_name or not medals:
                continue
            if entity_type == LADDER_ENTITY_ACTOR:
                actor_medal_map[entity_name] = medals
            elif entity_type == LADDER_ENTITY_CODE_PREFIX:
                prefix_medal_map[entity_name.upper()] = medals

        return {
            'actor_medal_map': actor_medal_map,
            'prefix_medal_map': prefix_medal_map,
        }

    def build_tags(self, code='', author='', medal_maps=None):
        medal_maps = dict(medal_maps or self.load_medal_maps())
        return build_video_ladder_tags(
            code=code,
            author=author,
            actor_medal_map=medal_maps.get('actor_medal_map', {}),
            prefix_medal_map=medal_maps.get('prefix_medal_map', {}),
        )

    def enrich_video_rows(self, rows, medal_maps=None):
        medal_maps = dict(medal_maps or self.load_medal_maps())
        enriched_rows = []
        for row in rows or []:
            enriched = dict(row or {})
            tags = self.build_tags(
                code=enriched.get('code', ''),
                author=enriched.get('author', ''),
                medal_maps=medal_maps,
            )
            enriched['ladder_tags'] = tags
            enriched['ladder_tag_text'] = build_video_ladder_tag_text(tags)
            enriched_rows.append(enriched)
        return enriched_rows

    def filter_video_rows(self, rows, search_text=''):
        normalized_search = str(search_text or '').strip().lower()
        if not normalized_search:
            return list(rows or [])

        filtered_rows = []
        for row in rows or []:
            haystack = ' '.join(
                str((row or {}).get(field, '') or '')
                for field in self._SEARCH_FIELDS
            ).lower()
            if normalized_search in haystack:
                filtered_rows.append(dict(row or {}))
        return filtered_rows
