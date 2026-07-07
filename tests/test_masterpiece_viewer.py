import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication, QDialog, QGroupBox, QPushButton

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.masterpiece_viewer import MasterpieceDetailWindow, MasterpieceWindow


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


class MasterpieceBackendStub:
    def __init__(self):
        self.entries = [
            {
                'code': 'PFSA-001',
                'title': 'Perfect First Scene',
                'author': 'Alice',
                'medal': 'Rookie',
                'medals': ['Rookie'],
            }
        ]
        self.add_calls = []
        self.medal_calls = []
        self.detail_calls = []
        self.detail_refresh_flags = []
        self.global_medals = [
            {'name': 'Rookie', 'description': 'For debut-level standouts'},
            {'name': 'Evergreen', 'description': 'For long-running elite entries'},
        ]

    def list_masterpiece_entries(self):
        return [dict(row) for row in self.entries]

    def add_masterpiece_entry(self, code):
        normalized_code = str(code or '').strip().upper()
        self.add_calls.append(normalized_code)
        row = {
            'code': normalized_code,
            'title': 'Second Story',
            'author': 'Beta',
            'medal': '',
            'medals': [],
        }
        self.entries.append(row)
        return dict(row)

    def update_masterpiece_entry_medal(self, code, medal):
        self.medal_calls.append((code, medal))
        for row in self.entries:
            if row['code'] == code:
                row['medal'] = medal
                row['medals'] = [segment for segment in medal.split('\n') if segment]
                return dict(row)
        raise AssertionError('missing code')

    def list_global_medals(self):
        return [dict(row) for row in self.global_medals]

    def get_masterpiece_detail_snapshot(self, code, force_refresh=False):
        self.detail_refresh_flags.append(bool(force_refresh))
        self.detail_calls.append(code)
        return {
            'detail': {
                'code': code,
                'display_title': 'Perfect First Scene',
                'display_author': 'Alice',
                'primary_source': 'video_library',
                'primary_detail_url': 'https://avfan.example/movies/avfan-001',
                'medal': 'Rookie',
                'medals': ['Rookie'],
                'actor_details': [
                    {
                        'actor_name': 'Alice',
                        'birthday': '2000/4/10',
                        'current_age': '24',
                        'appearance_age': '24',
                        'height': '168',
                        'bust': '88',
                        'waist': '59',
                        'hip': '89',
                        'cup': 'E',
                        'measurements_raw': 'B88(E) W59 H89',
                        'actor_exists_in_library': 1,
                        'ladder_tier': 'S',
                    },
                    {
                        'actor_name': 'Beta',
                        'birthday': '',
                        'current_age': '',
                        'appearance_age': '',
                        'height': '',
                        'bust': '',
                        'waist': '',
                        'hip': '',
                        'cup': '',
                        'measurements_raw': '',
                        'actor_exists_in_library': 0,
                        'ladder_tier': 'B',
                    },
                ],
                'collaborator_sections': [
                    {
                        'actor_name': 'Alice',
                        'ladder_tier': 'S',
                        'collaborators': [
                            {'actor_name': 'Carol', 'count': 3},
                            {'actor_name': 'Dana', 'count': 2},
                            {'actor_name': 'Erin', 'count': 2},
                            {'actor_name': 'Fiona', 'count': 1},
                            {'actor_name': 'Grace', 'count': 1},
                            {'actor_name': 'Helen', 'count': 1},
                            {'actor_name': 'Iris', 'count': 1},
                        ],
                    }
                ],
                'references': [
                    {
                        'reference_source': 'video_library',
                        'reference_key': 'PFSA-001',
                        'matched_code': 'PFSA-001',
                        'title': 'Perfect First Scene',
                        'author': 'Alice',
                        'release_date': '2024-05-01',
                        'detail_url': 'https://avfan.example/movies/avfan-001',
                    },
                    {
                        'reference_source': 'actor_library',
                        'reference_key': 'Alice',
                        'matched_code': 'PFSA-001',
                        'title': 'Actor Library Copy',
                        'author': 'Alice',
                        'release_date': '2024-05-02',
                        'detail_url': '',
                    },
                    {
                        'reference_source': 'code_prefix_library',
                        'reference_key': 'PFSA',
                        'matched_code': 'PFSA-001',
                        'title': 'Prefix Library Copy',
                        'author': 'Alice',
                        'release_date': '2024-05-03',
                        'detail_url': 'https://javtxt.example/pfsa-001',
                    },
                ],
            },
            'refreshed_at': '2026-07-07 09:32:00' if force_refresh else '2026-07-07 09:30:00',
            'cache_hit': not force_refresh,
        }

    def get_masterpiece_detail(self, code):
        return self.get_masterpiece_detail_snapshot(code, force_refresh=True)['detail']


