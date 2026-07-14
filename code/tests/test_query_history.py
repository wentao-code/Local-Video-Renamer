from app.gui.query_context import EntityReference, EntityType
from app.gui.query_history import QueryHistoryStore


def test_query_history_is_bounded_and_deduplicated(tmp_path):
    store = QueryHistoryStore(tmp_path / 'history.json', max_items=2)
    store.record_search('演员 A')
    store.record_search('番号 B')
    store.record_search('演员 A')

    assert store.recent_searches() == ['演员 A', '番号 B']


def test_query_history_stores_entities_without_database_access(tmp_path):
    store = QueryHistoryStore(tmp_path / 'history.json')
    reference = EntityReference(EntityType.ACTOR, '演员 A', display_name='演员 A')
    store.record_entity(reference)

    assert store.recent_entities()[0]['entity_key'] == '演员 A'
