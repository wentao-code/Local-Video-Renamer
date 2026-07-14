import pytest

from app.gui.query_context import EntityReference, EntityType, NavigationRequest, QueryContext


def test_entity_reference_normalizes_and_serializes():
    reference = EntityReference(EntityType.ACTOR, '  Actor A ', display_name=' Actor A ')

    assert reference.entity_key == 'Actor A'
    assert reference.display_name == 'Actor A'
    assert reference.as_dict()['entity_type'] == EntityType.ACTOR


def test_query_context_copies_filters_and_calculates_offset():
    original_filters = {'age_min': 40}
    context = QueryContext(filters=original_filters, page=3, page_size=25, sort_order='DESC')
    original_filters['age_min'] = 99
    updated = context.copy_with(filters={'age_min': 50})

    assert context.filters == {'age_min': 40}
    assert context.offset == 50
    assert context.sort_order == 'desc'
    assert updated.filters == {'age_min': 50}


def test_navigation_request_rejects_unknown_entity_type_and_action():
    with pytest.raises(ValueError):
        EntityReference('unknown', 'key')
    with pytest.raises(ValueError):
        NavigationRequest(action='mutate')
