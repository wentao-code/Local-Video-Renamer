import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.backend.client import BackendClient
from app.backend.service import BackendService
from app.core.video_filter_rules import FILTER_FIELD_CO_STAR_CODE, FILTER_FIELD_TITLE
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.video_category_viewer import VideoCategoryViewerWindow
from app.services.video import VideoFilterService


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


class _BackendClientStub:
    base_url = 'http://127.0.0.1:65535'
    timeout = 30


class _RefreshClientStub:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def list_videos_requiring_manual_category_snapshot(self, force_refresh=False):
        self.calls.append(bool(force_refresh))
        return {
            'videos': [],
            'staged_count': 0,
            'refreshed_at': '2026-07-07 11:05:00' if force_refresh else '2026-07-07 11:00:00',
            'refresh_duration_ms': 7000 if force_refresh else 3000,
            'refresh_duration_text': '7秒' if force_refresh else '3秒',
            'cache_hit': not force_refresh,
        }

    @staticmethod
    def list_videos_requiring_manual_category():
        return {
            'videos': [],
            'staged_count': 0,
        }


class _FilterServiceStub:
    def __init__(self, settings=None):
        self._settings = dict(settings or {})
        self._service = VideoFilterService(settings_loader=self.load_settings)

    def load_settings(self):
        return dict(self._settings)

    def filter_video_rows(self, rows, settings=None):
        return self._service.filter_video_rows(rows, settings=settings)


