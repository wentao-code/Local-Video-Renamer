from app.core.ladder_board import LADDER_BOARD_ACTOR, LADDER_BOARD_CODE_PREFIX


class UnifiedSearchService:
    """Builds bounded, read-only search results from existing library services."""

    def __init__(self, backend_service):
        self.backend_service = backend_service

    def search(self, search_text='', limit=20):
        query = str(search_text or '').strip()
        normalized_limit = max(1, min(100, int(limit or 20)))
        if not query:
            return {'query': '', 'results': [], 'total': 0}

        results = []
        results.extend(self._search_videos(query, normalized_limit))
        results.extend(self._search_actors(query, normalized_limit))
        results.extend(self._search_prefixes(query, normalized_limit))
        results.extend(self._search_ladder(query, normalized_limit))
        results.extend(self._search_masterpieces(query, normalized_limit))

        deduplicated = {}
        for item in results:
            key = (item['entity_type'], item['entity_key'])
            deduplicated.setdefault(key, item)
        ordered = list(deduplicated.values())
        return {'query': query, 'results': ordered, 'total': len(ordered)}

    def _search_videos(self, query, limit):
        payload = self.backend_service.list_videos(query, limit=limit, offset=0)
        rows = payload.get('videos', []) if isinstance(payload, dict) else payload
        return [
            self._result(
                'video',
                row.get('code'),
                row.get('title') or row.get('code'),
                row.get('author') or row.get('video_category', ''),
                'video_library',
            )
            for row in rows or []
            if row.get('code')
        ]

    def _search_actors(self, query, limit):
        payload = self.backend_service.list_actors(query, limit=limit, offset=0)
        rows = payload.get('actors', []) if isinstance(payload, dict) else payload
        return [
            self._result(
                'actor',
                row.get('name') or row.get('actor_name'),
                row.get('name') or row.get('actor_name'),
                row.get('age') or row.get('birthday', ''),
                'actor_library',
            )
            for row in rows or []
            if row.get('name') or row.get('actor_name')
        ]

    def _search_prefixes(self, query, limit):
        payload = self.backend_service.list_code_prefixes(query, limit=limit, offset=0)
        rows = payload.get('prefixes', []) if isinstance(payload, dict) else payload
        return [
            self._result(
                'code_prefix',
                row.get('prefix'),
                row.get('prefix'),
                f"{int(row.get('video_count', 0) or 0)} 部作品" if row.get('video_count') is not None else '',
                'code_prefix_library',
            )
            for row in rows or []
            if row.get('prefix')
        ]

    def _search_ladder(self, query, limit):
        results = []
        for board_key, entity_type in (
            (LADDER_BOARD_ACTOR, 'actor'),
            (LADDER_BOARD_CODE_PREFIX, 'code_prefix'),
        ):
            payload = self.backend_service.get_ladder_board(board_key)
            for group in ('selected', 'candidates'):
                for row in (payload or {}).get(group, []) or []:
                    name = str(row.get('display_name') or row.get('entity_name') or '').strip()
                    if name and query.casefold() in name.casefold():
                        results.append(
                            self._result(
                                'ladder',
                                f'{board_key}:{entity_type}:{name}',
                                name,
                                f"天梯榜 {row.get('tier', '') or '候选'}",
                                f'ladder:{board_key}',
                                metadata={
                                    'board_key': board_key,
                                    'entity_type': entity_type,
                                    'entity_name': name,
                                },
                            )
                        )
                        if len(results) >= limit * 2:
                            return results
        return results

    def _search_masterpieces(self, query, limit):
        payload = self.backend_service.list_masterpiece_entries()
        rows = payload.get('entries', []) if isinstance(payload, dict) else payload
        results = []
        for row in rows or []:
            code = str(row.get('code') or '').strip()
            title = str(row.get('display_title') or row.get('title') or code).strip()
            author = str(row.get('display_author') or row.get('author') or '').strip()
            if query.casefold() not in f'{code} {title} {author}'.casefold():
                continue
            results.append(self._result('masterpiece', code, title, author, 'masterpiece'))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _result(entity_type, entity_key, display_name, secondary_text, source, metadata=None):
        return {
            'entity_type': entity_type,
            'entity_key': str(entity_key or '').strip(),
            'display_name': str(display_name or entity_key or '').strip(),
            'secondary_text': str(secondary_text or '').strip(),
            'source': source,
            'metadata': dict(metadata or {}),
        }
