import ctypes
import inspect
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from PyQt5.QtGui import QFont
from PyQt5.QtCore import QCoreApplication, QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.backend_protocol import BACKEND_API_REVISION, build_backend_code_fingerprint
from app.core.local_video_labels import (
    ENRICHMENT_REQUIRED_STATUS,
    IMPORT_REQUIRED_STATUS,
    NORMALIZED_STATUS,
    RENAME_REQUIRED_STATUS,
)
from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.combo_enrichment import get_combo_label
from app.core.enrichment_sources import get_video_enrichment_source_label
from app.core.enrichment_targets import ENRICHMENT_TARGET_LABELS
from app.core.project_paths import DATABASE_FILE, GUI_INSTANCE_LOCK_FILE, PROJECT_ROOT
from app.core.runtime_config import get_backend_port, get_backend_timeout_seconds
from app.gui.actor_viewer import ActorViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin, BackendTaskWorker
from app.gui.canglangge_viewer import CanglanggeViewerWindow
from app.gui.code_prefix_viewer import CodePrefixViewerWindow
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.data_center_viewer import DataCenterWindow
from app.gui.data_center_analysis_viewer import _build_refresh_client
from app.gui.comparison_viewer import ComparisonWindow
from app.gui.db_viewer import DatabaseViewerWindow
from app.gui.enrichment_dialog import EnrichmentDialog
from app.gui.gui_task_runner import GuiTaskRunner
from app.gui.i18n import tr
from app.gui.ladder_board_viewer import LadderBoardWindow
from app.gui.medal_catalog_viewer import MedalCatalogWindow
from app.gui.masterpiece_viewer import MasterpieceDetailWindow, MasterpieceWindow
from app.gui.path_library_viewer import PathLibraryWindow
from app.queen_library.viewer import QueenLibraryWindow
from app.gui.task_queue import (
    RUN_MODE_TASK,
    RUN_MODE_VIEW,
    TASK_CATEGORY_ENRICHMENT,
    TASK_CATEGORY_VIEW,
    TASK_STATUS_RUNNING,
    get_gui_task_queue,
)
from app.gui.task_queue_viewer import TaskQueueViewerWindow
from app.gui.task_progress_widget import TaskProgressWidget
from app.gui.timeout_settings_viewer import TimeoutSettingsViewerWindow
from app.gui.runtime_settings import load_runtime_mode, save_runtime_mode
from app.gui.query_context import EntityReference, EntityType, QueryContext
from app.gui.query_history import QueryHistoryStore
from app.gui.single_instance import SingleInstanceGuard
from app.gui.unified_search_viewer import UnifiedSearchWindow
from app.gui.window_coordinator import WindowCoordinator
from app.gui.video_category_viewer import VideoCategoryViewerWindow
from app.gui.video_filter_dialog import VideoFilterDialog
from app.services.system import NetworkGuardService


SNAPSHOT_REFRESH_STARTUP_DELAY_MS = 15000
SNAPSHOT_REFRESH_REQUEST_TIMEOUT_SECONDS = 20 * 60
SNAPSHOT_REFRESH_HISTORY_TASK_KEY = 'snapshot_refresh'
SNAPSHOT_REFRESH_HISTORY_TASK_TITLE = '后台刷新快照'
STARTUP_REFRESH_INTERVAL_HOURS = 88
STARTUP_REFRESH_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'


class EnrichmentWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        backend_client,
        limit,
        show_browser,
        cooldown_before_search,
        target_type,
        source_key,
        batch_mode=False,
        plan_id='',
        plan_task_kind='',
    ):
        super().__init__()
        self.backend_client = backend_client
        self.limit = limit
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.target_type = target_type
        self.source_key = source_key
        self.batch_mode = bool(batch_mode)
        self.plan_id = str(plan_id or '')
        self.plan_task_kind = str(plan_task_kind or '')

    def run(self):
        try:
            result = self.backend_client.enrich_videos(
                self.limit,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                target_type=self.target_type,
                source_key=self.source_key,
                batch_mode=self.batch_mode,
                plan_id=self.plan_id,
                plan_task_kind=self.plan_task_kind,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class ComboEnrichmentWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        backend_client,
        combo_key,
        limit,
        show_browser,
        cooldown_before_search,
        combo_task_settings=None,
        batch_mode=False,
    ):
        super().__init__()
        self.backend_client = backend_client
        self.combo_key = combo_key
        self.limit = limit
        self.show_browser = show_browser
        self.cooldown_before_search = cooldown_before_search
        self.combo_task_settings = dict(combo_task_settings or {})
        self.batch_mode = bool(batch_mode)

    def run(self):
        try:
            result = self.backend_client.enrich_combo(
                self.combo_key,
                self.limit,
                show_browser=self.show_browser,
                cooldown_before_search=self.cooldown_before_search,
                combo_task_settings=self.combo_task_settings,
                batch_mode=self.batch_mode,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class AutoLoginWorker(QObject):
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, backend_client):
        super().__init__()
        self.backend_client = backend_client

    def run(self):
        try:
            result = self.backend_client.auto_login()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class SnapshotRefreshWorker(QObject):
    progress = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, refresh_callback):
        super().__init__()
        self.refresh_callback = refresh_callback

    def run(self):
        try:
            result = self.refresh_callback(self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(dict(result or {}))


class VidNormApp(QWidget, AsyncTaskHostMixin):
    def __init__(self):
        super().__init__()
        self.pending_renames = []
        self.backend_process = None
        self.owns_backend_process = self._should_own_prelaunched_backend()
        self.backend_instance_token = self._get_initial_backend_instance_token()
        self.backend_client = BackendClient()
        self.enrichment_thread = None
        self.enrichment_worker = None
        self.enrichment_task_runner = None
        self.current_enrichment_kind = 'single'
        self.enrichment_mode = None
        self.batch_enrichment_active = False
        self.batch_enrichment_config = None
        self.batch_enrichment_round = 0
        self.batch_timer = QTimer(self)
        self.batch_timer.setSingleShot(True)
        self.batch_timer.timeout.connect(self.run_next_batch_enrichment)
        self.batch_countdown_timer = QTimer(self)
        self.batch_countdown_timer.setInterval(1000)
        self.batch_countdown_timer.timeout.connect(self.update_batch_countdown)
        self.batch_next_run_at = None
        self.enrichment_progress_timer = QTimer(self)
        self.enrichment_progress_timer.setInterval(1000)
        self.enrichment_progress_timer.timeout.connect(self.refresh_enrichment_progress)
        self.network_guard_service = NetworkGuardService()
        self.network_guard_timer = QTimer(self)
        self.network_guard_timer.setInterval(5000)
        self.network_guard_timer.timeout.connect(self.check_network_guard)
        self.network_guard_failure_count = 0
        self.network_stop_requested = False
        self.network_last_probe_online = None
        self.login_thread = None
        self.login_worker = None
        self.login_task_runner = None
        self.login_task_queued = False
        self.snapshot_refresh_worker = None
        self.snapshot_refresh_task_runner = None
        self.snapshot_refresh_running = False
        self.snapshot_refresh_queued = False
        self.snapshot_refresh_started_at = 0.0
        self.snapshot_refresh_current_target = ''
        self.snapshot_refresh_last_completed_at = ''
        self.snapshot_refresh_timer = QTimer(self)
        self.snapshot_refresh_timer.setInterval(3 * 60 * 60 * 1000)
        self.snapshot_refresh_timer.timeout.connect(self.schedule_snapshot_refresh_cycle)
        self.snapshot_refresh_elapsed_timer = QTimer(self)
        self.snapshot_refresh_elapsed_timer.setInterval(1000)
        self.snapshot_refresh_elapsed_timer.timeout.connect(self.update_snapshot_refresh_elapsed)
        self._init_async_task_host()
        self.enrichment_task_queued = False
        self._queued_enrichment_worker_factory = None
        self._queued_enrichment_task_title = ''
        self._queued_enrichment_batch_plan_payload = None
        self._queued_enrichment_batch_plan_state = None
        self._active_enrichment_batch_plan_state = None
        self._queued_gui_task_runners = {}
        self.runtime_mode = load_runtime_mode()
        self.window_coordinator = WindowCoordinator(parent=self)
        self.query_history = QueryHistoryStore()
        self._configure_window_coordinator()

        self.ensure_backend_running()
        self.init_ui()
        self.task_queue = get_gui_task_queue()
        self.task_queue.changed.connect(self.refresh_task_queue_indicator)
        self.task_queue.set_run_mode(self.runtime_mode)
        self.recover_unfinished_enrichment_plans()
        self.refresh_task_queue_indicator()
        self.update_enrichment_controls()
        self.reset_progress_widgets()
        self.start_network_guard()
        self.check_network_guard()
        self.start_snapshot_refresh_scheduler()

    def ensure_backend_running(self):
        stale_backend_cleaned = False
        health = self.get_backend_health()
        if self._adopt_reusable_backend(health):
            return
        if health is not None:
            stale_backend_cleaned = self.is_reusable_backend_instance(health) and not self.is_expected_backend_instance(health)
            self.stop_backend_on_port(health=health)
            health = self.get_backend_health()
            if self._adopt_reusable_backend(health):
                return
            if health is not None:
                raise RuntimeError(tr('main.backend_port_in_use', port=get_backend_port()))

        self.backend_instance_token = uuid.uuid4().hex
        backend_script = PROJECT_ROOT / 'backend_server.py'
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.backend_process = subprocess.Popen(
            [self._get_backend_python_executable(), str(backend_script), '--instance-token', self.backend_instance_token],
            cwd=str(backend_script.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creation_flags,
        )
        self.owns_backend_process = True

        deadline = time.time() + VidNormApp._get_backend_start_timeout_seconds()
        while time.time() < deadline:
            if self.backend_process.poll() is not None:
                stdout_text, stderr_text = self.backend_process.communicate()
                detail = (stderr_text or stdout_text or '').strip() or tr('main.backend_process_exited_no_detail')
                raise RuntimeError(tr('main.backend_process_exited', detail=detail))
            health = self.get_backend_health()
            if self.is_expected_backend_instance(health):
                return
            time.sleep(0.2)

        health = self.get_backend_health()
        if health is not None:
            raise RuntimeError(tr('main.backend_port_in_use', port=get_backend_port()))
        if VidNormApp._is_backend_process_alive(self.backend_process):
            self.stop_owned_backend()
        raise RuntimeError(self._build_backend_start_failure_message(stale_backend_cleaned=stale_backend_cleaned))

    @staticmethod
    def _get_initial_backend_instance_token():
        return str(os.environ.get('VIDNORM_BACKEND_INSTANCE_TOKEN', '') or '').strip()

    @staticmethod
    def _should_own_prelaunched_backend():
        return str(os.environ.get('VIDNORM_BACKEND_OWNED', '') or '').strip().lower() in ('1', 'true', 'yes', 'on')

    def _adopt_reusable_backend(self, health):
        if not self.is_reusable_backend_instance(health):
            return False
        if self.is_expected_backend_instance(health):
            return True
        if not str(self.backend_instance_token or '').strip():
            return False
        self.backend_instance_token = str((health or {}).get('backend_instance_token') or self.backend_instance_token)
        self.backend_process = None
        self.owns_backend_process = False
        return True

    @staticmethod
    def _get_backend_python_executable():
        current_executable = Path(sys.executable)
        if current_executable.name.lower() == 'pythonw.exe':
            console_python = current_executable.with_name('python.exe')
            if console_python.exists():
                return str(console_python)
        return str(current_executable)

    def is_backend_alive(self):
        return self.get_backend_health() is not None

    def get_backend_health(self):
        try:
            return self.backend_client.health()
        except Exception:
            return None

    def is_backend_compatible(self, health):
        return bool(health) and self._is_matching_backend_code(health)

    def is_expected_backend_instance(self, health):
        return (
            self.is_backend_compatible(health)
            and str((health or {}).get('backend_instance_token') or '').strip() == self.backend_instance_token
        )

    @staticmethod
    def is_reusable_backend_instance(health):
        if not health:
            return False
        if not VidNormApp._is_matching_backend_code(health):
            return False
        existing_project_root = str((health or {}).get('project_root') or '').strip()
        if not existing_project_root:
            return False
        return Path(existing_project_root).resolve() == PROJECT_ROOT.resolve()

    @staticmethod
    def _is_matching_backend_code(health):
        if str((health or {}).get('backend_revision') or '').strip() != BACKEND_API_REVISION:
            return False
        return str((health or {}).get('backend_code_fingerprint') or '').strip() == build_backend_code_fingerprint(
            PROJECT_ROOT
        )

    def stop_backend_on_port(self, health=None):
        if self.backend_process and self.backend_process.poll() is None:
            force_killed = self._terminate_backend_process_handle(self.backend_process, timeout_seconds=3)
            if force_killed:
                self._wait_for_backend_release(timeout_seconds=3)
            self.backend_process = None
            return

        if self._terminate_backend_pid(self._extract_backend_pid(health)):
            if self._wait_for_backend_release():
                return

        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        port = str(get_backend_port())
        result = subprocess.run(
            ['netstat', '-ano', '-p', 'tcp'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creation_flags,
        )
        target_pids = set()
        port_token = f':{port}'
        for line in result.stdout.splitlines():
            upper_line = line.upper()
            if 'LISTENING' not in upper_line or port_token not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            local_address = parts[1]
            if port_token not in local_address:
                continue
            pid = str(parts[-1] or '').strip()
            if pid.isdigit():
                target_pids.add(pid)

        for pid in sorted(target_pids):
            self._terminate_backend_pid(pid)

        if target_pids:
            self._wait_for_backend_release()

    @staticmethod
    def _extract_backend_pid(health):
        pid = str((health or {}).get('backend_process_id') or '').strip()
        return pid if pid.isdigit() else ''

    def _is_database_locked(self):
        try:
            conn = sqlite3.connect(DATABASE_FILE, timeout=1)
            try:
                conn.execute('SELECT 1')
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            return 'locked' in str(exc).lower()
        return False

    @staticmethod
    def _get_backend_start_timeout_seconds():
        return max(30.0, float(get_backend_timeout_seconds() or 0))

    def _build_backend_start_failure_message(self, stale_backend_cleaned=False):
        if self._is_backend_process_alive(self.backend_process):
            if stale_backend_cleaned:
                return tr('main.backend_start_timeout_after_cleanup')
            return tr('main.backend_start_initializing_too_long')
        if self._is_database_locked():
            return tr('main.backend_db_locked')
        if stale_backend_cleaned:
            return tr('main.backend_start_timeout_after_cleanup')
        return tr('main.backend_start_timeout')

    @staticmethod
    def _is_backend_process_alive(process):
        return process is not None and process.poll() is None

    def _terminate_backend_process_handle(self, process, timeout_seconds=3):
        if not self._is_backend_process_alive(process):
            return False
        process.terminate()
        try:
            process.wait(timeout=timeout_seconds)
        except Exception:
            pass
        if self._is_backend_process_alive(process):
            return self._terminate_backend_pid(getattr(process, 'pid', ''))
        return False

    @staticmethod
    def _terminate_backend_pid(pid):
        normalized_pid = str(pid or '').strip()
        if not normalized_pid.isdigit():
            return False
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.run(
            ['taskkill', '/PID', normalized_pid, '/T', '/F'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        return True

    def _wait_for_backend_release(self, timeout_seconds=3.0):
        deadline = time.time() + max(0.2, float(timeout_seconds or 0))
        while time.time() < deadline:
            if self.get_backend_health() is None:
                return True
            time.sleep(0.2)
        return self.get_backend_health() is None

    def stop_owned_backend(self):
        if not self.owns_backend_process:
            return
        if self._is_backend_process_alive(self.backend_process):
            force_killed = self._terminate_backend_process_handle(self.backend_process, timeout_seconds=3)
            if force_killed:
                self._wait_for_backend_release(timeout_seconds=3)
            self.backend_process = None
            self.owns_backend_process = False
            return

        health = self.get_backend_health()
        if self.is_expected_backend_instance(health):
            self.stop_backend_on_port(health=health)
        self.owns_backend_process = False

    def init_ui(self):
        self.setWindowTitle(tr('main.title'))
        self.resize(1000, 700)
        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(tr('main.path_placeholder'))
        self.path_input.setReadOnly(True)

        self.btn_browse = QPushButton(tr('main.browse'))
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_path_library = QPushButton(tr('main.path_library'))
        self.btn_path_library.clicked.connect(self.show_path_library)
        self.snapshot_refresh_red_light_label = QLabel('●')
        self.snapshot_refresh_green_light_label = QLabel('●')
        self.snapshot_refresh_status_label = QLabel('')

        snapshot_status_layout = QHBoxLayout()
        snapshot_status_layout.setSpacing(6)
        snapshot_status_layout.addWidget(self.snapshot_refresh_red_light_label)
        snapshot_status_layout.addWidget(self.snapshot_refresh_green_light_label)
        snapshot_status_layout.addWidget(self.snapshot_refresh_status_label)

        top_layout.addWidget(QLabel(tr('main.local_folder')))
        top_layout.addWidget(self.path_input)
        top_layout.addWidget(self.btn_path_library)
        top_layout.addWidget(self.btn_browse)
        top_layout.addSpacing(12)
        top_layout.addLayout(snapshot_status_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(tr('main.scan_headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.status_label = QLabel('')
        self.network_status_label = QLabel(tr('main.network_status_unknown'))
        self.runtime_mode_label = QLabel('任务模式')
        self.runtime_mode_label.setStyleSheet('color: #1b7f3b; font-weight: 700;')
        self.btn_runtime_mode = QPushButton('切换查看模式')
        self.btn_runtime_mode.clicked.connect(self.toggle_runtime_mode)
        self.progress_label = QLabel('')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(True)
        self.combo_subtask_widgets = [TaskProgressWidget(self), TaskProgressWidget(self)]
        self.batch_countdown_label = QLabel('')
        self.update_network_status_label()
        VidNormApp._set_snapshot_refresh_indicator_state(
            self,
            state='idle',
            status_text=VidNormApp._build_snapshot_refresh_idle_status_text(''),
        )

        button_layout = QVBoxLayout()
        top_button_row = QHBoxLayout()
        bottom_button_row = QHBoxLayout()

        self.btn_video_library = QPushButton(tr('main.video_library'))
        self.btn_video_library.clicked.connect(self.show_video_library)

        self.btn_unified_search = QPushButton('统一查询')
        self.btn_unified_search.clicked.connect(self.show_unified_search)

        self.btn_database = QPushButton(tr('main.data_center'))
        self.btn_database.clicked.connect(self.show_data_center)

        self.btn_view_actors = QPushButton(tr('main.actor_library'))
        self.btn_view_actors.clicked.connect(self.show_actor_viewer)

        self.btn_view_code_prefixes = QPushButton(tr('main.code_prefix_library'))
        self.btn_view_code_prefixes.clicked.connect(self.show_code_prefix_viewer)

        self.btn_canglangge = QPushButton(tr('main.canglangge'))
        self.btn_canglangge.clicked.connect(self.show_canglangge_viewer)

        self.btn_tianji = QPushButton(tr('main.video_category'))
        self.btn_tianji.clicked.connect(self.show_video_category_viewer)

        self.btn_ladder_board = QPushButton(tr('main.ladder_board'))
        self.btn_ladder_board.clicked.connect(self.show_ladder_board_viewer)

        self.btn_masterpiece = QPushButton('名作堂')
        self.btn_masterpiece.clicked.connect(self.show_masterpiece_viewer)

        self.btn_medal_catalog = QPushButton('勋章堂')
        self.btn_medal_catalog.clicked.connect(self.show_medal_catalog_viewer)

        self.btn_queen_library = QPushButton('女王库')
        self.btn_queen_library.clicked.connect(self.show_queen_library_viewer)

        self.btn_scan = QPushButton(tr('main.scan_local_videos'))
        self.btn_scan.clicked.connect(self.scan_files)

        self.btn_import_db = QPushButton(tr('main.import_video_library'))
        self.btn_import_db.clicked.connect(self.import_to_database)
        self.btn_import_db.setEnabled(False)

        self.btn_auto_login = QPushButton(tr('main.auto_login'))
        self.btn_auto_login.clicked.connect(self.auto_login)

        self.btn_enrich = QPushButton(tr('main.enrich_info'))
        self.btn_enrich.clicked.connect(self.enrich_video_info)

        self.btn_stop_enrich = QPushButton(tr('main.stop_enrich'))
        self.btn_stop_enrich.clicked.connect(self.stop_enrichment)
        self.btn_stop_enrich.setEnabled(False)

        self.btn_reset_browser_profile = QPushButton(tr('main.reset_browser_profile'))
        self.btn_reset_browser_profile.clicked.connect(self.reset_browser_profile)

        self.btn_status_sync = QPushButton(tr('main.status_sync'))
        self.btn_status_sync.clicked.connect(self.sync_library_statuses)

        self.btn_refresh_detail_snapshots = QPushButton('全量刷新快照')
        self.btn_refresh_detail_snapshots.clicked.connect(self.refresh_detail_snapshots)

        self.btn_task_queue = QPushButton('任务列表')
        self.btn_task_queue.clicked.connect(self.show_task_queue_viewer)

        self.btn_timeout_settings = QPushButton('超时器')
        self.btn_timeout_settings.clicked.connect(self.show_timeout_settings_viewer)

        self.btn_execute = QPushButton(tr('main.execute_rename'))
        self.btn_execute.clicked.connect(self.execute_rename)
        self.btn_execute.setEnabled(False)

        self.btn_force_exit = QPushButton(tr('main.force_exit'))
        self.btn_force_exit.clicked.connect(self.force_exit_application)
        self.btn_force_exit.setStyleSheet('QPushButton { color: #b42318; font-weight: 700; }')

        top_button_row.addWidget(self.btn_unified_search)
        top_button_row.addWidget(self.btn_video_library)
        top_button_row.addWidget(self.btn_database)
        top_button_row.addWidget(self.btn_view_actors)
        top_button_row.addWidget(self.btn_view_code_prefixes)
        top_button_row.addWidget(self.btn_canglangge)
        top_button_row.addWidget(self.btn_tianji)
        top_button_row.addWidget(self.btn_ladder_board)
        top_button_row.addWidget(self.btn_masterpiece)
        top_button_row.addWidget(self.btn_medal_catalog)
        top_button_row.addWidget(self.btn_queen_library)
        top_button_row.addStretch()

        bottom_button_row.addWidget(self.btn_scan)
        bottom_button_row.addWidget(self.btn_import_db)
        bottom_button_row.addWidget(self.btn_auto_login)
        bottom_button_row.addWidget(self.btn_enrich)
        bottom_button_row.addWidget(self.btn_stop_enrich)
        bottom_button_row.addWidget(self.btn_reset_browser_profile)
        bottom_button_row.addWidget(self.btn_status_sync)
        bottom_button_row.addWidget(self.btn_refresh_detail_snapshots)
        bottom_button_row.addWidget(self.btn_task_queue)
        bottom_button_row.addWidget(self.btn_timeout_settings)
        bottom_button_row.addWidget(self.btn_execute)
        bottom_button_row.addStretch()
        bottom_button_row.addWidget(self.btn_force_exit)

        button_layout.addLayout(top_button_row)
        button_layout.addLayout(bottom_button_row)

        status_bar_layout = QHBoxLayout()
        status_bar_layout.addWidget(self.status_label, 1)
        status_bar_layout.addWidget(self.runtime_mode_label, 0, Qt.AlignRight)
        status_bar_layout.addWidget(self.btn_runtime_mode, 0, Qt.AlignRight)
        status_bar_layout.addWidget(self.network_status_label, 0, Qt.AlignRight)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.table)
        main_layout.addLayout(status_bar_layout)
        main_layout.addWidget(self.progress_label)
        main_layout.addWidget(self.progress_bar)
        for combo_subtask_widget in self.combo_subtask_widgets:
            combo_subtask_widget.hide()
            main_layout.addWidget(combo_subtask_widget)
        main_layout.addWidget(self.batch_countdown_label)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, tr('common.select_folder'))
        if folder_path:
            self.set_current_folder(folder_path)

    def set_current_folder(self, folder_path):
        self.path_input.setText(folder_path)
        self.table.setRowCount(0)
        self.pending_renames.clear()
        self.btn_execute.setEnabled(False)
        self.btn_import_db.setEnabled(False)

    def scan_files(self):
        self.refresh_scan_results(show_message=True)

    def refresh_scan_results(self, show_message=False):
        folder_path = self.path_input.text()
        if not folder_path:
            QMessageBox.warning(self, tr('common.prompt'), tr('main.select_folder_first'))
            return False

        def task():
            return {
                'scan_result': self.backend_client.scan_folder(folder_path),
                'show_message': bool(show_message),
            }

        self.start_async_task(task, self._on_scan_finished, tr('common.prompt'), task_title='主界面 扫描本地视频')
        return True

    def import_to_database(self):
        if not self.pending_renames:
            return

        folder_path = self.path_input.text()
        plans = list(self.pending_renames)

        def task():
            result = self.backend_client.import_videos(plans)
            scan_result = self.backend_client.scan_folder(folder_path)
            return {
                'success_count': result.get('success_count', 0),
                'scan_result': scan_result,
            }

        self.start_async_task(task, self._on_import_finished, tr('common.prompt'), task_title='主界面 导入视频库')

    def execute_rename(self):
        if not self.pending_renames:
            return

        renamable_plans = [
            plan
            for plan in self.pending_renames
            if bool(plan.get('can_rename')) and bool(plan.get('needs_rename'))
        ]
        if not renamable_plans:
            QMessageBox.information(self, tr('common.prompt'), tr('main.no_renamable_videos'))
            return

        folder_path = self.path_input.text()

        def task():
            response = self.backend_client.execute_renames(renamable_plans)
            scan_result = self.backend_client.scan_folder(folder_path)
            return {
                'success_count': response.get('success_count', 0),
                'scan_result': scan_result,
            }

        self.start_async_task(task, self._on_execute_rename_finished, tr('common.prompt'), task_title='主界面 执行重命名')

    def auto_login(self):
        if self.login_thread is not None or self.login_task_queued:
            QMessageBox.information(self, tr('main.login_in_progress_title'), tr('main.login_in_progress_message'))
            return
        self.start_auto_login()

    def start_auto_login(self):
        self.login_task_queued = True
        self.btn_auto_login.setEnabled(False)
        self.status_label.setText(tr('main.login_status'))

        def assign_login_runner(worker, runner):
            self.login_worker = worker
            self.login_task_runner = runner
            self.login_thread = runner.thread

        self._start_queued_gui_runner(
            '自动登录',
            lambda: AutoLoginWorker(self.backend_client),
            self.on_auto_login_finished,
            self.on_auto_login_failed,
            cleanup_handler=self.cleanup_auto_login_thread,
            assign_runner=assign_login_runner,
        )

    def enrich_video_info(self):
        dialog = EnrichmentDialog(self)
        if not dialog.exec_():
            return

        values = dialog.values()
        if dialog.action_mode == 'batch':
            self.start_batch_enrichment(values)
            return
        if dialog.action_mode == 'combo_single':
            self.start_combo_enrichment(
                values['combo_key'],
                values['limit'],
                values['show_browser'],
                values['cooldown_before_search'],
                combo_task_settings=self._build_combo_task_settings_for_mode(
                    values.get('combo_task_settings', {}),
                    use_batch_limit=False,
                ),
                mode='combo_single',
            )
            return
        if dialog.action_mode == 'combo_batch':
            self.start_combo_batch_plan(values)
            return

        self.start_enrichment(
            values['limit'],
            values['show_browser'],
            values['cooldown_before_search'],
            values['target_type'],
            values['source_key'],
            mode='single',
        )

    def start_enrichment(
        self,
        limit,
        show_browser,
        cooldown_before_search,
        target_type,
        source_key,
        mode='single',
        resume_plan=None,
    ):
        self.current_enrichment_kind = 'single'
        self.enrichment_mode = mode
        resume_plan = dict(resume_plan or getattr(self, '_active_enrichment_batch_plan_state', None) or {})
        plan_batch_count_limit = (
            (self.batch_enrichment_config or {}).get('batch_count_limit', 1)
            if mode == 'batch'
            else int(resume_plan.get('batch_count_limit', 1) or 1)
        )
        batch_plan_payload = None if resume_plan.get('plan_id') else VidNormApp._build_enrichment_batch_plan_payload(
            target_type,
            source_key,
            limit,
            plan_batch_count_limit,
        )
        batch_plan_state = dict(resume_plan)
        self._queued_enrichment_worker_factory = (
            lambda: EnrichmentWorker(
                self.backend_client,
                limit,
                show_browser,
                cooldown_before_search,
                target_type,
                source_key,
                batch_mode=(mode == 'batch'),
                plan_id=batch_plan_state.get('plan_id', ''),
                plan_task_kind=batch_plan_state.get('task_kind') or (batch_plan_payload or {}).get('task_kind', ''),
            )
        )
        self._queued_enrichment_task_title = VidNormApp._build_enrichment_task_queue_title(
            mode,
            target_type=target_type,
            source_key=source_key,
            limit=limit,
            batch_round=(self.batch_enrichment_round + 1) if mode == 'batch' else 0,
            batch_count_limit=(self.batch_enrichment_config or {}).get('batch_count_limit', 1),
        )
        self._queued_enrichment_batch_plan_payload = batch_plan_payload
        self._queued_enrichment_batch_plan_state = batch_plan_state
        self.enrichment_worker = None
        if mode == 'batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(
                tr('main.batch_round_running', round_number=self.batch_enrichment_round)
            )
            interval_minutes = max(1, int((self.batch_enrichment_config or {}).get('interval_minutes', 1) or 1))
            self.batch_countdown_label.setText(
                tr('main.batch_countdown_pending_current_round', interval_minutes=interval_minutes)
            )
        else:
            self.status_label.setText(tr('main.single_enrichment_running'))
        self._start_enrichment_task_runner()

    def start_combo_enrichment(
        self,
        combo_key,
        limit,
        show_browser,
        cooldown_before_search,
        combo_task_settings=None,
        mode='combo_single',
        batch_mode=False,
    ):
        self.current_enrichment_kind = 'combo'
        self.enrichment_mode = mode
        self._queued_enrichment_worker_factory = (
            lambda: ComboEnrichmentWorker(
                self.backend_client,
                combo_key,
                limit,
                show_browser,
                cooldown_before_search,
                combo_task_settings=combo_task_settings,
                batch_mode=batch_mode,
            )
        )
        self._queued_enrichment_task_title = VidNormApp._build_combo_task_queue_title(
            mode,
            combo_key=combo_key,
            combo_task_settings=combo_task_settings,
            batch_round=(self.batch_enrichment_round + 1) if mode == 'combo_batch' else 0,
            batch_count_limit=(self.batch_enrichment_config or {}).get('batch_count_limit', 1),
        )
        self._queued_enrichment_batch_plan_payload = None
        self._queued_enrichment_batch_plan_state = None
        self.enrichment_worker = None
        if mode == 'combo_batch':
            self.batch_enrichment_round += 1
            self.status_label.setText(
                tr('main.combo_round_running', round_number=self.batch_enrichment_round)
            )
            interval_minutes = max(1, int((self.batch_enrichment_config or {}).get('interval_minutes', 1) or 1))
            self.batch_countdown_label.setText(
                tr('main.batch_countdown_pending_current_round', interval_minutes=interval_minutes)
            )
        else:
            self.status_label.setText(tr('main.combo_running'))
        self._start_enrichment_task_runner()

    def _start_enrichment_task_runner(self):
        self.enrichment_task_queued = True
        queued_kind = self.current_enrichment_kind
        queued_mode = self.enrichment_mode
        worker_factory = self._queued_enrichment_worker_factory
        batch_plan_payload = self._queued_enrichment_batch_plan_payload
        batch_plan_state = self._queued_enrichment_batch_plan_state
        task_title = str(getattr(self, '_queued_enrichment_task_title', '') or '').strip() or '信息补全'

        def before_start(record=None):
            self.current_enrichment_kind = queued_kind
            self.enrichment_mode = queued_mode
            if batch_plan_payload and not batch_plan_state.get('plan_id'):
                plan_response = self.backend_client.create_enrichment_batch_plan(batch_plan_payload)
                plan_payload = dict(plan_response.get('plan', plan_response) or {})
                if isinstance(batch_plan_state, dict):
                    batch_plan_state.update(plan_payload)
            if queued_mode == 'batch':
                self._active_enrichment_batch_plan_state = dict(batch_plan_state)
            if batch_plan_state.get('plan_id'):
                progress = dict(batch_plan_state)
                try:
                    progress = self.backend_client.get_enrichment_plan_progress(
                        batch_plan_state.get('plan_id'),
                        batch_plan_state.get('task_kind') or (batch_plan_payload or {}).get('task_kind', ''),
                    ) or progress
                except Exception:
                    pass
                if record is not None and hasattr(self, 'task_queue'):
                    self.task_queue.update_record_plan(
                        record.task_id,
                        batch_plan_state.get('plan_id'),
                        batch_plan_state.get('task_kind') or (batch_plan_payload or {}).get('task_kind', ''),
                        progress,
                    )
            self.update_enrichment_controls()
            self.reset_progress_widgets(keep_visible=True)
            self.enrichment_progress_timer.start()
            self.refresh_enrichment_progress()

        def assign_enrichment_runner(worker, runner):
            self.enrichment_worker = worker
            self.enrichment_task_runner = runner
            self.enrichment_thread = runner.thread

        self.update_enrichment_controls()
        self.reset_progress_widgets(keep_visible=True)
        runner_kwargs = {
            'cleanup_handler': self.cleanup_enrichment_thread,
            'before_start': before_start,
            'assign_runner': assign_enrichment_runner,
            'task_category': TASK_CATEGORY_ENRICHMENT,
            'task_kind': queued_kind,
        }
        supported_parameters = inspect.signature(self._start_queued_gui_runner).parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in supported_parameters.values()
        )
        if 'before_start_with_record' in supported_parameters or accepts_kwargs:
            runner_kwargs['before_start_with_record'] = True
        if 'plan_id' in supported_parameters or accepts_kwargs:
            runner_kwargs['plan_id'] = batch_plan_state.get('plan_id', '')
            runner_kwargs['plan_progress'] = batch_plan_state
        self._start_queued_gui_runner(
            task_title,
            worker_factory,
            self.on_enrichment_finished,
            self.on_enrichment_failed,
            **runner_kwargs,
        )

    @staticmethod
    def _build_enrichment_task_queue_title(
        mode,
        target_type,
        source_key,
        limit,
        batch_round=0,
        batch_count_limit=1,
    ):
        target_label = ENRICHMENT_TARGET_LABELS.get(str(target_type or '').strip(), '补全对象')
        source_label = get_video_enrichment_source_label(source_key)
        limit_text = max(1, int(limit or 1))
        if mode == 'batch':
            return (
                f'分批补全 {max(1, int(batch_round or 1))}/{max(1, int(batch_count_limit or 1))} - '
                f'{target_label} / {source_label} / {limit_text}项'
            )
        return f'单次补全 - {target_label} / {source_label} / {limit_text}项'

    @staticmethod
    def _build_combo_task_queue_title(
        mode,
        combo_key,
        combo_task_settings=None,
        batch_round=0,
        batch_count_limit=1,
    ):
        combo_label = get_combo_label(combo_key)
        settings = dict(combo_task_settings or {})
        task_count = len(settings)
        max_limit = 1
        for task_settings in settings.values():
            max_limit = max(max_limit, int((task_settings or {}).get('limit', 1) or 1))
        if mode == 'combo_batch':
            return (
                f'组合分批补全 {max(1, int(batch_round or 1))}/{max(1, int(batch_count_limit or 1))} - '
                f'{combo_label} / {task_count}类任务 / 最大{max_limit}项'
            )
        return f'组合补全 - {combo_label} / {task_count}类任务 / 最大{max_limit}项'

    @staticmethod
    def _build_enrichment_batch_plan_payload(target_type, source_key, batch_limit, batch_count_limit):
        task_kind_by_target = {
            'video_library': 'video',
            'code_prefix_library': 'code_prefix',
            'actor_library': 'actor',
            'actor_birthday': 'actor_birthday',
        }
        normalized_target = str(target_type or 'video_library').strip() or 'video_library'
        return {
            'task_kind': task_kind_by_target.get(normalized_target, 'video'),
            'target_type': normalized_target,
            'source_key': str(source_key or '').strip(),
            'batch_limit': max(1, int(batch_limit or 1)),
            'batch_count_limit': max(1, int(batch_count_limit or 1)),
        }

    def start_batch_enrichment(self, values):
        self.batch_enrichment_active = True
        self._active_enrichment_batch_plan_state = None
        self.batch_enrichment_config = {
            'task_kind': 'single',
            'limit': values['batch_limit'],
            'batch_count_limit': max(1, int(values.get('batch_count', 1) or 1)),
            'interval_minutes': values['batch_interval_minutes'],
            'show_browser': values['show_browser'],
            'cooldown_before_search': values['cooldown_before_search'],
            'target_type': values['target_type'],
            'source_key': values['source_key'],
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            tr(
                'main.batch_started',
                interval_minutes=values['batch_interval_minutes'],
                batch_limit=values['batch_limit'],
            )
        )
        self.update_enrichment_controls()
        self.run_next_batch_enrichment()

    def start_batch_combo_enrichment(self, values):
        combo_task_settings = self._build_combo_task_settings_for_mode(
            values.get('combo_task_settings', {}),
            use_batch_limit=True,
        )
        self.batch_enrichment_active = True
        self.batch_enrichment_config = {
            'task_kind': 'combo',
            'combo_key': values['combo_key'],
            'limit': self._combo_default_limit(combo_task_settings, fallback=values['batch_limit']),
            'batch_count_limit': max(1, int(values.get('batch_count', 1) or 1)),
            'interval_minutes': self._combo_batch_interval_minutes(
                combo_task_settings,
                fallback=values['batch_interval_minutes'],
            ),
            'show_browser': values['show_browser'],
            'cooldown_before_search': values['cooldown_before_search'],
            'combo_task_settings': combo_task_settings,
        }
        self.batch_enrichment_round = 0
        self.status_label.setText(
            tr(
                'main.combo_batch_started',
                interval_minutes=values['batch_interval_minutes'],
                batch_limit=values['batch_limit'],
            )
        )
        self.update_enrichment_controls()
        self.run_next_batch_enrichment()

    def run_next_batch_enrichment(self):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return
        if self.enrichment_thread is not None or self.enrichment_task_queued:
            return

        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_countdown_label.setText('')

        if self.batch_enrichment_config.get('task_kind') == 'combo':
            self.start_combo_enrichment(
                self.batch_enrichment_config['combo_key'],
                self.batch_enrichment_config['limit'],
                self.batch_enrichment_config['show_browser'],
                self.batch_enrichment_config['cooldown_before_search'],
                combo_task_settings=self.batch_enrichment_config.get('combo_task_settings', {}),
                mode='combo_batch',
            )
            return

        self.start_enrichment(
            self.batch_enrichment_config['limit'],
            self.batch_enrichment_config['show_browser'],
            self.batch_enrichment_config['cooldown_before_search'],
            self.batch_enrichment_config['target_type'],
            self.batch_enrichment_config['source_key'],
            mode='batch',
        )

    def start_combo_batch_plan(self, values):
        combo_task_settings = self._build_combo_task_settings_for_mode(
            values.get('combo_task_settings', {}),
            use_batch_limit=True,
        )
        effective_limit = self._combo_default_limit(combo_task_settings, fallback=values['batch_limit'])
        self.batch_enrichment_active = True
        self.batch_enrichment_config = {
            'task_kind': 'combo_plan',
            'combo_key': values['combo_key'],
            'combo_task_settings': combo_task_settings,
            'batch_count_limit': max(1, int(values.get('batch_count', 1) or 1)),
        }
        self.batch_enrichment_round = 0
        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_countdown_label.setText(tr('main.combo_plan_countdown'))
        self.update_enrichment_controls()
        self.start_combo_enrichment(
            values['combo_key'],
            effective_limit,
            values['show_browser'],
            values['cooldown_before_search'],
            combo_task_settings=combo_task_settings,
            mode='combo_batch',
            batch_mode=True,
        )
        self.status_label.setText(tr('main.combo_plan_status'))

    @staticmethod
    def _build_combo_task_settings_for_mode(combo_task_settings, use_batch_limit):
        normalized = {}
        for task_key, task_settings in dict(combo_task_settings or {}).items():
            current = dict(task_settings or {})
            limit_key = 'batch_limit' if use_batch_limit else 'limit'
            normalized[task_key] = {
                'target_type': current.get('target_type'),
                'source_key': current.get('source_key'),
                'limit': max(1, int(current.get(limit_key, current.get('limit', 1)) or 1)),
                'batch_count_limit': max(
                    1,
                    int(current.get('batch_count_limit', current.get('batch_count', 1)) or 1),
                ),
                'show_browser': bool(current.get('show_browser')),
                'cooldown_before_search': bool(current.get('cooldown_before_search')),
                'batch_interval_minutes': max(1, int(current.get('batch_interval_minutes', 1) or 1)),
            }
        return normalized

    @staticmethod
    def _combo_default_limit(combo_task_settings, fallback=1):
        limits = [
            max(1, int((task_settings or {}).get('limit', 0) or 0))
            for task_settings in dict(combo_task_settings or {}).values()
            if int((task_settings or {}).get('limit', 0) or 0) > 0
        ]
        if limits:
            return max(limits)
        return max(1, int(fallback or 1))

    @staticmethod
    def _combo_batch_interval_minutes(combo_task_settings, fallback=1):
        intervals = [
            max(1, int((task_settings or {}).get('batch_interval_minutes', 0) or 0))
            for task_settings in dict(combo_task_settings or {}).values()
            if int((task_settings or {}).get('batch_interval_minutes', 0) or 0) > 0
        ]
        if intervals:
            return max(intervals)
        return max(1, int(fallback or 1))

    def schedule_next_batch_enrichment(self, last_result=None):
        if not self.batch_enrichment_active or self.batch_enrichment_config is None:
            return

        interval_minutes = max(1, int(self.batch_enrichment_config['interval_minutes']))
        interval_seconds = interval_minutes * 60
        self.batch_next_run_at = time.time() + interval_seconds
        self.batch_timer.start(interval_seconds * 1000)
        self.batch_countdown_timer.start()
        if last_result and int(last_result.get('processed_count', 0) or 0) <= 0:
            entity_label = str(last_result.get('entity_label', tr('main.batch_entity_default')) or tr('main.batch_entity_default'))
            message = str(last_result.get('message', '') or '').strip()
            status_text = tr(
                'main.batch_no_items',
                round_number=self.batch_enrichment_round,
                entity_label=entity_label,
                interval_minutes=interval_minutes,
            )
            if message:
                status_text = tr('main.batch_current_hint', status_text=status_text, message=message)
            self.status_label.setText(status_text)
        else:
            self.status_label.setText(
                tr(
                    'main.batch_round_completed',
                    round_number=self.batch_enrichment_round,
                    interval_minutes=interval_minutes,
                )
            )
        self.update_batch_countdown()
        self.update_enrichment_controls()
        self.reset_progress_widgets()

    def stop_batch_enrichment(self, message=None):
        message = message or tr('main.batch_stopped')
        self.batch_timer.stop()
        self.batch_countdown_timer.stop()
        self.batch_next_run_at = None
        self.batch_enrichment_active = False
        self.batch_enrichment_config = None
        self._active_enrichment_batch_plan_state = None
        self.update_enrichment_controls()
        self.status_label.setText(message)
        self.batch_countdown_label.setText('')
        self.reset_progress_widgets()

    def update_batch_countdown(self):
        if self.batch_next_run_at is None:
            self.batch_countdown_label.setText('')
            return

        remaining_seconds = max(0, int(round(self.batch_next_run_at - time.time())))
        minutes, seconds = divmod(remaining_seconds, 60)
        hours, minutes = divmod(minutes, 60)

        if remaining_seconds <= 0:
            self.batch_countdown_timer.stop()
            self.batch_countdown_label.setText(tr('main.next_batch_soon'))
            return

        if hours > 0:
            countdown_text = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        else:
            countdown_text = f'{minutes:02d}:{seconds:02d}'
        self.batch_countdown_label.setText(tr('main.batch_countdown', countdown_text=countdown_text))

    def update_enrichment_controls(self):
        enrichment_running = self.enrichment_thread is not None or self.enrichment_task_queued
        self.btn_enrich.setEnabled(True)
        self.btn_stop_enrich.setEnabled(enrichment_running or self.batch_enrichment_active)
        self.update_network_guard()

    def update_network_guard(self):
        self.start_network_guard()
        if not self._has_active_enrichment_plan():
            self.network_stop_requested = False

    def start_network_guard(self):
        if self.network_guard_timer.isActive():
            return
        self.network_guard_timer.start()

    def stop_network_guard(self):
        self.network_guard_timer.stop()
        self.network_guard_failure_count = 0
        self.network_stop_requested = False
        self.network_last_probe_online = None
        self.update_network_status_label()

    def check_network_guard(self):
        try:
            self.ensure_backend_running()
        except Exception:
            pass
        try:
            probe_result = self.network_guard_service.probe()
        except Exception:
            self.network_last_probe_online = None
            self.update_network_status_label()
            return

        if bool((probe_result or {}).get('is_online')):
            self.network_guard_failure_count = 0
            self.network_stop_requested = False
            self.network_last_probe_online = True
            self.update_network_status_label(probe_result=probe_result)
            return

        self.network_guard_failure_count += 1
        self.network_last_probe_online = False
        self.update_network_status_label(probe_result=probe_result)
        if not self._has_active_enrichment_plan():
            self.network_stop_requested = False
            return
        if self.network_stop_requested:
            return
        if self.network_guard_failure_count < self.network_guard_service.required_failures:
            return

        self.network_stop_requested = True
        self.handle_network_disconnect(probe_result)

    def update_network_status_label(self, probe_result=None):
        if self.network_last_probe_online is True:
            self.network_status_label.setText(tr('main.network_status_online'))
            self.network_status_label.setStyleSheet('color: #1b7f3b;')
            reachable_target = str((probe_result or {}).get('reachable_target', '') or '').strip()
            self.network_status_label.setToolTip(reachable_target)
            return
        if self.network_last_probe_online is False:
            self.network_status_label.setText(
                tr(
                    'main.network_status_offline',
                    count=self.network_guard_failure_count,
                    threshold=self.network_guard_service.required_failures,
                )
            )
            self.network_status_label.setStyleSheet('color: #b42318;')
            failed_targets = ' / '.join((probe_result or {}).get('failed_targets', [])[:3]) or tr('common.unknown')
            self.network_status_label.setToolTip(failed_targets)
            return
        self.network_status_label.setText(tr('main.network_status_unknown'))
        self.network_status_label.setStyleSheet('color: #667085;')
        self.network_status_label.setToolTip('')

    def _has_active_enrichment_plan(self):
        return bool(self.enrichment_thread is not None or self.enrichment_task_queued or self.batch_enrichment_active)

    def toggle_runtime_mode(self):
        next_mode = RUN_MODE_VIEW if getattr(self, 'runtime_mode', RUN_MODE_TASK) == RUN_MODE_TASK else RUN_MODE_TASK
        self.set_runtime_mode(next_mode)

    def set_runtime_mode(self, run_mode):
        normalized_mode = RUN_MODE_VIEW if str(run_mode or '').strip() == RUN_MODE_VIEW else RUN_MODE_TASK
        previous_mode = getattr(self, 'runtime_mode', RUN_MODE_TASK)
        self.runtime_mode = normalized_mode
        save_runtime_mode(run_mode=normalized_mode)
        queue = getattr(self, 'task_queue', None) or get_gui_task_queue()
        queue.set_run_mode(normalized_mode)
        if hasattr(self, 'runtime_mode_label'):
            if normalized_mode == RUN_MODE_VIEW:
                self.runtime_mode_label.setText('查看模式')
                if hasattr(self.runtime_mode_label, 'setStyleSheet'):
                    self.runtime_mode_label.setStyleSheet('color: #2563eb; font-weight: 700;')
            else:
                self.runtime_mode_label.setText('任务模式')
                if hasattr(self.runtime_mode_label, 'setStyleSheet'):
                    self.runtime_mode_label.setStyleSheet('color: #1b7f3b; font-weight: 700;')
        if hasattr(self, 'btn_runtime_mode'):
            self.btn_runtime_mode.setText('切换任务模式' if normalized_mode == RUN_MODE_VIEW else '切换查看模式')
        if normalized_mode == RUN_MODE_VIEW and VidNormApp._has_active_enrichment_plan(self):
            self.stop_enrichment()
        if normalized_mode == RUN_MODE_VIEW:
            queen_window = getattr(self, 'queen_library_window', None)
            if (
                queen_window is not None
                and hasattr(queen_window, 'is_async_task_running')
                and queen_window.is_async_task_running()
                and hasattr(queen_window, 'stop_crawl')
            ):
                queen_window.stop_crawl()
        elif (
            previous_mode != normalized_mode
            and hasattr(self, 'backend_client')
            and hasattr(self, 'task_queue')
        ):
            self.recover_unfinished_enrichment_plans()
        if hasattr(self, 'update_enrichment_controls'):
            self.update_enrichment_controls()
        return normalized_mode

    def recover_unfinished_enrichment_plans(self):
        recover = getattr(self.backend_client, 'recover_enrichment_plans', None)
        if callable(recover):
            try:
                recover('程序启动恢复')
            except Exception:
                return []
        if getattr(self, 'runtime_mode', RUN_MODE_TASK) != RUN_MODE_TASK:
            return []
        list_plans = getattr(self.backend_client, 'list_enrichment_plans', None)
        if not callable(list_plans):
            return []
        try:
            plans = list(list_plans(resumable_only=True) or [])
        except Exception:
            return []
        for plan in plans:
            self._enqueue_resumed_enrichment_plan(plan)
        return plans

    def _enqueue_resumed_enrichment_plan(self, plan):
        plan = dict(plan or {})
        plan_id = str(plan.get('plan_id') or '').strip()
        if not plan_id or self.task_queue.has_plan(plan_id):
            return False
        target_type = str(plan.get('target_type') or 'video_library').strip() or 'video_library'
        source_key = str(plan.get('source_key') or '').strip()
        batch_limit = max(1, int(plan.get('batch_limit', 1) or 1))
        batch_total = max(1, int(plan.get('batch_count_limit', 1) or 1))
        batch_current = int(plan.get('completed_batch_count', 0) or 0)
        is_batch = batch_total > 1
        self._active_enrichment_batch_plan_state = dict(plan) if is_batch else None
        if is_batch:
            self.batch_enrichment_active = True
            self.batch_enrichment_config = {
                'task_kind': 'single',
                'limit': batch_limit,
                'batch_count_limit': batch_total,
                'interval_minutes': 1,
                'show_browser': False,
                'cooldown_before_search': False,
                'target_type': target_type,
                'source_key': source_key,
            }
            self.batch_enrichment_round = batch_current
        else:
            self.batch_enrichment_active = False
            self.batch_enrichment_config = None
        self.start_enrichment(
            batch_limit,
            False,
            False,
            target_type,
            source_key,
            mode='batch' if is_batch else 'single',
            resume_plan=plan,
        )
        return True

    def _start_queued_gui_runner(
        self,
        task_title,
        worker_factory,
        finished_handler,
        failed_handler,
        cleanup_handler=None,
        source='主界面',
        before_start=None,
        assign_runner=None,
        task_category=TASK_CATEGORY_VIEW,
        task_kind='',
        before_start_with_record=False,
        plan_id='',
        plan_progress=None,
    ):
        def start_runner(record):
            if callable(before_start):
                if before_start_with_record:
                    before_start(record)
                else:
                    before_start()
            attempt_state = {
                'failed': False,
                'message': '',
            }
            runner_holder = {}
            worker = worker_factory()

            def handle_finished(result):
                if record.plan_id and isinstance(result, dict) and result.get('plan_progress'):
                    get_gui_task_queue().update_plan_progress(record.plan_id, result.get('plan_progress'))
                finished_handler(result)

            def handle_failed(message):
                attempt_state['failed'] = True
                attempt_state['message'] = str(message or '')

            def handle_cleanup():
                try:
                    if callable(cleanup_handler):
                        cleanup_handler()
                    if attempt_state['failed']:
                        final_failure = get_gui_task_queue().mark_failed(record.task_id, attempt_state['message'])
                        if final_failure:
                            failed_handler(attempt_state['message'])
                        return
                    get_gui_task_queue().mark_completed(record.task_id)
                finally:
                    self._queued_gui_task_runners.pop(record.task_id, None)
                    runner_holder.pop('runner', None)

            runner = GuiTaskRunner(
                self,
                worker,
                handle_finished,
                handle_failed,
                handle_cleanup,
            )
            runner_holder['runner'] = runner
            self._queued_gui_task_runners[record.task_id] = runner
            if callable(assign_runner):
                assign_runner(worker, runner)
            runner.start()

        enqueue_kwargs = {
            'task_category': task_category,
            'task_kind': task_kind,
        }
        if plan_id:
            enqueue_kwargs['plan_id'] = plan_id
            enqueue_kwargs['plan_progress'] = plan_progress
        get_gui_task_queue().enqueue(task_title, source, start_runner, **enqueue_kwargs)
        return True

    def enqueue_startup_refresh_tasks(self):
        history = self._load_startup_refresh_history()
        startup_refresh_client = _build_refresh_client(
            self.backend_client,
            minimum_timeout=get_operation_timeout_seconds('snapshot_refresh_rebuild'),
        )
        for task_key, title, task in VidNormApp._startup_refresh_task_specs(
            self,
            refresh_client=startup_refresh_client,
        ):
            if not self._should_run_startup_refresh_task(task_key, history):
                continue

            def handle_success(result, task_key=task_key, task_title=title):
                self._record_startup_refresh_completion(task_key, task_title)
                self._on_startup_refresh_task_finished(result)

            self._start_queued_gui_runner(
                title,
                lambda task=task: BackendTaskWorker(task),
                handle_success,
                self._on_startup_refresh_task_failed,
                source='启动刷新',
            )

    def _startup_refresh_task_specs(self, refresh_client=None):
        startup_refresh_client = refresh_client or self.backend_client
        return [
            (
                'actor_library',
                '启动刷新 演员库',
                lambda: startup_refresh_client.list_actors_snapshot(
                    force_refresh=True,
                    include_update_status=False,
                ),
            ),
            (
                'code_prefix_library',
                '启动刷新 番号库',
                lambda: startup_refresh_client.list_code_prefixes_snapshot(force_refresh=True),
            ),
            (
                'data_center',
                '启动刷新 数据中心',
                lambda: startup_refresh_client.get_data_center_summary(force_refresh=True),
            ),
            (
                'video_category',
                '启动刷新 视频分类',
                lambda: startup_refresh_client.list_videos_requiring_manual_category_snapshot(force_refresh=True),
            ),
            (
                'path_library',
                '启动刷新 路径库',
                lambda: self.backend_client.get_path_library_snapshot(force_refresh=True),
            ),
            (
                'queen_library',
                '启动刷新 女王库',
                lambda: VidNormApp._refresh_queen_library_startup_payload(self),
            ),
            (
                'masterpiece',
                '启动刷新 名作堂',
                lambda: self.backend_client.list_masterpiece_entries(),
            ),
            (
                'global_medals',
                '启动刷新 勋章堂',
                lambda: self.backend_client.list_global_medals(),
            ),
            (
                'canglangge',
                '启动刷新 沧浪阁',
                lambda: self.backend_client.list_canglangge_candidates_snapshot(force_refresh=True),
            ),
        ]

    def _get_startup_refresh_history_db_path(self):
        health = self.get_backend_health() if hasattr(self, 'get_backend_health') else None
        db_path = str((health or {}).get('db_path') or '').strip()
        return Path(db_path) if db_path else DATABASE_FILE

    def _ensure_startup_refresh_history_table(self, db_path=None):
        target_path = Path(db_path or self._get_startup_refresh_history_db_path())
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(target_path), timeout=5) as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS startup_refresh_history (
                    task_key TEXT PRIMARY KEY,
                    task_title TEXT NOT NULL DEFAULT '',
                    last_completed_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )

    def _load_startup_refresh_history(self):
        try:
            db_path = self._get_startup_refresh_history_db_path()
            VidNormApp._ensure_startup_refresh_history_table(self, db_path)
            with sqlite3.connect(str(db_path), timeout=5) as conn:
                rows = conn.execute(
                    '''
                    SELECT task_key, task_title, last_completed_at, updated_at
                    FROM startup_refresh_history
                    '''
                ).fetchall()
        except sqlite3.Error:
            return {}

        history = {}
        for task_key, task_title, last_completed_at, updated_at in rows:
            normalized_key = str(task_key or '').strip()
            if not normalized_key:
                continue
            history[normalized_key] = {
                'task_key': normalized_key,
                'task_title': str(task_title or '').strip(),
                'last_completed_at': str(last_completed_at or '').strip(),
                'updated_at': str(updated_at or '').strip(),
            }
        return history

    def _should_run_startup_refresh_task(self, task_key, history, now=None):
        row = dict((history or {}).get(str(task_key or '').strip()) or {})
        last_completed_at = str(row.get('last_completed_at') or '').strip()
        if not last_completed_at:
            return True
        try:
            completed_at = datetime.strptime(last_completed_at, STARTUP_REFRESH_TIMESTAMP_FORMAT)
        except ValueError:
            return True
        current_time = now if isinstance(now, datetime) else datetime.now()
        return current_time - completed_at >= timedelta(hours=STARTUP_REFRESH_INTERVAL_HOURS)

    def _record_startup_refresh_completion(self, task_key, task_title, completed_at=None):
        normalized_key = str(task_key or '').strip()
        if not normalized_key:
            return
        completed_text = str(completed_at or time.strftime(STARTUP_REFRESH_TIMESTAMP_FORMAT)).strip()
        try:
            db_path = self._get_startup_refresh_history_db_path()
            VidNormApp._ensure_startup_refresh_history_table(self, db_path)
            with sqlite3.connect(str(db_path), timeout=5) as conn:
                conn.execute(
                    '''
                    INSERT INTO startup_refresh_history (task_key, task_title, last_completed_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(task_key) DO UPDATE SET
                        task_title = excluded.task_title,
                        last_completed_at = excluded.last_completed_at,
                        updated_at = excluded.updated_at
                    ''',
                    (
                        normalized_key,
                        str(task_title or '').strip(),
                        completed_text,
                        completed_text,
                    ),
                )
                conn.commit()
        except sqlite3.Error:
            return

    def _refresh_queen_library_startup_payload(self):
        return {
            'queens': self.backend_client.list_queen_library_snapshot(force_refresh=True),
            'keywords': self.backend_client.list_queen_keywords_snapshot(force_refresh=True),
            'stats': self.backend_client.get_queen_library_stats(),
        }

    def _on_startup_refresh_task_finished(self, _result):
        return None

    def _on_startup_refresh_task_failed(self, _message):
        return None

    def handle_network_disconnect(self, probe_result=None):
        failed_targets = ' / '.join((probe_result or {}).get('failed_targets', [])[:3]) or tr('common.unknown')
        requested_message = tr('main.network_offline_stop_requested', failed_targets=failed_targets)
        failed_message = tr('main.network_offline_stop_failed')
        warning_message = tr('main.network_offline_warning_message', failed_targets=failed_targets)

        self._request_enrichment_stop(requested_message, failed_message)
        QMessageBox.warning(
            self,
            tr('main.network_offline_warning_title'),
            warning_message,
        )

    def refresh_enrichment_progress(self):
        try:
            progress = self.backend_client.get_enrichment_progress()
        except Exception:
            return
        if progress.get('task_kind') == 'combo':
            self.refresh_combo_enrichment_progress(progress)
            return
        self.hide_combo_subtask_progress()

        total_count = int(progress.get('total_count', 0) or 0)
        processed_count = int(progress.get('processed_count', 0) or 0)
        success_count = int(progress.get('success_count', 0) or 0)
        failed_count = int(progress.get('failed_count', 0) or 0)
        progress_percent = float(progress.get('progress_percent', 0) or 0)
        target_label = str(progress.get('target_label', '') or '')
        source_label = str(progress.get('source_label', '') or '')
        current_item = str(progress.get('current_item', '') or '')
        message = str(progress.get('message', '') or '')
        is_running = bool(progress.get('is_running'))
        count_unit = str(progress.get('count_unit', '') or tr('main.progress_default_unit'))
        log_path = str(progress.get('log_path', '') or '')

        if not is_running and total_count <= 0 and not message:
            return

        label_text = target_label or tr('main.enrichment_task')
        if source_label:
            label_text = f'{label_text} / {source_label}'
        if current_item:
            label_text = f"{label_text} | {tr('common.current', value=current_item)}"
        elif message:
            label_text = f'{label_text} | {message}'
        if log_path and not is_running:
            label_text = f"{label_text} | {tr('common.log', value=log_path)}"

        self.progress_label.setText(label_text)
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_bar.setValue(int(progress_percent * 10))
        if total_count > 0:
            self.progress_bar.setFormat(
                tr(
                    'main.progress_format',
                    processed_count=processed_count,
                    total_count=total_count,
                    count_unit='',
                    success_count=success_count,
                    failed_count=failed_count,
                    progress_percent=progress_percent,
                ).replace('  |', ' |', 1)
            )
        else:
            self.progress_bar.setFormat(message or tr('common.preparing'))

        if total_count > 0:
            self.progress_bar.setFormat(
                tr(
                    'main.progress_format',
                    processed_count=processed_count,
                    total_count=total_count,
                    count_unit=count_unit,
                    success_count=success_count,
                    failed_count=failed_count,
                    progress_percent=progress_percent,
                )
            )

    def refresh_combo_enrichment_progress(self, progress):
        target_label = str(progress.get('target_label', '') or tr('main.combo_task'))
        message = str(progress.get('message', '') or '')
        current_item = str(progress.get('current_item', '') or '')
        is_running = bool(progress.get('is_running'))
        log_path = str(progress.get('log_path', '') or '')
        subtasks = list((progress.get('subtasks', {}) or {}).values())

        if not is_running and not subtasks and not message:
            return

        label_text = target_label
        if current_item:
            label_text = f"{label_text} | {tr('common.current', value=current_item)}"
        elif message:
            label_text = f'{label_text} | {message}'
        if log_path and not is_running:
            label_text = f"{label_text} | {tr('common.log', value=log_path)}"

        self.progress_label.setText(label_text)
        self.progress_label.show()
        self.progress_bar.hide()

        for index, combo_subtask_widget in enumerate(self.combo_subtask_widgets):
            if index >= len(subtasks):
                combo_subtask_widget.reset(hide_widget=True)
                continue
            task_state = dict(subtasks[index] or {})
            combo_subtask_widget.set_progress(
                title=str(task_state.get('task_label', '') or task_state.get('task_key', tr('common.subtask'))),
                processed_count=int(task_state.get('processed_count', 0) or 0),
                total_count=int(task_state.get('total_count', 0) or 0),
                success_count=int(task_state.get('success_count', 0) or 0),
                failed_count=int(task_state.get('failed_count', 0) or 0),
                progress_percent=float(task_state.get('progress_percent', 0) or 0),
                count_unit=str(task_state.get('count_unit', '') or tr('main.progress_default_unit')),
                current_item=str(task_state.get('current_item', '') or ''),
                message=str(task_state.get('message', '') or ''),
            )
        self.update_combo_batch_countdown_label(progress)

    def update_combo_batch_countdown_label(self, progress):
        if self.enrichment_mode != 'combo_batch' or not self.batch_enrichment_active:
            self.batch_countdown_label.setText('')
            return

        waiting_segments = []
        running_segments = []
        for task_state in (progress.get('subtasks', {}) or {}).values():
            task_state = dict(task_state or {})
            task_label = str(task_state.get('task_label', '') or task_state.get('task_key', tr('common.subtask')))
            detail_message = str(task_state.get('message', '') or '').strip()
            if detail_message.startswith(tr('main.combo_subtask_waiting_prefix')):
                waiting_segments.append(f'{task_label}: {detail_message}')
            elif bool(task_state.get('is_running')):
                running_segments.append(tr('main.combo_subtask_running', task_label=task_label))

        if waiting_segments or running_segments:
            self.batch_countdown_label.setText(' | '.join(waiting_segments + running_segments))
            return

        self.batch_countdown_label.setText(tr('main.combo_waiting_status'))

    def hide_combo_subtask_progress(self):
        for combo_subtask_widget in self.combo_subtask_widgets:
            combo_subtask_widget.reset(hide_widget=True)

    def reset_progress_widgets(self, keep_visible=False):
        self.enrichment_progress_timer.stop()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('0/0 | 0.0%')
        self.progress_label.setText('')
        self.hide_combo_subtask_progress()
        if keep_visible:
            self.progress_bar.show()
            self.progress_label.show()
            return
        self.progress_bar.hide()
        self.progress_label.hide()

    def stop_enrichment(self):
        self._request_enrichment_stop(
            tr('main.stop_enrichment_requested'),
            tr('main.stop_enrichment_request_failed'),
        )

    def _request_enrichment_stop(self, requested_message, failed_message):
        queue = getattr(self, 'task_queue', None) or get_gui_task_queue()
        for record in queue.records():
            if (
                record.status == TASK_STATUS_RUNNING
                and record.task_category == TASK_CATEGORY_ENRICHMENT
            ):
                queue.request_pause(record.task_id, requested_message)
        if self.enrichment_thread is None:
            if self.batch_enrichment_active:
                self.stop_batch_enrichment(requested_message)
            return

        self.btn_stop_enrich.setEnabled(False)
        if self.batch_enrichment_active:
            self.batch_timer.stop()
            self.batch_countdown_timer.stop()
            self.batch_next_run_at = None
            self.batch_countdown_label.setText('')
            self.batch_enrichment_active = False
            self.batch_enrichment_config = None
        self.status_label.setText(requested_message)
        try:
            result = self.backend_client.cancel_enrichment()
            self.status_label.setText(result.get('message', requested_message or tr('main.stop_enrichment_requested_default')))
        except Exception as exc:
            self.update_enrichment_controls()
            self.status_label.setText(failed_message)
            QMessageBox.critical(self, tr('main.stop_failed'), str(exc))

    def on_auto_login_finished(self, result):
        QMessageBox.information(
            self,
            tr('main.auto_login_completed'),
            result.get('message', tr('main.auto_login_completed_default')),
        )

    def on_auto_login_failed(self, error_message):
        QMessageBox.critical(self, tr('main.auto_login_failed'), error_message)

    def on_enrichment_finished(self, result):
        mode = self.enrichment_mode
        is_batch_mode = mode in ('batch', 'combo_batch')
        entity_label = result.get('entity_label', tr('main.entity_default'))
        summary = self.build_enrichment_summary(result)

        if result.get('requires_manual_verification'):
            message = result.get('message') or tr('main.manual_verification_message')
            if is_batch_mode:
                self.stop_batch_enrichment(tr('main.manual_verification_batch_stopped'))
            else:
                self.status_label.setText('')
            QMessageBox.warning(self, tr('main.manual_verification_title'), f'{message}\n\n{summary}')
            return

        if mode == 'combo_batch':
            if not self.batch_enrichment_active:
                self.status_label.setText(tr('main.combo_plan_stopped'))
                self.batch_countdown_label.setText('')
                QMessageBox.information(self, tr('main.combo_plan_stopped_title'), summary)
                return

            self.stop_batch_enrichment(tr('main.combo_plan_ended'))
            QMessageBox.information(self, tr('main.combo_plan_ended_title'), summary)
            return

        if is_batch_mode:
            if not self.batch_enrichment_active:
                self.status_label.setText(tr('main.batch_stopped'))
                QMessageBox.information(self, tr('main.batch_stopped_title'), summary)
                return

            has_more_pending = result.get('has_more_pending')
            if has_more_pending is None:
                has_more_pending = int(result.get('remaining_count', 0) or 0) > 0

            if not has_more_pending:
                self.stop_batch_enrichment(tr('main.batch_completed'))
                QMessageBox.information(self, tr('main.enrichment_completed_title'), summary)
                return

            batch_count_limit = max(
                1,
                int((getattr(self, 'batch_enrichment_config', None) or {}).get('batch_count_limit', 1) or 1),
            )
            if int(getattr(self, 'batch_enrichment_round', 0) or 0) >= batch_count_limit:
                self.stop_batch_enrichment(tr('main.batch_count_completed'))
                QMessageBox.information(self, tr('main.enrichment_completed_title'), summary)
                return

            self.schedule_next_batch_enrichment(last_result=result)
            return

        title = tr('main.enrichment_stopped_title') if result.get('stopped') else tr('main.enrichment_completed_title')
        QMessageBox.information(self, title, summary)
        self.status_label.setText('')

    def on_enrichment_failed(self, error_message):
        mode = self.enrichment_mode
        if mode in ('batch', 'combo_batch'):
            self.stop_batch_enrichment(tr('main.batch_failed'))
            QMessageBox.critical(self, tr('main.batch_failed_title'), error_message)
            return

        self.status_label.setText('')
        QMessageBox.critical(self, tr('main.enrichment_failed_title'), error_message)

    def build_enrichment_summary(self, result):
        if result.get('task_kind') == 'combo':
            lines = [
                tr('main.combo_summary_title', combo_label=result.get('combo_label', '')),
                tr('main.combo_summary_hint'),
            ]
            for task_key, task_result in (result.get('subtask_results', {}) or {}).items():
                task_label = task_result.get('task_label') or task_result.get('entity_label') or task_key
                count_unit = task_result.get('count_unit') or tr('main.summary_count_unit_default')
                lines.append(
                    tr(
                        'main.combo_summary_task',
                        task_label=task_label,
                        processed_count=task_result.get('processed_count', 0),
                        count_unit=count_unit,
                        success_count=task_result.get('success_count', 0),
                        failed_count=task_result.get('failed_count', 0),
                        remaining_count=task_result.get('remaining_count', 0),
                    )
                )
            if result.get('message'):
                lines.append(tr('common.message', value=result.get('message')))
            if result.get('log_path'):
                lines.append(tr('common.log', value=result.get('log_path')))
            return '\n'.join(lines)

        count_unit = result.get('count_unit') or result.get('entity_label', tr('main.summary_count_unit_default'))
        remaining_label = result.get('remaining_label', tr('common.remaining_default'))
        lines = [
            tr(
                'main.summary_line_processed',
                processed_count=result.get('processed_count', 0),
                count_unit=count_unit,
            ),
            tr('main.summary_line_success', success_count=result.get('success_count', 0)),
            tr('main.summary_line_failed', failed_count=result.get('failed_count', 0)),
            tr(
                'main.summary_line_remaining',
                remaining_label=remaining_label,
                remaining_count=result.get('remaining_count', 0),
                count_unit=count_unit,
            ),
        ]
        if result.get('message'):
            lines.append(tr('common.message', value=result.get('message')))
        if result.get('log_path'):
            lines.append(tr('common.log', value=result.get('log_path')))
        return '\n'.join(lines)

    def cleanup_auto_login_thread(self):
        self.login_task_queued = False
        self.btn_auto_login.setEnabled(True)
        self.status_label.setText('')
        self.login_worker = None
        self.login_thread = None
        self.login_task_runner = None

    def cleanup_enrichment_thread(self):
        self.enrichment_task_queued = False
        self.enrichment_worker = None
        self.enrichment_thread = None
        self.enrichment_task_runner = None
        self.current_enrichment_kind = 'single'
        self.enrichment_mode = None
        self._queued_enrichment_worker_factory = None
        self._queued_enrichment_task_title = ''
        self._queued_enrichment_batch_plan_payload = None
        self._queued_enrichment_batch_plan_state = None
        self.update_enrichment_controls()
        if not self.batch_enrichment_active:
            self.reset_progress_widgets()

    def reset_browser_profile(self):
        answer = QMessageBox.question(
            self,
            tr('main.reset_browser_profile_title'),
            tr('main.reset_browser_profile_message'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: self.backend_client.reset_browser_profile(),
            self._on_reset_browser_profile_finished,
            tr('common.reset_failed'),
            task_title='主界面 重置浏览器环境',
        )

    def force_exit_application(self):
        answer = QMessageBox.warning(
            self,
            tr('main.force_exit_title'),
            tr('main.force_exit_message'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return False
        VidNormApp._force_exit_process(0)
        return True

    @staticmethod
    def _force_exit_process(exit_code=0):
        os._exit(int(exit_code or 0))

    def start_async_task(self, task, success_handler, error_title=None, block_ui=True, **kwargs):
        return super().start_async_task(task, success_handler, error_title, block_ui=block_ui, **kwargs)

    def _set_async_busy(self, busy):
        self.btn_browse.setEnabled(not busy)
        self.btn_path_library.setEnabled(not busy)
        self.btn_scan.setEnabled(not busy)
        self.btn_import_db.setEnabled(not busy and any(bool(plan.get('import_required')) for plan in self.pending_renames))
        self.btn_execute.setEnabled(
            not busy and any(bool(plan.get('can_rename') and plan.get('needs_rename')) for plan in self.pending_renames)
        )
        self.btn_reset_browser_profile.setEnabled(not busy)
        self.btn_status_sync.setEnabled(not busy)
        self.btn_refresh_detail_snapshots.setEnabled(not busy)
        self.btn_task_queue.setEnabled(True)
        self.btn_timeout_settings.setEnabled(True)
        self.btn_force_exit.setEnabled(True)
        self.table.setEnabled(not busy)
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def _apply_scan_result(self, result):
        result = dict(result or {})
        self.pending_renames = result.get('plans', [])
        self.table.setRowCount(0)

        has_files_to_rename = False
        has_files_to_import = False
        for row, plan in enumerate(self.pending_renames):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plan.get('old_name', '')))
            self.table.setItem(row, 1, QTableWidgetItem(plan.get('preview_name', '')))

            row_status = plan.get('row_status', '')
            status_item = QTableWidgetItem(row_status)
            status_item.setForeground(self._status_color(row_status))
            self.table.setItem(row, 2, status_item)

            has_files_to_rename = has_files_to_rename or bool(plan.get('can_rename') and plan.get('needs_rename'))
            has_files_to_import = has_files_to_import or bool(plan.get('import_required'))

        self.btn_execute.setEnabled(has_files_to_rename)
        self.btn_import_db.setEnabled(has_files_to_import)

    def _on_scan_finished(self, payload):
        scan_result = dict((payload or {}).get('scan_result', {}) or {})
        self._apply_scan_result(scan_result)
        if (payload or {}).get('show_message'):
            QMessageBox.information(
                self,
                tr('main.scan_completed'),
                tr(
                    'main.scan_completed_message',
                    count=scan_result.get('count', 0),
                    import_count=scan_result.get('import_count', 0),
                    rename_count=scan_result.get('rename_count', 0),
                ),
            )

    def _on_import_finished(self, payload):
        self._apply_scan_result((payload or {}).get('scan_result', {}))
        success_count = int((payload or {}).get('success_count', 0) or 0)
        QMessageBox.information(
            self,
            tr('main.import_completed'),
            tr('main.import_completed_message', success_count=success_count),
        )

    def _on_execute_rename_finished(self, payload):
        self._apply_scan_result((payload or {}).get('scan_result', {}))
        success_count = int((payload or {}).get('success_count', 0) or 0)
        QMessageBox.information(
            self,
            tr('main.result'),
            tr('main.rename_completed_message', success_count=success_count),
        )

    def _on_reset_browser_profile_finished(self, result):
        result = dict(result or {})
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr(
                'main.reset_completed_message',
                message=result.get('message', tr('main.reset_completed_default')),
                profile_dir=result.get('profile_dir', ''),
            ),
        )

    def sync_library_statuses(self):
        if self.enrichment_thread is not None or self.batch_enrichment_active:
            QMessageBox.information(
                self,
                tr('main.enrichment_in_progress_title'),
                tr('main.enrichment_in_progress_message'),
            )
            return

        self.start_async_task(
            lambda: self.backend_client.sync_library_statuses(),
            self._on_sync_library_statuses_finished,
            tr('common.operation_failed'),
            task_title='主界面 同步库状态',
        )

    def _on_sync_library_statuses_finished(self, result):
        result = dict(result or {})
        QMessageBox.information(
            self,
            tr('main.status_sync_completed_title'),
            tr(
                'main.status_sync_completed_message',
                candidate_code_count=int(result.get('candidate_code_count', 0) or 0),
                shared_code_count=int(result.get('shared_code_count', 0) or 0),
                synced_code_count=int(result.get('synced_code_count', 0) or 0),
                updated_code_prefix_movie_count=int(result.get('updated_code_prefix_movie_count', 0) or 0),
                updated_actor_movie_count=int(result.get('updated_actor_movie_count', 0) or 0),
                updated_prefix_count=int(result.get('updated_prefix_count', 0) or 0),
                updated_actor_count=int(result.get('updated_actor_count', 0) or 0),
                message=str(result.get('message', '') or tr('main.status_sync_completed_default')),
            ),
        )

    def refresh_detail_snapshots(self):
        self.start_async_task(
            lambda: self.backend_client.rebuild_detail_snapshots(),
            self._on_refresh_detail_snapshots_finished,
            tr('common.operation_failed'),
            task_title='主界面 全量刷新快照',
        )

    def _on_refresh_detail_snapshots_finished(self, result):
        result = dict(result or {})
        QMessageBox.information(
            self,
            '快照刷新完成',
            (
                f"演员快照: {int(result.get('actor_refreshed', 0) or 0)}/"
                f"{int(result.get('actor_total', 0) or 0)}\n"
                f"番号快照: {int(result.get('code_prefix_refreshed', 0) or 0)}/"
                f"{int(result.get('code_prefix_total', 0) or 0)}"
            ),
        )

    def show_data_center(self):
        key = ('data_center', 'summary')
        viewer = self.window_coordinator.get_window(key)
        if viewer is None:
            viewer = DataCenterWindow(
                backend_client=self.backend_client,
                parent=self,
                coordinator=self.window_coordinator,
            )
            self.window_coordinator.register_window(key, viewer)
        self.window_coordinator.activate(viewer)

    def show_video_library(self):
        self.window_coordinator.open_list(EntityType.VIDEO, QueryContext(source='main_video_library'))

    def show_actor_viewer(self):
        self.window_coordinator.open_list(EntityType.ACTOR, QueryContext(source='main_actor_library'))

    def show_code_prefix_viewer(self):
        self.window_coordinator.open_list(EntityType.CODE_PREFIX, QueryContext(source='main_code_prefix_library'))

    def show_canglangge_viewer(self):
        viewer = CanglanggeViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_video_category_viewer(self):
        viewer = VideoCategoryViewerWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_ladder_board_viewer(self):
        self.window_coordinator.open_list(EntityType.LADDER, QueryContext(source='main_ladder'))

    def show_masterpiece_viewer(self):
        self.window_coordinator.open_list(EntityType.MASTERPIECE, QueryContext(source='main_masterpiece'))

    def show_unified_search(self):
        key = ('search', 'unified')
        viewer = self.window_coordinator.get_window(key)
        if viewer is None:
            viewer = UnifiedSearchWindow(
                self.backend_client,
                self.window_coordinator,
                self,
                history_store=self.query_history,
            )
            self.window_coordinator.register_window(key, viewer)
        self.window_coordinator.activate(viewer)

    def _configure_window_coordinator(self):
        self.window_coordinator.set_factory(EntityType.VIDEO, self._create_video_entity_window)
        self.window_coordinator.set_factory(EntityType.ACTOR, self._create_actor_entity_window)
        self.window_coordinator.set_factory(EntityType.CODE_PREFIX, self._create_code_prefix_entity_window)
        self.window_coordinator.set_factory(EntityType.MASTERPIECE, self._create_masterpiece_entity_window)
        self.window_coordinator.set_comparison_factory(self._create_comparison_window)
        self.window_coordinator.set_factory('list:video', lambda _context: DatabaseViewerWindow(self.backend_client, self))
        self.window_coordinator.set_factory(
            'list:actor',
            lambda _context: ActorViewerWindow(self.backend_client, self, coordinator=self.window_coordinator),
        )
        self.window_coordinator.set_factory(
            'list:code_prefix',
            lambda _context: CodePrefixViewerWindow(self.backend_client, self, coordinator=self.window_coordinator),
        )
        self.window_coordinator.set_factory(
            'list:ladder',
            lambda _context: LadderBoardWindow(self.backend_client, self, coordinator=self.window_coordinator),
        )
        self.window_coordinator.set_factory(
            'list:masterpiece',
            lambda _context: MasterpieceWindow(self.backend_client, self, coordinator=self.window_coordinator),
        )

    def _create_video_entity_window(self, _reference, _context):
        return DatabaseViewerWindow(self.backend_client, self)

    def _create_actor_entity_window(self, reference, _context):
        from app.gui.actor_detail_viewer import ActorDetailViewerWindow

        return ActorDetailViewerWindow(
            self.backend_client,
            reference.entity_key,
            self,
            coordinator=self.window_coordinator,
        )

    def _create_code_prefix_entity_window(self, reference, _context):
        return CodePrefixDetailViewerWindow(
            self.backend_client,
            reference.entity_key,
            self,
            coordinator=self.window_coordinator,
        )

    def _create_masterpiece_entity_window(self, reference, _context):
        return MasterpieceDetailWindow(
            self.backend_client,
            reference.entity_key,
            self,
            coordinator=self.window_coordinator,
        )

    def _create_comparison_window(self, first, second):
        return ComparisonWindow(self.backend_client, first, second, self)

    def show_medal_catalog_viewer(self):
        viewer = MedalCatalogWindow(backend_client=self.backend_client, parent=self)
        viewer.exec_()

    def show_queen_library_viewer(self):
        viewer = self.__dict__.get('queen_library_window')
        if viewer is None:
            viewer = QueenLibraryWindow(backend_client=self.backend_client, parent=self)
            self.queen_library_window = viewer
            if hasattr(viewer, 'destroyed'):
                viewer.destroyed.connect(lambda *_args: setattr(self, 'queen_library_window', None))
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def show_task_queue_viewer(self):
        viewer = self.__dict__.get('task_queue_window')
        if viewer is None:
            viewer = TaskQueueViewerWindow(parent=self)
            self.task_queue_window = viewer
            if hasattr(viewer, 'destroyed'):
                viewer.destroyed.connect(lambda *_args: setattr(self, 'task_queue_window', None))
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def show_timeout_settings_viewer(self):
        viewer = self.__dict__.get('timeout_settings_window')
        if viewer is None:
            viewer = TimeoutSettingsViewerWindow(self.backend_client, self)
            self.timeout_settings_window = viewer
            if hasattr(viewer, 'destroyed'):
                viewer.destroyed.connect(
                    lambda *_args: setattr(self, 'timeout_settings_window', None)
                )
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def refresh_task_queue_indicator(self):
        queue = getattr(self, 'task_queue', None) or get_gui_task_queue()
        self._update_task_queue_indicator(queue.is_all_done())

    def _update_task_queue_indicator(self, is_done=False):
        if not hasattr(self, 'btn_task_queue'):
            return
        if is_done:
            self.btn_task_queue.setStyleSheet('QPushButton { background-color: #16a34a; }')
            return
        self.btn_task_queue.setStyleSheet('')

    def show_video_filter_dialog(self):
        dialog = VideoFilterDialog(self)
        dialog.exec_()

    def show_path_library(self):
        viewer = PathLibraryWindow(backend_client=self.backend_client, parent=self)
        if viewer.exec_() and viewer.selected_path:
            self.set_current_folder(viewer.selected_path)

    def start_snapshot_refresh_scheduler(self):
        self.snapshot_refresh_timer.start()
        QTimer.singleShot(SNAPSHOT_REFRESH_STARTUP_DELAY_MS, lambda: VidNormApp.run_startup_refresh_sequence(self))

    def run_startup_refresh_sequence(self):
        self.schedule_snapshot_refresh_cycle()
        self.enqueue_startup_refresh_tasks()

    def schedule_snapshot_refresh_cycle(self):
        if self.snapshot_refresh_running or getattr(self, 'snapshot_refresh_queued', False):
            return False
        if not self._should_run_snapshot_refresh_cycle():
            return False
        self.snapshot_refresh_queued = True

        def worker_factory():
            worker = self._create_snapshot_refresh_worker()
            progress_signal = getattr(worker, 'progress', None)
            if progress_signal is not None and hasattr(progress_signal, 'connect'):
                progress_signal.connect(self._on_snapshot_refresh_progress)
            return worker

        def before_start():
            self.snapshot_refresh_queued = False
            self.snapshot_refresh_running = True

        def assign_snapshot_runner(worker, runner):
            self.snapshot_refresh_worker = worker
            self.snapshot_refresh_task_runner = runner

        self._start_queued_gui_runner(
            SNAPSHOT_REFRESH_HISTORY_TASK_TITLE,
            worker_factory,
            self._on_snapshot_refresh_finished,
            self._on_snapshot_refresh_failed,
            cleanup_handler=self._cleanup_snapshot_refresh_attempt,
            before_start=before_start,
            assign_runner=assign_snapshot_runner,
        )
        return True

    def _should_run_snapshot_refresh_cycle(self):
        try:
            history = self._load_startup_refresh_history()
            should_run_task = getattr(self, '_should_run_startup_refresh_task', None)
            if not callable(should_run_task):
                should_run_task = lambda task_key, task_history: VidNormApp._should_run_startup_refresh_task(
                    self,
                    task_key,
                    task_history,
                )
            if SNAPSHOT_REFRESH_HISTORY_TASK_KEY in history:
                return should_run_task(SNAPSHOT_REFRESH_HISTORY_TASK_KEY, history)
            component_keys = ('actor_library', 'code_prefix_library')
            if all(
                not should_run_task(component_key, history)
                for component_key in component_keys
            ):
                return False
            return True
        except Exception:
            return True

    def _cleanup_snapshot_refresh_attempt(self):
        self.snapshot_refresh_running = False
        self.snapshot_refresh_worker = None
        self.snapshot_refresh_task_runner = None

    def _create_snapshot_refresh_worker(self):
        refresh_client = _build_refresh_client(
            self.backend_client,
            minimum_timeout=get_operation_timeout_seconds('snapshot_refresh_rebuild'),
        )
        return SnapshotRefreshWorker(
            lambda progress_callback: self._run_snapshot_refresh_cycle(
                progress_callback=progress_callback,
                refresh_client=refresh_client,
            )
        )

    def _run_snapshot_refresh_cycle(self, progress_callback=None, refresh_client=None):
        active_client = refresh_client or _build_refresh_client(
            self.backend_client,
            minimum_timeout=get_operation_timeout_seconds('snapshot_refresh_rebuild'),
        )
        self.snapshot_refresh_running = True
        try:
            VidNormApp._emit_snapshot_refresh_progress(progress_callback, 'actor_library', '演员库')
            active_client.list_actors_snapshot(force_refresh=True, include_update_status=False)
            VidNormApp._emit_snapshot_refresh_progress(progress_callback, 'code_prefix_library', '番号库')
            active_client.list_code_prefixes_snapshot(force_refresh=True)
            return {'success': True}
        finally:
            self.snapshot_refresh_running = False

    @staticmethod
    def _emit_snapshot_refresh_progress(progress_callback, target_key, target_label):
        if not callable(progress_callback):
            return
        progress_callback(
            {
                'target_key': str(target_key or '').strip(),
                'target_label': str(target_label or '').strip(),
                'elapsed_seconds': 0,
            }
        )

    def _on_snapshot_refresh_progress(self, payload):
        current = dict(payload or {})
        self.snapshot_refresh_current_target = str(current.get('target_label', '') or '').strip()
        self.snapshot_refresh_started_at = time.time()
        VidNormApp._set_snapshot_refresh_indicator_state(
            self,
            state='refreshing',
            status_text=VidNormApp._build_snapshot_refresh_status_text(self.snapshot_refresh_current_target, 0),
        )
        self.snapshot_refresh_elapsed_timer.start()

    def update_snapshot_refresh_elapsed(self):
        if not str(self.snapshot_refresh_current_target or '').strip():
            self.snapshot_refresh_elapsed_timer.stop()
            return
        elapsed_seconds = max(0, int(time.time() - float(self.snapshot_refresh_started_at or 0.0)))
        VidNormApp._set_snapshot_refresh_indicator_state(
            self,
            state='refreshing',
            status_text=VidNormApp._build_snapshot_refresh_status_text(
                self.snapshot_refresh_current_target,
                elapsed_seconds,
            ),
        )

    @staticmethod
    def _build_snapshot_refresh_status_text(target_label, elapsed_seconds):
        current_target = str(target_label or '').strip() or '后台任务'
        return f'后台刷新: 正在刷新 {current_target} | 已耗时 {max(0, int(elapsed_seconds or 0))}秒'

    @staticmethod
    def _build_snapshot_refresh_idle_status_text(completed_at):
        normalized_completed_at = str(completed_at or '').strip()
        if normalized_completed_at:
            return f'后台刷新: 最近完成于 {normalized_completed_at}'
        return '后台刷新: 等待执行'

    @staticmethod
    def _set_snapshot_refresh_indicator_state(window, state='idle', status_text=''):
        current_state = str(state or '').strip().lower()
        red_color = '#dc2626' if current_state in ('refreshing', 'failed') else '#cbd5e1'
        green_color = '#16a34a' if current_state == 'idle' else '#cbd5e1'
        if hasattr(window, 'snapshot_refresh_red_light_label'):
            window.snapshot_refresh_red_light_label.setStyleSheet(
                f'color: {red_color}; font-size: 18px; font-weight: 700;'
            )
        if hasattr(window, 'snapshot_refresh_green_light_label'):
            window.snapshot_refresh_green_light_label.setStyleSheet(
                f'color: {green_color}; font-size: 18px; font-weight: 700;'
            )
        if hasattr(window, 'snapshot_refresh_status_label'):
            window.snapshot_refresh_status_label.setText(str(status_text or '').strip())

    def _on_snapshot_refresh_finished(self, result):
        self.snapshot_refresh_running = False
        self.snapshot_refresh_elapsed_timer.stop()
        self.snapshot_refresh_started_at = 0.0
        self.snapshot_refresh_current_target = ''
        self.snapshot_refresh_last_completed_at = time.strftime('%H:%M:%S')
        if hasattr(self, '_record_startup_refresh_completion'):
            self._record_startup_refresh_completion(
                SNAPSHOT_REFRESH_HISTORY_TASK_KEY,
                SNAPSHOT_REFRESH_HISTORY_TASK_TITLE,
            )
        VidNormApp._set_snapshot_refresh_indicator_state(
            self,
            state='idle',
            status_text=VidNormApp._build_snapshot_refresh_idle_status_text(self.snapshot_refresh_last_completed_at),
        )
        self.snapshot_refresh_worker = None
        self.snapshot_refresh_task_runner = None

    def _on_snapshot_refresh_failed(self, error_message):
        self.snapshot_refresh_running = False
        self.snapshot_refresh_elapsed_timer.stop()
        self.snapshot_refresh_started_at = 0.0
        self.snapshot_refresh_current_target = ''
        VidNormApp._set_snapshot_refresh_indicator_state(
            self,
            state='failed',
            status_text=f'后台刷新: 刷新失败 ({str(error_message or "").strip() or "未知错误"})',
        )
        self.snapshot_refresh_worker = None
        self.snapshot_refresh_task_runner = None

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        if self.enrichment_thread and self.enrichment_thread.isRunning():
            QMessageBox.information(
                self,
                tr('main.enrichment_in_progress_title'),
                tr('main.enrichment_close_wait'),
            )
            event.ignore()
            return
        if self.batch_enrichment_active or self.batch_timer.isActive():
            QMessageBox.information(
                self,
                tr('main.batch_close_wait_title'),
                tr('main.batch_close_wait'),
            )
            event.ignore()
            return
        if self.login_thread and self.login_thread.isRunning():
            QMessageBox.information(
                self,
                tr('main.login_in_progress_title'),
                tr('main.login_close_wait'),
            )
            event.ignore()
            return
        self.snapshot_refresh_timer.stop()
        self.snapshot_refresh_elapsed_timer.stop()
        self.stop_owned_backend()
        super().closeEvent(event)

    @staticmethod
    def _status_color(row_status):
        if row_status == IMPORT_REQUIRED_STATUS:
            return Qt.darkYellow
        if row_status == ENRICHMENT_REQUIRED_STATUS:
            return Qt.darkYellow
        if row_status == RENAME_REQUIRED_STATUS:
            return Qt.blue
        if row_status == NORMALIZED_STATUS:
            return Qt.darkGreen
        return Qt.black


def configure_qt_application():
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    rounding_policy_enum = getattr(Qt, 'HighDpiScaleFactorRoundingPolicy', None)
    pass_through_policy = getattr(rounding_policy_enum, 'PassThrough', None)
    if pass_through_policy is not None and hasattr(QApplication, 'setHighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(pass_through_policy)


def configure_application_font(app):
    current_font = app.font()
    if not _is_suspicious_application_font(current_font):
        return

    replacement_font = _resolve_windows_message_font()
    if replacement_font is None:
        return
    app.setFont(replacement_font)


def _is_suspicious_application_font(font):
    family = str(font.family() or '').strip().lower()
    point_size = int(font.pointSize() or 0)
    if point_size <= 0:
        return False
    if point_size <= 7:
        return True
    return family in {'simsun'} and point_size <= 8


def _resolve_windows_message_font():
    if sys.platform != 'win32':
        return None
    try:
        class LOGFONTW(ctypes.Structure):
            _fields_ = [
                ('lfHeight', ctypes.c_long),
                ('lfWidth', ctypes.c_long),
                ('lfEscapement', ctypes.c_long),
                ('lfOrientation', ctypes.c_long),
                ('lfWeight', ctypes.c_long),
                ('lfItalic', ctypes.c_ubyte),
                ('lfUnderline', ctypes.c_ubyte),
                ('lfStrikeOut', ctypes.c_ubyte),
                ('lfCharSet', ctypes.c_ubyte),
                ('lfOutPrecision', ctypes.c_ubyte),
                ('lfClipPrecision', ctypes.c_ubyte),
                ('lfQuality', ctypes.c_ubyte),
                ('lfPitchAndFamily', ctypes.c_ubyte),
                ('lfFaceName', ctypes.c_wchar * 32),
            ]

        class NONCLIENTMETRICSW(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.c_uint),
                ('iBorderWidth', ctypes.c_int),
                ('iScrollWidth', ctypes.c_int),
                ('iScrollHeight', ctypes.c_int),
                ('iCaptionWidth', ctypes.c_int),
                ('iCaptionHeight', ctypes.c_int),
                ('lfCaptionFont', LOGFONTW),
                ('iSmCaptionWidth', ctypes.c_int),
                ('iSmCaptionHeight', ctypes.c_int),
                ('lfSmCaptionFont', LOGFONTW),
                ('iMenuWidth', ctypes.c_int),
                ('iMenuHeight', ctypes.c_int),
                ('lfMenuFont', LOGFONTW),
                ('lfStatusFont', LOGFONTW),
                ('lfMessageFont', LOGFONTW),
                ('iPaddedBorderWidth', ctypes.c_int),
            ]

        metrics = NONCLIENTMETRICSW()
        metrics.cbSize = ctypes.sizeof(NONCLIENTMETRICSW)
        if not ctypes.windll.user32.SystemParametersInfoW(0x0029, metrics.cbSize, ctypes.byref(metrics), 0):
            return None

        face_name = str(metrics.lfMessageFont.lfFaceName or '').strip()
        if not face_name:
            return None

        dpi = 96.0
        desktop = ctypes.windll.user32.GetDC(0)
        if desktop:
            try:
                dpi = float(ctypes.windll.gdi32.GetDeviceCaps(desktop, 90) or 96)
            finally:
                ctypes.windll.user32.ReleaseDC(0, desktop)

        point_size = max(9, int(round((abs(int(metrics.lfMessageFont.lfHeight or -12)) * 72.0) / max(dpi, 1.0))))
        font = QFont(face_name, point_size)
        return font
    except Exception:
        return None


def main():
    configure_qt_application()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    configure_application_font(app)
    instance_guard = SingleInstanceGuard(GUI_INSTANCE_LOCK_FILE)
    if not instance_guard.acquire():
        QMessageBox.information(None, '程序已运行', '客户端已经在运行中，请使用已有窗口。')
        return 0
    try:
        window = VidNormApp()
    except Exception as exc:
        instance_guard.release()
        QMessageBox.critical(
            None,
            tr('main.start_failed_title'),
            tr('main.start_failed_message', error=str(exc)),
        )
        return 1
    window.show()
    try:
        return app.exec_()
    finally:
        instance_guard.release()


if __name__ == '__main__':
    raise SystemExit(main())
