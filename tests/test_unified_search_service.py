from app.services.library.unified_search_service import UnifiedSearchService


class FakeBackendService:
    def list_videos(self, query, limit, offset):
        return {'videos': [{'code': 'ABC-001', 'title': 'First', 'author': 'Actor A'}]}

    def list_actors(self, query, limit, offset):
        return {'actors': [{'name': 'Actor A', 'age': '42'}]}

    def list_code_prefixes(self, query, limit, offset):
        return {'prefixes': [{'prefix': 'ABC', 'video_count': 4}]}

    def get_ladder_board(self, board_key):
        return {'selected': [{'entity_name': 'Actor A', 'tier': 'A'}], 'candidates': []}

    def list_masterpiece_entries(self):
        return {'entries': [{'code': 'ABC-001', 'display_title': 'First'}]}


def test_unified_search_merges_typed_results_and_deduplicates_per_type():
    payload = UnifiedSearchService(FakeBackendService()).search('ABC', limit=5)

    keys = {(row['entity_type'], row['entity_key']) for row in payload['results']}
    assert ('video', 'ABC-001') in keys
    assert ('code_prefix', 'ABC') in keys
    assert ('masterpiece', 'ABC-001') in keys
    assert payload['total'] == len(payload['results'])


def test_unified_search_is_empty_for_blank_query():
    assert UnifiedSearchService(FakeBackendService()).search('   ') == {
        'query': '',
        'results': [],
        'total': 0,
    }
