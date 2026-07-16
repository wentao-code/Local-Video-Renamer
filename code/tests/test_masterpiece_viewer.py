import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtGui import QCloseEvent, QColor
from PyQt5.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.detail_summary_widgets import DetailSummaryGrid
from app.gui.masterpiece_viewer import MasterpieceDetailWindow, MasterpieceWindow
from app.gui.query_context import EntityReference, EntityType, QueryContext


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
                'avfan_enrichment_status': '已补全',
                'javtxt_enrichment_status': '已补全',
            },
            {
                'code': 'MISS-001',
                'title': 'Missing Second Source',
                'author': 'Beta',
                'medal': '',
                'medals': [],
                'avfan_enrichment_status': '已补全',
                'javtxt_enrichment_status': '未补全',
            }
        ]
        self.add_calls = []
        self.medal_calls = []
        self.detail_calls = []
        self.detail_refresh_flags = []
        self.enrich_calls = []
        self.actor_refresh_calls = 0
        self.entry_refresh_flags = []
        self.global_medal_refresh_flags = []
        self.global_medals = [
            {'name': 'Rookie', 'description': 'For debut-level standouts'},
            {'name': 'Evergreen', 'description': 'For long-running elite entries'},
        ]

    def list_masterpiece_entries(self, force_refresh=False):
        self.entry_refresh_flags.append(bool(force_refresh))
        return [dict(row) for row in self.entries]

    def refresh_masterpiece_actors(self):
        self.actor_refresh_calls += 1
        return {'blacklisted_count': 0, 'removed_count': 0}

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

    def list_global_medals(self, force_refresh=False):
        self.global_medal_refresh_flags.append(bool(force_refresh))
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
                'display_tags': 'Drama,Newcomer',
                'second_source_description': 'Second source plot description',
                'second_source_title': 'Second Source Title',
                'second_source_actors': 'Alice Beta',
                'second_source_tags': 'Drama,Newcomer',
                'first_source_duration': '130 分钟',
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
                        'actor_id': 'avfan-1',
                        'binghuo_person_id': 'binghuo-1',
                        'update_status_text': '正在更新',
                        'local_video_count': 2,
                        'web_total_videos': 915,
                        'appearance_code_count': 138,
                        'code_prefix_library_count': 33,
                        'web_update_frequency_text': '3.64 部/月',
                        'web_enrichment_status': '天限阁: 已补全 | 辛聚谷: 已补全 | 并火: 无搜索结果 | 保木: 无搜索结果',
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

    def enrich_masterpiece_detail(self, code):
        self.enrich_calls.append(code)
        return self.get_masterpiece_detail_snapshot(code, force_refresh=True)


