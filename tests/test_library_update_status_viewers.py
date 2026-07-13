import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_viewer import CodePrefixViewerWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, *_args, **_kwargs):
    success_handler(task())
    return True


class _BackendStub:
    def list_actors_snapshot(self, **_kwargs):
        return {'actors': [], 'total_count': 0, 'refreshed_at': '', 'refresh_duration_text': ''}

    def list_code_prefixes_snapshot(self, **_kwargs):
        return {'prefixes': [], 'total_count': 0, 'refreshed_at': '', 'refresh_duration_text': ''}


def test_actor_name_color_tracks_update_status():
    with (
        patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
        patch('app.gui.actor_viewer.load_actor_library_settings', return_value={'sort_field': 'name', 'sort_order': 'asc'}),
        patch('app.gui.actor_viewer.save_actor_library_settings'),
    ):
        window = ActorViewerWindow(_BackendStub())
        try:
            window.render_rows([
                {'name': 'Active', 'update_status': 'active'},
                {'name': 'Suspect', 'update_status': 'suspect'},
                {'name': 'Inactive', 'update_status': 'inactive'},
            ])
            assert window.table.item(0, 0).foreground().color().name() == '#16a34a'
            assert window.table.item(1, 0).foreground().color().name() == '#ca8a04'
            assert window.table.item(2, 0).foreground().color().name() == '#6b7280'
        finally:
            window.deleteLater()


def test_code_prefix_color_tracks_update_status():
    with (
        patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
        patch('app.gui.code_prefix_viewer.load_code_prefix_library_settings', return_value={'sort_field': 'prefix', 'sort_order': 'asc'}),
        patch('app.gui.code_prefix_viewer.save_code_prefix_library_settings'),
    ):
        window = CodePrefixViewerWindow(_BackendStub())
        try:
            window.render_rows([
                {'prefix': 'AAA', 'update_status': 'active'},
                {'prefix': 'BBB', 'update_status': 'suspect'},
                {'prefix': 'CCC', 'update_status': 'inactive'},
            ])
            assert window.table.item(0, 0).foreground().color().name() == '#16a34a'
            assert window.table.item(1, 0).foreground().color().name() == '#ca8a04'
            assert window.table.item(2, 0).foreground().color().name() == '#6b7280'
        finally:
            window.deleteLater()
