from app.gui.query_context import EntityType
from app.gui.unified_search_viewer import UnifiedSearchWindow


def test_unified_search_row_maps_ladder_result_to_target_entity():
    reference = UnifiedSearchWindow._reference_from_row(
        {
            'entity_type': EntityType.LADDER,
            'entity_key': 'actor:Actor A',
            'display_name': 'Actor A',
            'metadata': {
                'entity_type': EntityType.ACTOR,
                'entity_name': 'Actor A',
            },
        }
    )

    assert reference.entity_type == EntityType.ACTOR
    assert reference.entity_key == 'Actor A'


def test_unified_search_row_rejects_missing_key():
    assert UnifiedSearchWindow._reference_from_row({'entity_type': EntityType.ACTOR}) is None