class MasterpieceViewerTest(unittest.TestCase):
    def test_window_loads_entries(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                self.assertEqual(window.table.rowCount(), 2)
                self.assertEqual(window.table.item(0, 0).text(), 'PFSA-001')
                self.assertFalse(window.medal_sidebar.medal_buttons['Rookie'].isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_refresh_loads_masterpiece_actor_registry_before_entries(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                window.btn_refresh.click()
                self.assertEqual(backend.actor_refresh_calls, 2)
                self.assertEqual(backend.entry_refresh_flags, [False, True])
                self.assertEqual(backend.global_medal_refresh_flags, [False, False])
            finally:
                window.hide()
                window.deleteLater()

    def test_window_marks_fully_enriched_codes_purple(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                self.assertEqual(window.table.item(0, 0).foreground().color(), QColor('#7b1fa2'))
                self.assertNotEqual(window.table.item(1, 0).foreground().color(), QColor('#7b1fa2'))
            finally:
                window.hide()
                window.deleteLater()

    def test_window_adds_new_code_then_enters_sidebar_edit_mode(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                window.code_input.setText('ipx-001')
                window.handle_add_entry()

                self.assertEqual(backend.add_calls, ['IPX-001'])
                self.assertEqual(backend.medal_calls, [])
                self.assertEqual(window.active_medal_code, 'IPX-001')
                new_row_index = window.table.rowCount() - 1
                self.assertEqual(window.table.cellWidget(new_row_index, 4).text(), '确认')
                self.assertTrue(window.medal_sidebar.medal_buttons['Rookie'].isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_window_updates_medals_via_sidebar_selection(self):
        backend = MasterpieceBackendStub()

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceWindow(backend)
            try:
                sidebar = window.medal_sidebar
                action_button = window.table.cellWidget(0, 4)
                action_button.click()

                self.assertEqual(action_button.text(), '确认')
                self.assertTrue(sidebar.medal_buttons['Rookie'].isChecked())

                sidebar.medal_buttons['Rookie'].click()
                sidebar.medal_buttons['Evergreen'].click()
                action_button.click()

                self.assertEqual(backend.medal_calls, [('PFSA-001', 'Evergreen')])
                self.assertEqual(window.table.cellWidget(0, 4).text(), '添加')
                self.assertFalse(window.medal_sidebar.medal_buttons['Rookie'].isEnabled())
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_hides_reference_shortcuts_and_summary_header(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                self.assertEqual(backend.detail_refresh_flags, [False, True])
                self.assertEqual(backend.detail_calls, ['PFSA-001', 'PFSA-001'])
                self.assertIn('2026-07-07 09:32:00', window.last_refreshed_label.text())
                group_titles = {group.title() for group in window.findChildren(QGroupBox)}
                self.assertNotIn(window._source_title('video_library'), group_titles)
                self.assertNotIn(window._source_title('actor_library'), group_titles)
                self.assertNotIn(window._source_title('code_prefix_library'), group_titles)

                self.assertFalse(hasattr(window, 'reference_buttons'))
                self.assertFalse(hasattr(window, 'summary_label'))
                self.assertNotIn('详情直达:', [label.text() for label in window.findChildren(QLabel)])
                self.assertIn('Alice', window.actor_detail_buttons)
                self.assertEqual(window.actor_detail_buttons['Alice'].text(), '详情')
                self.assertIn('Second source plot description', window.second_source_label.text())
                self.assertIn('130 分钟', window.first_source_label.text())
                self.assertIn('Alice', window.actor_details_label.text())
                self.assertIn('生日: 2000/4/10', window.actor_details_label.text())
                self.assertIn('天限阁ID: avfan-1', window.actor_details_label.text())
                self.assertIn('并火 ID: binghuo-1', window.actor_details_label.text())
                self.assertIn('演员等级: S', window.actor_details_label.text())
                self.assertIn('更新状态: 正在更新', window.actor_details_label.text())
                self.assertIn('年龄: 24', window.actor_details_label.text())
                self.assertIn('出演年龄: 24', window.actor_details_label.text())
                self.assertIn('身高: 168', window.actor_details_label.text())
                self.assertIn('本地视频总数: 2', window.actor_details_label.text())
                self.assertIn('网页作品总数: 915', window.actor_details_label.text())
                self.assertIn('出演番号数量: 138', window.actor_details_label.text())
                self.assertIn('番号库中数量: 33', window.actor_details_label.text())
                self.assertIn('三围: 88/59/89', window.actor_details_label.text())
                self.assertIn('罩杯: E', window.actor_details_label.text())
                self.assertIn('更新频率: 3.64 部/月', window.actor_details_label.text())
                self.assertIn('补全状态: 天限阁: 已补全', window.actor_details_label.text())
                self.assertIn('Beta', window.actor_details_label.text())
                self.assertIn('Alice', window.collaborator_tables)
                self.assertEqual(window.collaborator_tables['Alice'].columnCount(), 6)
                self.assertEqual(window.collaborator_tables['Alice'].rowCount(), 2)
                self.assertEqual(window.collaborator_tables['Alice'].item(0, 0).text(), 'Carol x3')
                self.assertEqual(window.collaborator_tables['Alice'].item(1, 0).text(), 'Iris x1')
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_switches_to_selected_masterpiece_context(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                context = QueryContext(entity=EntityReference(EntityType.MASTERPIECE, 'MISS-001'))

                window.apply_query_context(context)

                self.assertEqual(window.code, 'MISS-001')
                self.assertIn('MISS-001', window.windowTitle())
                self.assertEqual(backend.detail_calls[-1], 'MISS-001')
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_ignores_previous_masterpiece_response_after_switch(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                window.apply_query_context(
                    QueryContext(entity=EntityReference(EntityType.MASTERPIECE, 'MISS-001'))
                )
                current_detail = dict(window.detail)

                window._on_detail_loaded(
                    {
                        'detail': {'code': 'PFSA-001', 'display_title': 'Old detail'},
                        'request_token': 1,
                        'request_code': 'PFSA-001',
                    }
                )

                self.assertEqual(window.code, 'MISS-001')
                self.assertEqual(window.detail, current_detail)
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_renders_source_blocks_one_above_two_and_actor_union(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                self.assertTrue(window.detail_scroll_area.widgetResizable())
                self.assertIs(window.detail_scroll_area.widget(), window.detail_scroll_widget)
                self.assertLess(
                    window.detail_scroll_layout.indexOf(window.first_source_group),
                    window.detail_scroll_layout.indexOf(window.second_source_group),
                )
                self.assertLess(
                    window.detail_scroll_layout.indexOf(window.second_source_group),
                    window.detail_scroll_layout.indexOf(window.actor_details_group),
                )
                self.assertIn('第一套系统', window.first_source_group.title())
                self.assertIn('Perfect First Scene', window.first_source_label.text())
                self.assertIn('130 分钟', window.first_source_label.text())
                self.assertIn('Drama,Newcomer', window.first_source_label.text())
                self.assertIn('Alice', window.first_source_label.text())
                self.assertIn('第二套系统', window.second_source_group.title())
                self.assertIn('Second Source Title', window.second_source_label.text())
                self.assertIn('Alice Beta', window.second_source_label.text())
                self.assertIn('Drama,Newcomer', window.second_source_label.text())
                self.assertIn('Second source plot description', window.second_source_label.text())
                self.assertIn('演员基础信息', window.actor_details_group.title())
                self.assertIn('Alice', window.actor_details_label.text())
                self.assertEqual(window.actor_details_label.text().count('Alice'), 1)
                self.assertIn('Beta', window.actor_details_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_uses_actor_detail_grid_layout_for_actor_basic_info(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                self.assertIn('Alice', window.actor_detail_grids)
                basic_grid = window.actor_detail_grids['Alice']['basic']
                measurements_grid = window.actor_detail_grids['Alice']['measurements']
                status_grid = window.actor_detail_grids['Alice']['status']

                self.assertIsInstance(basic_grid, DetailSummaryGrid)
                self.assertEqual(basic_grid.columns, 4)
                self.assertEqual(basic_grid.value_labels['name'].text(), 'Alice')
                self.assertEqual(basic_grid.value_labels['actor_id'].text(), 'avfan-1')
                self.assertEqual(basic_grid.value_labels['binghuo_person_id'].text(), 'binghuo-1')
                self.assertEqual(basic_grid.value_labels['local_video_count'].text(), '2')
                self.assertEqual(measurements_grid.value_labels['measurements'].text(), '88/59/89')
                self.assertIn('天限阁: 已补全', status_grid.value_labels['web_enrichment_status'].text())
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_actor_detail_button_opens_actor_detail_page(self):
        backend = MasterpieceBackendStub()
        opened = []

        class FakeActorDetailViewerWindow:
            def __init__(self, backend_client, actor_name, parent=None):
                opened.append((backend_client, actor_name, parent))

            def exec_(self):
                opened.append('exec')
                return 0

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task), patch(
            'app.gui.masterpiece_viewer.ActorDetailViewerWindow',
            FakeActorDetailViewerWindow,
        ):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                self.assertIn('Alice', window.actor_detail_buttons)
                window.actor_detail_buttons['Alice'].click()

                self.assertEqual(opened[0], (backend, 'Alice', window))
                self.assertEqual(opened[1], 'exec')
            finally:
                window.hide()
                window.deleteLater()

    def test_detail_window_enrich_button_runs_both_sources_and_refreshes(self):
        backend = MasterpieceBackendStub()
        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = MasterpieceDetailWindow(backend, 'PFSA-001')
            try:
                window.handle_enrich()

                self.assertEqual(backend.enrich_calls, ['PFSA-001'])
                self.assertEqual(backend.detail_refresh_flags, [False, True, True])
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
