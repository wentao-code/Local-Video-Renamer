import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.query_context import EntityReference, EntityType, QueryContext


_APP = QApplication.instance() or QApplication([])


def _build_window():
    with patch('app.gui.actor_detail_viewer.QTimer.singleShot'):
        return ActorDetailViewerWindow(object(), 'Actor A')


def test_actor_detail_applies_navigation_context_to_existing_window():
    window = _build_window()
    try:
        window._switch_actor = Mock()
        reference = EntityReference(EntityType.ACTOR, 'Actor B')

        window.apply_query_context(QueryContext(source='actor_library', entity=reference))

        window._switch_actor.assert_called_once_with('Actor B')
    finally:
        window.deleteLater()


def test_actor_detail_keeps_current_actor_when_context_has_no_actor():
    window = _build_window()
    try:
        window._switch_actor = Mock()
        context = SimpleNamespace(entity=None, search_text='')

        window.apply_query_context(context)

        window._switch_actor.assert_not_called()
    finally:
        window.deleteLater()


def test_actor_detail_uses_coordinated_actor_list_for_neighbor_navigation():
    actor_list = Mock()
    actor_list.neighbor_detail_key.side_effect = lambda current, offset: {
        ('Actor B', -1): 'Actor A',
        ('Actor B', 1): 'Actor C',
    }.get((current, offset))
    coordinator = Mock()
    coordinator.get_window.return_value = actor_list

    window = _build_window()
    try:
        window.coordinator = coordinator
        window.actor_name = 'Actor B'

        window._refresh_navigation_buttons()

        coordinator.get_window.assert_called_with(('list', EntityType.ACTOR))
        assert window.btn_prev_item.isEnabled()
        assert window.btn_next_item.isEnabled()

        window.load_data = Mock()
        window._switch_actor('Actor C')
        actor_list.select_actor_row.assert_called_once_with('Actor C')
    finally:
        window.deleteLater()
