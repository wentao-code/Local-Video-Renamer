import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QDialog

from app.core.ladder_board import LADDER_BOARD_ACTOR
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr
from app.gui.ladder_board_viewer import LadderBoardWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(
    self,
    task,
    success_handler,
    error_title=None,
    block_ui=True,
    allow_deferred_close=False,
):
    success_handler(task())
    return True


class LadderBoardBackendStub:
    def __init__(self):
        self.refresh_flags = []
        self.medal_calls = []
        self.global_medals = [
            {'name': 'Rookie', 'description': 'For debut-level standouts'},
            {'name': 'Evergreen', 'description': 'For long-running elite entries'},
        ]

    def get_ladder_board_snapshot(self, board_key, force_refresh=False):
        self.refresh_flags.append((board_key, bool(force_refresh)))
        return {
            'board': {
                'board_key': board_key,
                'entity_type': 'actor',
                'candidates': [{'entity_name': 'ActorA', 'display_name': 'ActorA', 'local_video_count': 3}],
                'selected': [
                    {
                        'entity_name': 'ActorA',
                        'display_name': 'ActorA',
                        'tier': 'S',
                        'medal': 'Rookie',
                        'medals': ['Rookie'],
                    }
                ],
            },
            'refreshed_at': '2026-06-21 21:00:00',
        }

    def list_global_medals(self):
        return [dict(row) for row in self.global_medals]

    def update_ladder_entry_medal(self, board_key, entity_name, medal):
        self.medal_calls.append((board_key, entity_name, medal))
        return {}


class _AcceptedGlobalMedalDialog:
    def __init__(self, *_args, **_kwargs):
        pass

    def exec_(self):
        return QDialog.Accepted

    def selected_medal_names(self):
        return ['Evergreen']


class LadderBoardViewerTest(unittest.TestCase):
    def test_uses_cached_snapshot_on_open_and_force_refresh_on_button_click(self):
        backend = LadderBoardBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = LadderBoardWindow(backend)
            try:
                self.assertEqual(backend.refresh_flags, [(LADDER_BOARD_ACTOR, False)])
                self.assertIn('2026-06-21 21:00:00', window.last_refreshed_label.text())

                window.load_board(force_refresh=True)

                self.assertEqual(
                    backend.refresh_flags,
                    [(LADDER_BOARD_ACTOR, False), (LADDER_BOARD_ACTOR, True)],
                )
            finally:
                window.hide()
                window.deleteLater()

    def test_selects_global_medal_and_merges_existing_medals(self):
        backend = LadderBoardBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch(
            'app.gui.ladder_selected_panel.GlobalMedalPickerDialog',
            _AcceptedGlobalMedalDialog,
        ):
            window = LadderBoardWindow(backend)
            try:
                action_button = window.selected_panel.table.cellWidget(0, 3)
                action_button.click()

                self.assertEqual(
                    backend.medal_calls,
                    [(LADDER_BOARD_ACTOR, 'ActorA', 'Rookie\nEvergreen')],
                )
            finally:
                window.hide()
                window.deleteLater()

    def test_selected_panel_uses_add_label_even_when_medals_already_exist(self):
        backend = LadderBoardBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = LadderBoardWindow(backend)
            try:
                action_button = window.selected_panel.table.cellWidget(0, 3)
                medal_label = window.selected_panel.table.cellWidget(0, 2)

                self.assertEqual(action_button.text(), tr('ladder.selected.add_medal'))
                self.assertNotIn(tr('ladder.selected.edit_medal'), action_button.text())
                self.assertNotIn(tr('ladder.selected.medal_empty'), medal_label.text())
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
