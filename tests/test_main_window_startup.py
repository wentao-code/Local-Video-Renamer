import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from app.gui import main_window


class MainWindowStartupTest(unittest.TestCase):
    def test_configure_qt_application_enables_high_dpi_attributes(self):
        with patch('app.gui.main_window.QCoreApplication.setAttribute') as set_attribute_mock:
            main_window.configure_qt_application()

        set_attribute_mock.assert_any_call(Qt.AA_EnableHighDpiScaling, True)
        set_attribute_mock.assert_any_call(Qt.AA_UseHighDpiPixmaps, True)

    def test_configure_application_font_replaces_suspicious_small_default_font(self):
        class _AppStub:
            def __init__(self):
                self._font = QFont('SimSun', 6)
                self.applied_font = None

            def font(self):
                return self._font

            def setFont(self, font):
                self.applied_font = QFont(font)

        app = _AppStub()
        replacement_font = QFont('Tahoma', 9)

        with patch('app.gui.main_window._resolve_windows_message_font', return_value=replacement_font):
            main_window.configure_application_font(app)

        self.assertIsNotNone(app.applied_font)
        self.assertEqual(app.applied_font.family(), 'Tahoma')
        self.assertEqual(app.applied_font.pointSize(), 9)

    def test_configure_application_font_keeps_normal_default_font(self):
        class _AppStub:
            def __init__(self):
                self._font = QFont('Microsoft YaHei UI', 9)
                self.applied_font = None

            def font(self):
                return self._font

            def setFont(self, font):
                self.applied_font = QFont(font)

        app = _AppStub()

        with patch('app.gui.main_window._resolve_windows_message_font', return_value=QFont('Tahoma', 9)):
            main_window.configure_application_font(app)

        self.assertIsNone(app.applied_font)

    def test_run_snapshot_refresh_cycle_refreshes_libraries_in_order(self):
        calls = []

        refresh_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: calls.append(('actor', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: calls.append(('code_prefix', kwargs)),
            get_data_center_summary=lambda **kwargs: calls.append(('data_center', kwargs)),
        )
        stub = SimpleNamespace(snapshot_refresh_running=False)

        main_window.VidNormApp._run_snapshot_refresh_cycle(stub, refresh_client=refresh_client)

        self.assertFalse(stub.snapshot_refresh_running)
        self.assertEqual(
            [item[0] for item in calls],
            ['actor', 'code_prefix', 'data_center'],
        )
        for _name, kwargs in calls:
            self.assertTrue(kwargs.get('force_refresh'))

    def test_run_snapshot_refresh_cycle_emits_target_labels_in_order(self):
        progress_payloads = []
        refresh_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: None,
            list_code_prefixes_snapshot=lambda **kwargs: None,
            get_data_center_summary=lambda **kwargs: None,
        )
        stub = SimpleNamespace(snapshot_refresh_running=False)

        main_window.VidNormApp._run_snapshot_refresh_cycle(
            stub,
            progress_callback=lambda payload: progress_payloads.append(dict(payload or {})),
            refresh_client=refresh_client,
        )

        self.assertEqual(
            [payload.get('target_key') for payload in progress_payloads],
            ['actor_library', 'code_prefix_library', 'data_center'],
        )

    def test_schedule_snapshot_refresh_cycle_starts_runner_when_idle(self):
        started = []
        created_worker = object()
        stub = SimpleNamespace(
            snapshot_refresh_running=False,
            snapshot_refresh_task_runner=None,
            snapshot_refresh_worker=None,
            backend_client=SimpleNamespace(),
            _has_active_enrichment_plan=lambda: False,
            _create_snapshot_refresh_worker=lambda: created_worker,
            _on_snapshot_refresh_finished=lambda _result=None: None,
            _on_snapshot_refresh_failed=lambda _error=None: None,
        )

        class _Runner:
            def __init__(self, parent, worker, success_handler, error_handler, cleanup_handler=None):
                started.append(('init', parent, worker, success_handler, error_handler, cleanup_handler))

            def start(self):
                started.append('start')

        with patch('app.gui.main_window.GuiTaskRunner', _Runner):
            main_window.VidNormApp.schedule_snapshot_refresh_cycle(stub)

        self.assertTrue(stub.snapshot_refresh_running)
        self.assertIs(stub.snapshot_refresh_worker, created_worker)
        self.assertEqual(started[0][1], stub)
        self.assertIs(started[0][2], created_worker)
        self.assertEqual(started[-1], 'start')

    def test_schedule_snapshot_refresh_cycle_skips_while_enrichment_is_active(self):
        stub = SimpleNamespace(
            snapshot_refresh_running=False,
            _has_active_enrichment_plan=lambda: True,
        )

        result = main_window.VidNormApp.schedule_snapshot_refresh_cycle(stub)

        self.assertFalse(result)
        self.assertFalse(stub.snapshot_refresh_running)

    def test_snapshot_refresh_progress_updates_status_with_elapsed_seconds(self):
        snapshot_status = SimpleNamespace(text='')
        snapshot_status.setText = lambda value: setattr(snapshot_status, 'text', value)
        red_lamp = SimpleNamespace(style='')
        red_lamp.setStyleSheet = lambda value: setattr(red_lamp, 'style', value)
        green_lamp = SimpleNamespace(style='')
        green_lamp.setStyleSheet = lambda value: setattr(green_lamp, 'style', value)
        elapsed_timer = SimpleNamespace(started=False)
        elapsed_timer.start = lambda: setattr(elapsed_timer, 'started', True)
        elapsed_timer.stop = lambda: setattr(elapsed_timer, 'started', False)
        stub = SimpleNamespace(
            snapshot_refresh_status_label=snapshot_status,
            snapshot_refresh_red_light_label=red_lamp,
            snapshot_refresh_green_light_label=green_lamp,
            snapshot_refresh_elapsed_timer=elapsed_timer,
            snapshot_refresh_current_target='',
            snapshot_refresh_started_at=0.0,
        )

        with patch('app.gui.main_window.time.time', return_value=100.0):
            main_window.VidNormApp._on_snapshot_refresh_progress(
                stub,
                {'target_label': 'code-prefix', 'elapsed_seconds': 0},
            )

        self.assertTrue(elapsed_timer.started)
        self.assertEqual(stub.snapshot_refresh_current_target, 'code-prefix')
        self.assertIn('code-prefix', snapshot_status.text)
        self.assertIn('#dc2626', red_lamp.style)
        self.assertIn('#cbd5e1', green_lamp.style)

        with patch('app.gui.main_window.time.time', return_value=108.4):
            main_window.VidNormApp.update_snapshot_refresh_elapsed(stub)

        self.assertIn('8', snapshot_status.text)

    def test_snapshot_refresh_finished_switches_to_green_light(self):
        snapshot_status = SimpleNamespace(text='')
        snapshot_status.setText = lambda value: setattr(snapshot_status, 'text', value)
        red_lamp = SimpleNamespace(style='')
        red_lamp.setStyleSheet = lambda value: setattr(red_lamp, 'style', value)
        green_lamp = SimpleNamespace(style='')
        green_lamp.setStyleSheet = lambda value: setattr(green_lamp, 'style', value)
        elapsed_timer = SimpleNamespace(started=True)
        elapsed_timer.start = lambda: setattr(elapsed_timer, 'started', True)
        elapsed_timer.stop = lambda: setattr(elapsed_timer, 'started', False)
        stub = SimpleNamespace(
            snapshot_refresh_running=True,
            snapshot_refresh_status_label=snapshot_status,
            snapshot_refresh_red_light_label=red_lamp,
            snapshot_refresh_green_light_label=green_lamp,
            snapshot_refresh_elapsed_timer=elapsed_timer,
            snapshot_refresh_started_at=100.0,
            snapshot_refresh_current_target='data-center',
            snapshot_refresh_worker=object(),
            snapshot_refresh_task_runner=object(),
        )

        with patch('app.gui.main_window.time.strftime', return_value='12:34:56'):
            main_window.VidNormApp._on_snapshot_refresh_finished(stub, {'success': True})

        self.assertFalse(stub.snapshot_refresh_running)
        self.assertFalse(elapsed_timer.started)
        self.assertEqual(stub.snapshot_refresh_current_target, '')
        self.assertIn('12:34:56', snapshot_status.text)
        self.assertIn('#cbd5e1', red_lamp.style)
        self.assertIn('#16a34a', green_lamp.style)
        self.assertIsNone(stub.snapshot_refresh_worker)
        self.assertIsNone(stub.snapshot_refresh_task_runner)

    def test_refresh_detail_snapshots_dispatches_explicit_full_refresh_task(self):
        captured = {}
        stub = SimpleNamespace(
            backend_client=SimpleNamespace(
                rebuild_detail_snapshots=lambda: {
                    'actor_total': 2,
                    'actor_refreshed': 2,
                    'code_prefix_total': 1,
                    'code_prefix_refreshed': 1,
                }
            ),
            start_async_task=lambda task, success_handler, error_title=None, block_ui=True: captured.update(
                {
                    'task_result': task(),
                    'success_handler': success_handler,
                    'error_title': error_title,
                    'block_ui': block_ui,
                }
            ),
            _on_refresh_detail_snapshots_finished=lambda result: result,
        )

        main_window.VidNormApp.refresh_detail_snapshots(stub)

        self.assertEqual(captured['task_result']['actor_refreshed'], 2)
        self.assertEqual(captured['task_result']['code_prefix_refreshed'], 1)
        self.assertEqual(captured['success_handler'], stub._on_refresh_detail_snapshots_finished)
        self.assertTrue(captured['block_ui'])


if __name__ == '__main__':
    unittest.main()