class _AcceptedGlobalMedalDialog:
    def __init__(self, *_args, **_kwargs):
        pass

    def exec_(self):
        return QDialog.Accepted

    def selected_medal_names(self):
        return ['Evergreen']


class MasterpieceViewerTest(unittest.TestCase):
    def test_window_loads_entries(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                self.assertEqual(window.table.rowCount(), 1)
                self.assertEqual(window.table.item(0, 0).text(), 'PFSA-001')
            finally:
                window.hide()
                window.deleteLater()

    def test_window_adds_new_code_then_opens_global_medal_picker(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch(
            'app.gui.masterpiece_viewer.GlobalMedalPickerDialog',
            _AcceptedGlobalMedalDialog,
        ):
            window = MasterpieceWindow(backend)
            try:
                window.code_input.setText('ipx-001')
                window.handle_add_entry()

                self.assertEqual(backend.add_calls, ['IPX-001'])
                self.assertEqual(backend.medal_calls, [('IPX-001', 'Evergreen')])
            finally:
                window.hide()
                window.deleteLater()

    def test_window_selects_new_global_medal_and_merges_existing_ones(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch(
            'app.gui.masterpiece_viewer.GlobalMedalPickerDialog',
            _AcceptedGlobalMedalDialog,
        ):
            window = MasterpieceWindow(backend)
            try:
                action_button = window.table.cellWidget(0, 4)
                action_button.click()

                self.assertEqual(backend.medal_calls, [('PFSA-001', 'Rookie\nEvergreen')])
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_renders_grouped_reference_sections(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                self.assertEqual(backend.detail_refresh_flags, [False, True])
                self.assertEqual(backend.detail_calls, ['PFSA-001', 'PFSA-001'])
                self.assertIn('2026-07-07 09:32:00', window.last_refreshed_label.text())
                group_titles = {group.title() for group in window.findChildren(QGroupBox)}
                self.assertIn(window._source_title('video_library'), group_titles)
                self.assertIn(window._source_title('actor_library'), group_titles)
                self.assertIn(window._source_title('code_prefix_library'), group_titles)

                detail_buttons = [
                    button
                    for button in window.findChildren(QPushButton)
                    if button.text() == '详情'
                ]
                self.assertGreaterEqual(len(detail_buttons), 3)
                self.assertEqual([button.isEnabled() for button in detail_buttons[-3:]], [True, False, True])
                self.assertEqual(window.actor_table.rowCount(), 2)
                self.assertEqual(window.actor_table.item(0, 0).text(), 'Alice')
                self.assertEqual(window.actor_table.item(0, 3).text(), '24')
                self.assertEqual(window.actor_table.item(1, 0).text(), 'Beta')
                self.assertIn('Alice', window.collaborator_tables)
                self.assertEqual(window.collaborator_tables['Alice'].columnCount(), 6)
                self.assertEqual(window.collaborator_tables['Alice'].rowCount(), 2)
                self.assertEqual(window.collaborator_tables['Alice'].item(0, 0).text(), 'Carol x3')
                self.assertEqual(window.collaborator_tables['Alice'].item(1, 0).text(), 'Iris x1')
            finally:
                window.hide()
                window.deleteLater()

    def test_close_event_ignores_close_while_async_task_running(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                event = QCloseEvent()
                with patch.object(window, 'block_close_while_async_running', return_value=True) as block_mock:
                    window.closeEvent(event)

                block_mock.assert_called_once_with(event)
            finally:
                window.hide()
                window.deleteLater()


if __name__ == '__main__':
    unittest.main()
