import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from app.gui import main_window

_APP = QApplication.instance() or QApplication([])


def _process_events(rounds=5):
    for _ in range(rounds):
        _APP.processEvents()


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
            ['actor', 'code_prefix'],
        )
        self.assertEqual(calls[0][1], {'force_refresh': True, 'include_update_status': False})
        for _name, kwargs in calls[1:]:
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
            ['actor_library', 'code_prefix_library'],
        )

    def test_run_snapshot_refresh_cycle_builds_twenty_minute_refresh_client_by_default(self):
        calls = []
        refresh_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: calls.append(('actor', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: calls.append(('code_prefix', kwargs)),
            get_data_center_summary=lambda **kwargs: calls.append(('data_center', kwargs)),
        )
        stub = SimpleNamespace(snapshot_refresh_running=False, backend_client=SimpleNamespace(timeout=30))

        def fake_build_refresh_client(backend_client, minimum_timeout=90):
            calls.append(('build_client', backend_client, minimum_timeout))
            return refresh_client

        with patch('app.gui.main_window._build_refresh_client', fake_build_refresh_client):
            main_window.VidNormApp._run_snapshot_refresh_cycle(stub)

        self.assertEqual(calls[0], ('build_client', stub.backend_client, 1200))

    def test_start_snapshot_refresh_scheduler_delays_startup_refresh(self):
        started = []
        stub = SimpleNamespace(
            snapshot_refresh_timer=SimpleNamespace(start=lambda: started.append('timer')),
            schedule_snapshot_refresh_cycle=lambda: None,
            enqueue_startup_refresh_tasks=lambda: started.append('startup-refresh'),
        )

        with patch('app.gui.main_window.QTimer.singleShot') as single_shot:
            main_window.VidNormApp.start_snapshot_refresh_scheduler(stub)

        self.assertEqual(started, ['timer'])
        delay_ms, callback = single_shot.call_args.args
        self.assertGreaterEqual(delay_ms, 15000)
        callback()
        self.assertEqual(started, ['timer', 'startup-refresh'])

    def test_enqueue_startup_refresh_tasks_adds_interface_refreshes_after_snapshot_refresh(self):
        task_titles = []
        calls = []
        recorded = []
        backend_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: calls.append(('actors', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: calls.append(('prefixes', kwargs)),
            get_data_center_summary=lambda **kwargs: calls.append(('data_center', kwargs)),
            list_videos_requiring_manual_category_snapshot=lambda **kwargs: calls.append(('video_category', kwargs)),
            get_path_library_snapshot=lambda **kwargs: calls.append(('path_library', kwargs)),
            list_queen_library_snapshot=lambda **kwargs: calls.append(('queen_library', kwargs)),
            list_queen_keywords_snapshot=lambda **kwargs: calls.append(('queen_keywords', kwargs)),
            get_queen_library_stats=lambda: calls.append(('queen_stats', {})),
            list_masterpiece_entries=lambda: calls.append(('masterpiece', {})),
            list_global_medals=lambda: calls.append(('medals', {})),
            list_canglangge_candidates_snapshot=lambda **kwargs: calls.append(('canglangge', kwargs)),
        )
        stub = SimpleNamespace(
            backend_client=backend_client,
            _load_startup_refresh_history=lambda: {},
            _should_run_startup_refresh_task=lambda task_key, history, now=None: True,
            _record_startup_refresh_completion=lambda task_key, task_title, completed_at=None: recorded.append(
                (task_key, task_title)
            ),
            _start_queued_gui_runner=lambda title, worker_factory, success_handler, error_handler, **kwargs: (
                task_titles.append(title),
                success_handler(worker_factory().task()),
                True,
            )[-1],
            _on_startup_refresh_task_finished=lambda _result: None,
            _on_startup_refresh_task_failed=lambda _message: None,
        )

        main_window.VidNormApp.enqueue_startup_refresh_tasks(stub)

        self.assertEqual(
            task_titles,
            [
                '启动刷新 演员库',
                '启动刷新 番号库',
                '启动刷新 数据中心',
                '启动刷新 视频分类',
                '启动刷新 路径库',
                '启动刷新 女王库',
                '启动刷新 名作堂',
                '启动刷新 勋章堂',
                '启动刷新 沧浪阁',
            ],
        )
        self.assertIn(('actors', {'force_refresh': True, 'include_update_status': False}), calls)
        self.assertIn(('prefixes', {'force_refresh': True}), calls)
        self.assertIn(('data_center', {'force_refresh': True}), calls)
        self.assertIn(('video_category', {'force_refresh': True}), calls)
        self.assertIn(('path_library', {'force_refresh': True}), calls)
        self.assertIn(('queen_library', {'force_refresh': True}), calls)
        self.assertIn(('queen_keywords', {'force_refresh': True}), calls)
        self.assertIn(('queen_stats', {}), calls)
        self.assertIn(('masterpiece', {}), calls)
        self.assertIn(('medals', {}), calls)
        self.assertIn(('canglangge', {'force_refresh': True}), calls)
        self.assertEqual(
            recorded,
            [
                ('actor_library', '启动刷新 演员库'),
                ('code_prefix_library', '启动刷新 番号库'),
                ('data_center', '启动刷新 数据中心'),
                ('video_category', '启动刷新 视频分类'),
                ('path_library', '启动刷新 路径库'),
                ('queen_library', '启动刷新 女王库'),
                ('masterpiece', '启动刷新 名作堂'),
                ('global_medals', '启动刷新 勋章堂'),
                ('canglangge', '启动刷新 沧浪阁'),
            ],
        )

    def test_enqueue_startup_refresh_tasks_skips_recent_tasks_and_records_only_started_ones(self):
        task_titles = []
        recorded = []
        backend_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: {'actors': []},
            list_code_prefixes_snapshot=lambda **kwargs: {'prefixes': []},
            get_data_center_summary=lambda **kwargs: {'stats': {}},
            list_videos_requiring_manual_category_snapshot=lambda **kwargs: {'videos': []},
            get_path_library_snapshot=lambda **kwargs: {'paths': []},
            list_queen_library_snapshot=lambda **kwargs: {'queens': []},
            list_queen_keywords_snapshot=lambda **kwargs: {'keywords': []},
            get_queen_library_stats=lambda: {'queen_count': 0},
            list_masterpiece_entries=lambda: {'entries': []},
            list_global_medals=lambda: {'medals': []},
            list_canglangge_candidates_snapshot=lambda **kwargs: {'rows': []},
        )
        allowed_task_keys = {'code_prefix_library', 'queen_library'}
        stub = SimpleNamespace(
            backend_client=backend_client,
            _load_startup_refresh_history=lambda: {'actor_library': {'last_completed_at': '2026-07-12 10:00:00'}},
            _should_run_startup_refresh_task=lambda task_key, history, now=None: task_key in allowed_task_keys,
            _record_startup_refresh_completion=lambda task_key, task_title, completed_at=None: recorded.append(
                (task_key, task_title)
            ),
            _start_queued_gui_runner=lambda title, worker_factory, success_handler, error_handler, **kwargs: (
                task_titles.append(title),
                success_handler(worker_factory().task()),
                True,
            )[-1],
            _on_startup_refresh_task_finished=lambda _result: None,
            _on_startup_refresh_task_failed=lambda _message: None,
        )

        main_window.VidNormApp.enqueue_startup_refresh_tasks(stub)

        self.assertEqual(task_titles, ['启动刷新 番号库', '启动刷新 女王库'])
        self.assertEqual(
            recorded,
            [
                ('code_prefix_library', '启动刷新 番号库'),
                ('queen_library', '启动刷新 女王库'),
            ],
        )

    def test_enqueue_startup_refresh_tasks_uses_long_timeout_client_for_actor_code_prefix_data_center_and_video_category(self):
        backend_calls = []
        refresh_calls = []
        backend_client = SimpleNamespace(
            base_url='http://127.0.0.1:8766',
            timeout=30,
            list_actors_snapshot=lambda **kwargs: backend_calls.append(('actors', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: backend_calls.append(('prefixes', kwargs)),
            get_data_center_summary=lambda **kwargs: backend_calls.append(('data_center', kwargs)),
            list_videos_requiring_manual_category_snapshot=lambda **kwargs: backend_calls.append(('video_category', kwargs)),
            get_path_library_snapshot=lambda **kwargs: backend_calls.append(('path_library', kwargs)),
            list_queen_library_snapshot=lambda **kwargs: backend_calls.append(('queen_library', kwargs)),
            list_queen_keywords_snapshot=lambda **kwargs: backend_calls.append(('queen_keywords', kwargs)),
            get_queen_library_stats=lambda: backend_calls.append(('queen_stats', {})),
            list_masterpiece_entries=lambda: backend_calls.append(('masterpiece', {})),
            list_global_medals=lambda: backend_calls.append(('medals', {})),
            list_canglangge_candidates_snapshot=lambda **kwargs: backend_calls.append(('canglangge', kwargs)),
        )
        refresh_client = SimpleNamespace(
            list_actors_snapshot=lambda **kwargs: refresh_calls.append(('actors', kwargs)),
            list_code_prefixes_snapshot=lambda **kwargs: refresh_calls.append(('prefixes', kwargs)),
            get_data_center_summary=lambda **kwargs: refresh_calls.append(('data_center', kwargs)),
            list_videos_requiring_manual_category_snapshot=lambda **kwargs: refresh_calls.append(('video_category', kwargs)),
        )
        stub = SimpleNamespace(
            backend_client=backend_client,
            _load_startup_refresh_history=lambda: {},
            _should_run_startup_refresh_task=lambda task_key, history, now=None: True,
            _record_startup_refresh_completion=lambda task_key, task_title, completed_at=None: None,
            _start_queued_gui_runner=lambda title, worker_factory, success_handler, error_handler, **kwargs: (
                success_handler(worker_factory().task()),
                True,
            )[-1],
            _on_startup_refresh_task_finished=lambda _result: None,
            _on_startup_refresh_task_failed=lambda _message: None,
        )

        with patch('app.gui.main_window._build_refresh_client', return_value=refresh_client) as build_refresh_client:
            main_window.VidNormApp.enqueue_startup_refresh_tasks(stub)

        build_refresh_client.assert_called_once_with(
            backend_client,
            minimum_timeout=main_window.SNAPSHOT_REFRESH_REQUEST_TIMEOUT_SECONDS,
        )
        self.assertIn(('actors', {'force_refresh': True, 'include_update_status': False}), refresh_calls)
        self.assertIn(('prefixes', {'force_refresh': True}), refresh_calls)
        self.assertIn(('data_center', {'force_refresh': True}), refresh_calls)
        self.assertIn(('video_category', {'force_refresh': True}), refresh_calls)
        self.assertNotIn(('actors', {'force_refresh': True, 'include_update_status': False}), backend_calls)
        self.assertNotIn(('prefixes', {'force_refresh': True}), backend_calls)
        self.assertNotIn(('data_center', {'force_refresh': True}), backend_calls)
        self.assertNotIn(('video_category', {'force_refresh': True}), backend_calls)

    def test_should_run_startup_refresh_task_respects_88_hour_threshold(self):
        history = {
            'recent': {'last_completed_at': '2026-07-10 23:00:00'},
            'expired': {'last_completed_at': '2026-07-08 19:59:59'},
            'broken': {'last_completed_at': 'not-a-time'},
        }
        now = datetime(2026, 7, 12, 12, 0, 0)
        stub = SimpleNamespace()

        self.assertFalse(
            main_window.VidNormApp._should_run_startup_refresh_task(stub, 'recent', history, now=now)
        )
        self.assertTrue(
            main_window.VidNormApp._should_run_startup_refresh_task(stub, 'expired', history, now=now)
        )
        self.assertTrue(
            main_window.VidNormApp._should_run_startup_refresh_task(stub, 'missing', history, now=now)
        )
        self.assertTrue(
            main_window.VidNormApp._should_run_startup_refresh_task(stub, 'broken', history, now=now)
        )

    def test_record_startup_refresh_completion_persists_row_in_database(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / 'startup_refresh_test.db'
            stub = SimpleNamespace(
                _get_startup_refresh_history_db_path=lambda: db_path,
            )

            main_window.VidNormApp._record_startup_refresh_completion(
                stub,
                'actor_library',
                '启动刷新 演员库',
                completed_at='2026-07-12 12:34:56',
            )

            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    '''
                    SELECT task_key, task_title, last_completed_at
                    FROM startup_refresh_history
                    WHERE task_key = ?
                    ''',
                    ('actor_library',),
                ).fetchone()

            self.assertEqual(row, ('actor_library', '启动刷新 演员库', '2026-07-12 12:34:56'))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_schedule_snapshot_refresh_cycle_starts_runner_when_idle(self):
        started = []
        created_worker = object()
        stub = SimpleNamespace(
            snapshot_refresh_running=False,
            snapshot_refresh_queued=False,
            snapshot_refresh_task_runner=None,
            snapshot_refresh_worker=None,
            backend_client=SimpleNamespace(),
            _has_active_enrichment_plan=lambda: False,
            _create_snapshot_refresh_worker=lambda: created_worker,
            _on_snapshot_refresh_finished=lambda _result=None: None,
            _on_snapshot_refresh_failed=lambda _error=None: None,
            _cleanup_snapshot_refresh_attempt=lambda: None,
        )

        def fake_start_queued_runner(task_title, worker_factory, success_handler, error_handler, **kwargs):
            worker = worker_factory()
            started.append((task_title, worker, success_handler, error_handler, kwargs))
            kwargs['before_start']()
            kwargs['assign_runner'](worker, SimpleNamespace())
            return True

        stub._start_queued_gui_runner = fake_start_queued_runner

        main_window.VidNormApp.schedule_snapshot_refresh_cycle(stub)

        self.assertTrue(stub.snapshot_refresh_running)
        self.assertIs(stub.snapshot_refresh_worker, created_worker)
        self.assertEqual(started[0][0], '后台刷新快照')
        self.assertIs(started[0][1], created_worker)

    def test_schedule_snapshot_refresh_cycle_queues_even_while_enrichment_is_active(self):
        queued = []
        stub = SimpleNamespace(
            snapshot_refresh_running=False,
            snapshot_refresh_queued=False,
            _has_active_enrichment_plan=lambda: True,
            _on_snapshot_refresh_finished=lambda _result=None: None,
            _on_snapshot_refresh_failed=lambda _error=None: None,
            _cleanup_snapshot_refresh_attempt=lambda: None,
            _start_queued_gui_runner=lambda *args, **kwargs: queued.append((args, kwargs)) or True,
        )

        result = main_window.VidNormApp.schedule_snapshot_refresh_cycle(stub)

        self.assertTrue(result)
        self.assertTrue(stub.snapshot_refresh_queued)
        self.assertEqual(len(queued), 1)

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
            start_async_task=lambda task, success_handler, error_title=None, block_ui=True, **kwargs: captured.update(
                {
                    'task_result': task(),
                    'success_handler': success_handler,
                    'error_title': error_title,
                    'block_ui': block_ui,
                    'kwargs': dict(kwargs),
                }
            ),
            _on_refresh_detail_snapshots_finished=lambda result: result,
        )

        main_window.VidNormApp.refresh_detail_snapshots(stub)

        self.assertEqual(captured['task_result']['actor_refreshed'], 2)
        self.assertEqual(captured['task_result']['code_prefix_refreshed'], 1)
        self.assertEqual(captured['success_handler'], stub._on_refresh_detail_snapshots_finished)
        self.assertTrue(captured['block_ui'])
        self.assertEqual(captured['kwargs']['task_title'], '主界面 全量刷新快照')

    def test_task_queue_button_turns_green_when_queue_is_done(self):
        button = SimpleNamespace(style='')
        button.setStyleSheet = lambda value: setattr(button, 'style', value)
        stub = SimpleNamespace(btn_task_queue=button)

        main_window.VidNormApp._update_task_queue_indicator(stub, is_done=False)
        self.assertNotIn('#16a34a', button.style)

        main_window.VidNormApp._update_task_queue_indicator(stub, is_done=True)
        self.assertIn('#16a34a', button.style)

    # ── _queued_gui_task_runners lifecycle tests ──────────────────────────

    def test_runner_dict_holds_reference_after_ui_callback_clears_attribute(self):
        """核心场景：_on_snapshot_refresh_finished 清掉
        snapshot_refresh_task_runner = None 后，
        _queued_gui_task_runners 仍持有 runner 引用，
        handle_cleanup 能正常标记任务状态。"""
        from app.gui.task_queue import (
            TASK_STATUS_COMPLETED,
            TASK_STATUS_RUNNING,
            get_gui_task_queue,
        )

        queue = get_gui_task_queue()
        queue.reset_for_tests()
        try:
            # —— 模拟 _start_queued_gui_runner 的核心流程 ——
            # 用闭包重建 start_runner 和 handle_cleanup 的数据流
            runners_holder = {}
            cleanup_calls = []
            finished_handler_called = []
            failed_handler_called = []

            attempt_state = {'failed': False, 'message': ''}
            business_cleanup = lambda: cleanup_calls.append('business_cleanup')

            def handle_cleanup():
                try:
                    business_cleanup()
                    if attempt_state['failed']:
                        final = queue.mark_failed(record.task_id, attempt_state['message'])
                        if final:
                            failed_handler_called.append(attempt_state['message'])
                        return
                    queue.mark_completed(record.task_id)
                finally:
                    runners_holder.pop(record.task_id, None)

            # 模拟 GuiTaskRunner：将 handle_cleanup 挂到 mock 上
            mock_runner = SimpleNamespace(cleanup_handler=handle_cleanup)

            # 入队并立即调度（模拟 start_runner）
            record = queue.enqueue(
                '后台刷新快照', '主界面',
                lambda _r: None,  # start_callback 不会被调用，这里直接驱动
            )
            record.status = TASK_STATUS_RUNNING
            queue._running_task_id = record.task_id

            runners_holder[record.task_id] = mock_runner

            # 模拟 snapshot_refresh_task_runner 属性被清掉
            attr_runner = mock_runner
            attr_runner = None  # _on_snapshot_refresh_finished 的副作用
            self.assertIsNone(attr_runner)

            # runner 仍被 runners_holder 持有
            self.assertEqual(len(runners_holder), 1)

            # —— 模拟 thread.finished → _cleanup → handle_cleanup ——
            runners_holder[record.task_id].cleanup_handler()

            # 验证
            self.assertEqual(len(runners_holder), 0)
            self.assertEqual(cleanup_calls, ['business_cleanup'])

            records = queue.records()
            self.assertTrue(
                any(r.task_id == record.task_id and r.status == TASK_STATUS_COMPLETED
                    for r in records),
                '任务应被标记为已完成',
            )
        finally:
            queue.reset_for_tests()

    def test_runner_dict_released_on_failure_with_retry(self):
        """失败（未耗尽重试）：handle_cleanup 仍从 dict 移除 runner。"""
        from app.gui.task_queue import (
            TASK_STATUS_COMPLETED,
            TASK_STATUS_RUNNING,
            get_gui_task_queue,
        )

        queue = get_gui_task_queue()
        queue.reset_for_tests()
        try:
            runners_holder = {}
            attempt_state = {'failed': True, 'message': '网络超时'}
            failed_handler_called = []

            def handle_cleanup():
                try:
                    final = queue.mark_failed(record.task_id, attempt_state['message'])
                    if final:
                        failed_handler_called.append(attempt_state['message'])
                finally:
                    runners_holder.pop(record.task_id, None)

            mock_runner = SimpleNamespace(cleanup_handler=handle_cleanup)

            record = queue.enqueue('失败任务', '测试', lambda _r: None)
            record.status = TASK_STATUS_RUNNING
            queue._running_task_id = record.task_id

            runners_holder[record.task_id] = mock_runner

            # cleanup → mark_failed, 未耗尽重试 → 状态回到 WAITING
            runners_holder[record.task_id].cleanup_handler()

            self.assertEqual(len(runners_holder), 0)

            records = queue.records()
            matched = [r for r in records if r.task_id == record.task_id]
            self.assertTrue(matched)
            # 默认 max_attempts=5，1 次失败应等待重试
            self.assertNotEqual(matched[0].status, TASK_STATUS_COMPLETED)
        finally:
            queue.reset_for_tests()

    def test_runner_dict_cleanup_is_idempotent(self):
        """多次 handle_cleanup 不会因重复 pop 而崩溃。"""
        from app.gui.task_queue import get_gui_task_queue

        queue = get_gui_task_queue()
        queue.reset_for_tests()
        try:
            from app.gui.task_queue import TASK_STATUS_RUNNING

            runners_holder = {}

            def handle_cleanup():
                try:
                    queue.mark_completed(record.task_id)
                finally:
                    runners_holder.pop(record.task_id, None)

            mock_runner = SimpleNamespace(cleanup_handler=handle_cleanup)

            record = queue.enqueue('幂等测试', '测试', lambda _r: None)
            record.status = TASK_STATUS_RUNNING
            queue._running_task_id = record.task_id

            runners_holder[record.task_id] = mock_runner
            cleanup_fn = mock_runner.cleanup_handler  # 保存引用

            # 第一次
            cleanup_fn()
            self.assertEqual(len(runners_holder), 0)

            # 第二次：不会崩溃（handler 已直接持有，不需要再查 dict）
            cleanup_fn()
            self.assertEqual(len(runners_holder), 0)

            # 第三次：仍安全
            cleanup_fn()
            self.assertEqual(len(runners_holder), 0)
        finally:
            queue.reset_for_tests()

    def test_start_queued_gui_runner_stores_runner_in_dict(self):
        """通过拦截 enqueue 验证 _start_queued_gui_runner 把 runner 存入了 dict。"""
        from app.gui.task_queue import get_gui_task_queue

        queue = get_gui_task_queue()
        queue.reset_for_tests()
        try:
            stub = SimpleNamespace(_queued_gui_task_runners={})
            # Bind the unbound method with stub as self via partial.
            bound_start = partial(
                main_window.VidNormApp._start_queued_gui_runner, stub,
            )

            # Intercept enqueue so start_runner fires synchronously.
            original_enqueue = queue.enqueue

            def fake_enqueue(title, source, start_callback, max_attempts=5):
                record = original_enqueue(title, source, start_callback, max_attempts)
                start_callback(record)
                return record

            with patch.object(queue, 'enqueue', fake_enqueue), \
                 patch('app.gui.main_window.GuiTaskRunner') as MockRunner:
                bound_start(
                    '测试',
                    worker_factory=lambda: SimpleNamespace(),
                    finished_handler=lambda _r: None,
                    failed_handler=lambda _m: None,
                    source='测试',
                )

                # 验证 GuiTaskRunner 被调用
                self.assertTrue(MockRunner.called, 'GuiTaskRunner 应被构造')

                # 验证 runner 存入 _queued_gui_task_runners
                self.assertEqual(len(stub._queued_gui_task_runners), 1,
                                 'runner 应被存入 _queued_gui_task_runners')

                # 从 MockRunner.call_args 提取真实的 cleanup_handler
                # call_args[0] = (parent, worker, finished_h, failed_h, cleanup_h)
                real_cleanup = MockRunner.call_args[0][4]
                self.assertTrue(callable(real_cleanup),
                                'cleanup_handler 应为 callable')
                real_cleanup()

                # cleanup 后应从 dict 移除
                self.assertEqual(len(stub._queued_gui_task_runners), 0)
        finally:
            queue.reset_for_tests()

    def test_start_queued_gui_runner_keeps_runner_until_cleanup_marks_complete(self):
        from app.gui.task_queue import TASK_STATUS_COMPLETED, get_gui_task_queue

        queue = get_gui_task_queue()
        queue.reset_for_tests()
        try:
            states = []
            stub = SimpleNamespace(
                _queued_gui_task_runners={},
                snapshot_refresh_task_runner=None,
            )

            def finished_handler(_result):
                stub.snapshot_refresh_task_runner = None
                states.append(('attr_cleared', len(stub._queued_gui_task_runners)))

            class FakeRunner:
                def __init__(self, parent, worker, finished_cb, failed_cb, cleanup_cb):
                    self.finished_cb = finished_cb
                    self.cleanup_cb = cleanup_cb
                    self.thread = SimpleNamespace()

                def start(self):
                    self.finished_cb({'success': True})
                    states.append(('before_cleanup', len(stub._queued_gui_task_runners)))
                    self.cleanup_cb()

            with patch('app.gui.main_window.GuiTaskRunner', FakeRunner):
                bound_start = partial(main_window.VidNormApp._start_queued_gui_runner, stub)
                bound_start(
                    '后台刷新快照',
                    worker_factory=lambda: SimpleNamespace(),
                    finished_handler=finished_handler,
                    failed_handler=lambda _message: self.fail('不应进入失败分支'),
                    assign_runner=lambda _worker, runner: setattr(stub, 'snapshot_refresh_task_runner', runner),
                )

                _process_events()

            records = queue.records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, TASK_STATUS_COMPLETED)
            self.assertTrue(queue.is_all_done())
            self.assertEqual(states, [('attr_cleared', 1), ('before_cleanup', 1)])
            self.assertEqual(len(stub._queued_gui_task_runners), 0)
            self.assertIsNone(stub.snapshot_refresh_task_runner)
        finally:
            queue.reset_for_tests()


if __name__ == '__main__':
    unittest.main()
