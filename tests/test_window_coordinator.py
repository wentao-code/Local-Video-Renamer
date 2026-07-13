from app.gui.query_context import EntityReference, EntityType, QueryContext
from app.gui.window_coordinator import WindowCoordinator


class FakeWindow:
    def __init__(self):
        self.contexts = []
        self.activations = 0

    def apply_query_context(self, context):
        self.contexts.append(context)

    def show(self):
        self.activations += 1

    def raise_(self):
        self.activations += 1

    def activateWindow(self):
        self.activations += 1


def test_coordinator_reuses_entity_window_and_applies_latest_context():
    coordinator = WindowCoordinator()
    created = []
    coordinator.set_factory(EntityType.ACTOR, lambda _reference, _context: created.append(FakeWindow()) or created[-1])
    reference = EntityReference(EntityType.ACTOR, 'Actor A')

    first = coordinator.open_entity(reference, QueryContext(search_text='first'))
    second = coordinator.open_entity(reference, QueryContext(search_text='second'))

    assert first is second
    assert len(created) == 1
    assert [context.search_text for context in first.contexts] == ['first', 'second']
    assert first.activations == 6


def test_coordinator_has_separate_keys_for_entity_and_list_windows():
    coordinator = WindowCoordinator()
    coordinator.set_factory('list:actor', lambda _context: FakeWindow())
    window = coordinator.open_list(EntityType.ACTOR)

    assert coordinator.get_window(('list', EntityType.ACTOR)) is window
    assert coordinator.get_window((EntityType.ACTOR, 'Actor A')) is None


def test_coordinator_reuses_one_detail_window_for_each_entity_type():
    coordinator = WindowCoordinator()
    created = []
    coordinator.set_factory(EntityType.ACTOR, lambda _reference, _context: created.append(FakeWindow()) or created[-1])

    first = coordinator.open_entity(EntityReference(EntityType.ACTOR, 'Actor A'))
    second = coordinator.open_entity(EntityReference(EntityType.ACTOR, 'Actor B'))

    assert first is second
    assert len(created) == 1
    assert second.contexts[-1].entity.entity_key == 'Actor B'


def test_coordinator_reuses_one_comparison_window_and_updates_entities():
    coordinator = WindowCoordinator()
    created = []

    class ComparisonFake(FakeWindow):
        def set_entities(self, first, second):
            self.entities = (first, second)

    coordinator.set_comparison_factory(lambda first, second: created.append(ComparisonFake()) or created[-1])
    first = EntityReference(EntityType.ACTOR, 'Actor A')
    second = EntityReference(EntityType.ACTOR, 'Actor B')
    third = EntityReference(EntityType.ACTOR, 'Actor C')

    window = coordinator.compare_entities(first, second)
    reused = coordinator.compare_entities(second, third)

    assert window is reused
    assert len(created) == 1
    assert reused.entities == (second, third)