class VideoCategoryViewerWindowTest(unittest.TestCase):
    def test_filter_button_renders_in_bottom_toolbar_and_opens_dialog_modelessly(self):
        created = {}

        class FakeFilterDialog:
            def __init__(self, parent=None):
                created['parent'] = parent
                created['instance'] = self

            def setAttribute(self, *_args, **_kwargs):
                created['set_attribute_called'] = True

            def show(self):
                created['shown'] = True

            def raise_(self):
                created['raised'] = True

            def activateWindow(self):
                created['activated'] = True

        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
            patch('app.gui.video_category_viewer.VideoFilterDialog', FakeFilterDialog),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                bottom_layout = window.layout().itemAt(2).layout()
                self.assertGreaterEqual(bottom_layout.indexOf(window.btn_filter_rules), 0)

                window.btn_filter_rules.click()

                self.assertIs(created.get('parent'), window)
                self.assertIs(window._filter_dialog, created.get('instance'))
                self.assertTrue(created.get('set_attribute_called'))
                self.assertTrue(created.get('shown'))
                self.assertTrue(created.get('raised'))
                self.assertTrue(created.get('activated'))
            finally:
                window.hide()
                window.deleteLater()

    def test_startup_load_uses_snapshot_then_background_refresh(self):
        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                self.assertEqual(window.refresh_client.calls, [False, True])
                self.assertIn('2026-07-07 11:05:00', window.last_refreshed_label.text())
                self.assertIn('7秒', window.last_refresh_duration_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_filter_save_reuses_snapshot_instead_of_forcing_source_refresh(self):
        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                window.show()
                window.refresh_client.calls.clear()

                window.on_filter_rules_saved()

                self.assertEqual(window.refresh_client.calls, [False])
            finally:
                window.hide()
                window.deleteLater()

    def test_disabled_batch_and_sync_buttons_explain_their_requirements(self):
        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                self.assertFalse(window.btn_sync.isEnabled())
                self.assertIn('暂存', window.btn_sync.toolTip())
                self.assertFalse(window.btn_batch_single.isEnabled())
                self.assertIn('选择', window.btn_batch_single.toolTip())
                self.assertIn('当前显示', window.btn_tier_first.toolTip())
            finally:
                window.hide()
                window.deleteLater()

    def test_deferred_startup_refresh_keeps_allow_deferred_close_flag(self):
        captured = []

        def _capture_task(self, task, success_handler, error_title=None, block_ui=True, allow_deferred_close=False):
            captured.append(
                {
                    'block_ui': bool(block_ui),
                    'allow_deferred_close': bool(allow_deferred_close),
                }
            )
            success_handler(task())
            return True

        with (
            patch('app.gui.video_category_viewer.BackendClient', _RefreshClientStub),
            patch.object(AsyncTaskHostMixin, 'start_async_task', _capture_task),
        ):
            window = VideoCategoryViewerWindow(_BackendClientStub())
            try:
                captured.clear()
                window._deferred_force_refresh = True
                window._deferred_silent_errors = True
                window._deferred_block_ui = False
                window._deferred_allow_deferred_close = True

                window._perform_deferred_load()

                self.assertEqual(len(captured), 1)
                self.assertFalse(captured[0]['block_ui'])
                self.assertTrue(captured[0]['allow_deferred_close'])
            finally:
                window.hide()
                window.deleteLater()


class BackendServiceVideoCategorySnapshotTest(unittest.TestCase):
    def _build_service(self, snapshot_file, filter_settings=None):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.video_filter_service = _FilterServiceStub(filter_settings)
        service._snapshot_lock = None
        service._video_category_snapshot_file_lock = None
        service._video_category_snapshot_file = Path(snapshot_file)
        service._video_category_snapshot_filter_fingerprint = BackendService._build_video_category_snapshot_filter_fingerprint(
            filter_settings
        )
        service._video_category_snapshot_category_fingerprint = (
            BackendService._build_video_category_snapshot_category_fingerprint(filter_settings)
        )
        service._video_category_overview_snapshot = None
        return service

    def test_display_filter_change_reuses_raw_candidate_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'video_category_snapshot.json'
            settings = {'rules': {FILTER_FIELD_TITLE: []}}
            service = self._build_service(snapshot_file, filter_settings=settings)
            service.video_filter_service._settings = settings
            service._current_video_category_source_version = lambda: 'db-v1'
            calls = []
            service.list_unfiltered_videos_requiring_manual_category = lambda: calls.append(True) or {
                'videos': [
                    {'code': 'IPX-001', 'title': 'keep', 'javtxt_enrichment_status': '已补全'},
                    {'code': 'IPX-002', 'title': 'hide me', 'javtxt_enrichment_status': '已补全'},
                ],
                'staged_count': 0,
            }

            BackendService.list_videos_requiring_manual_category_snapshot(service)
            settings['rules'][FILTER_FIELD_TITLE] = ['hide']
            service.video_filter_service._settings = settings
            result = BackendService.list_videos_requiring_manual_category_snapshot(service)

            self.assertEqual(calls, [True])
            self.assertTrue(result['cache_hit'])
            self.assertEqual([row['code'] for row in result['videos']], ['IPX-001'])

    def test_category_filter_change_rebuilds_raw_candidate_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'video_category_snapshot.json'
            settings = {'rules': {FILTER_FIELD_CO_STAR_CODE: []}}
            service = self._build_service(snapshot_file, filter_settings=settings)
            service.video_filter_service._settings = settings
            service._current_video_category_source_version = lambda: 'db-v1'
            calls = []
            service.list_unfiltered_videos_requiring_manual_category = lambda: calls.append(True) or {
                'videos': [],
                'staged_count': 0,
            }

            BackendService.list_videos_requiring_manual_category_snapshot(service)
            settings['rules'][FILTER_FIELD_CO_STAR_CODE] = ['ABC']
            service.video_filter_service._settings = settings
            result = BackendService.list_videos_requiring_manual_category_snapshot(service)

            self.assertEqual(calls, [True, True])
            self.assertFalse(result['cache_hit'])

    def test_snapshot_persists_across_service_restarts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'video_category_snapshot.json'
            first_service = self._build_service(snapshot_file)
            timestamps = iter(['2026-07-07 11:10:00'])
            first_service._current_snapshot_timestamp = lambda: next(timestamps)
            first_service.list_unfiltered_videos_requiring_manual_category = lambda: {
                'videos': [{'code': 'IPX-001', 'title': 'A'}],
                'staged_count': 2,
            }

            first = BackendService.list_videos_requiring_manual_category_snapshot(first_service)

            self.assertFalse(first['cache_hit'])
            self.assertEqual(first['refreshed_at'], '2026-07-07 11:10:00')

            second_service = self._build_service(snapshot_file)
            second_service.list_unfiltered_videos_requiring_manual_category = lambda: (_ for _ in ()).throw(
                AssertionError('should reuse persisted video category snapshot')
            )
            BackendService._load_video_category_snapshot(second_service)

            second = BackendService.list_videos_requiring_manual_category_snapshot(second_service)

            self.assertTrue(second['cache_hit'])
            self.assertEqual(second['refreshed_at'], '2026-07-07 11:10:00')
            self.assertEqual(second['videos'][0]['code'], 'IPX-001')

    def test_snapshot_rebuilds_when_candidate_source_version_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'video_category_snapshot.json'
            service = self._build_service(snapshot_file)
            source_versions = iter(['db-v1', 'db-v2', 'db-v2'])
            service._current_video_category_source_version = lambda: next(source_versions)
            calls = []
            service.list_unfiltered_videos_requiring_manual_category = lambda: calls.append(True) or {
                'videos': [],
                'staged_count': 0,
            }

            BackendService.list_videos_requiring_manual_category_snapshot(service)
            result = BackendService.list_videos_requiring_manual_category_snapshot(service)

            self.assertEqual(calls, [True, True])
            self.assertFalse(result['cache_hit'])

    def test_snapshot_without_filter_fingerprint_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_file = Path(temp_dir) / 'video_category_snapshot.json'
            snapshot_file.write_text(
                json.dumps(
                    {
                        'version': 1,
                        'overview_snapshot': {
                            'videos': [],
                            'staged_count': 0,
                            'source_version': 'db-v1',
                            'refreshed_at': '2026-07-07 11:10:00',
                        },
                    }
                ),
                encoding='utf-8',
            )
            service = self._build_service(snapshot_file, filter_settings={'co_star_codes': ['ABC']})

            BackendService._load_video_category_snapshot(service)

            self.assertIsNone(service._video_category_overview_snapshot)

    def test_stage_rejects_codes_outside_manual_category_candidates(self):
        service = BackendService.__new__(BackendService)
        service.ensure_database_loaded = lambda: None
        service.list_videos_requiring_manual_category = lambda: {'videos': []}

        with self.assertRaisesRegex(ValueError, '待人工分类'):
            BackendService.stage_video_category(service, 'INVALID-001', '单体作品')


class BackendClientVideoCategorySnapshotTest(unittest.TestCase):
    def test_list_videos_requiring_manual_category_snapshot_passes_refresh_query(self):
        client = BackendClient(base_url='http://127.0.0.1:8766', timeout=30)
        calls = []

        def fake_get(path, timeout=None):
            calls.append((path, timeout))
            return {'videos': [], 'staged_count': 0, 'refreshed_at': '2026-07-07 11:15:00'}

        client._get = fake_get

        result = client.list_videos_requiring_manual_category_snapshot(force_refresh=True)

        self.assertEqual(result['refreshed_at'], '2026-07-07 11:15:00')
        self.assertEqual(
            calls,
            [('/database/videos/manual-category?refresh=1', 120)],
        )


if __name__ == '__main__':
    unittest.main()
