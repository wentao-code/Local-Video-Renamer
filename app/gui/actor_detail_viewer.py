import logging

from PyQt5.QtCore import QUrl
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QDesktopServices, QFont, QFontDatabase
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.ladder_board import LADDER_BOARD_ACTOR, LADDER_TIERS
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary, format_update_frequency_summary
from app.gui.i18n import tr
from app.gui.query_context import EntityType
from app.gui.video_category_update_events import video_category_update_event_bus
from app.gui.video_filter_events import video_filter_event_bus
from app.gui.video_list_detail_viewer import VideoListDetailWindow


def _build_refresh_client(backend_client, minimum_timeout=None):
    base_url = str(getattr(backend_client, 'base_url', '') or '').strip()
    if not base_url:
        return backend_client
    timeout = None
    if minimum_timeout is not None:
        timeout = max(float(getattr(backend_client, 'timeout', 30) or 30), float(minimum_timeout))
    return BackendClient(
        base_url=base_url,
        timeout=timeout,
    )


class ActorDetailViewerWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    _COLLABORATOR_COLUMNS = 10
    _LOGGER = logging.getLogger(__name__)

    def __init__(self, backend_client, actor_name, parent=None, coordinator=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.coordinator = coordinator
        self.refresh_client = _build_refresh_client(backend_client)
        self.actor_name = str(actor_name or '').strip()
        self.detail = {}
        self.collaborator_tables = {}
        self.collaborator_grids = {}
        self.collaborator_section_labels = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self._deferred_silent_errors = False
        self._deferred_allow_deferred_close = False
        self._suppress_async_error_dialog = False
        self._detail_request_sequence = 0
        self._active_request_token = 0
        self._active_request_actor_name = self.actor_name
        self._init_async_task_host()
        self._init_deferred_reload(self._perform_deferred_load)
        video_filter_event_bus.rules_saved.connect(self.on_filter_rules_saved)
        video_category_update_event_bus.categories_updated.connect(self.on_video_categories_updated)
        self.init_ui()
        QTimer.singleShot(0, self.load_data)

    def init_ui(self):
        self.setWindowTitle(tr('actor.detail.title', actor_name=self.actor_name))
        self.setFixedSize(1200, 800)
        self.setWindowModality(Qt.NonModal)

        root_layout = QVBoxLayout(self)
        self.detail_scroll_area = QScrollArea()
        self.detail_scroll_area.setWidgetResizable(True)
        self.detail_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.detail_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        root_layout.addWidget(self.detail_scroll_area)

        content = QGroupBox()
        content.setStyleSheet('QGroupBox { border: 0; margin-top: 0; }')
        self.detail_scroll_area.setWidget(content)

        layout = QVBoxLayout(content)

        action_group = QGroupBox(tr('detail.action_group'))
        action_group.setStyleSheet(
            'QGroupBox { margin-top: 14px; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }'
        )
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(12, 18, 12, 10)
        action_layout.setSpacing(10)
        self.btn_prev_item = QPushButton(tr('detail.prev_item'))
        self.btn_prev_item.clicked.connect(self.show_previous_item)
        action_layout.addWidget(self.btn_prev_item)
        self.btn_next_item = QPushButton(tr('detail.next_item'))
        self.btn_next_item.clicked.connect(self.show_next_item)
        action_layout.addWidget(self.btn_next_item)
        self.btn_copy_actor_name = QPushButton(tr('actor.detail.copy_actor_name'))
        self.btn_copy_actor_name.clicked.connect(self.copy_actor_name)
        action_layout.addWidget(self.btn_copy_actor_name)
        self.btn_open_web = QPushButton(tr('detail.open_web'))
        self.btn_open_web.clicked.connect(self.open_web_page)
        action_layout.addWidget(self.btn_open_web)
        self.tier_combo = QComboBox()
        for tier in LADDER_TIERS:
            self.tier_combo.addItem(tier, tier)
        self.tier_combo.setMinimumHeight(30)
        self.tier_combo.setMinimumWidth(78)
        action_layout.addWidget(self.tier_combo)
        self.btn_update_tier = QPushButton(tr('detail.update_tier'))
        self.btn_update_tier.clicked.connect(self.update_ladder_tier)
        action_layout.addWidget(self.btn_update_tier)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        action_layout.addWidget(self.btn_refresh)
        self.last_refreshed_label = QLabel(tr('data_center.last_refreshed', value=tr('common.empty')))
        action_layout.addWidget(self.last_refreshed_label)
        for button in (
            self.btn_prev_item,
            self.btn_next_item,
            self.btn_copy_actor_name,
            self.btn_open_web,
            self.btn_update_tier,
            self.btn_refresh,
        ):
            button.setMinimumHeight(30)
            button.setMinimumWidth(92)
        action_layout.addStretch()

        basic_group = QGroupBox(tr('actor.detail.basic_group'))
        basic_layout = QVBoxLayout(basic_group)
        self.basic_grid = DetailSummaryGrid(columns=4)
        self.basic_grid.set_items(
            [
                ('name', tr('actor.detail.name'), ''),
                ('actor_id', tr('actor.detail.actor_id'), ''),
                ('binghuo_person_id', tr('actor.detail.binghuo_id'), ''),
                ('ladder_tier', tr('actor.detail.ladder_tier'), ''),
                ('update_status', tr('actor.detail.update_status'), ''),
                ('age', tr('actor.detail.age'), ''),
                ('birthday', tr('actor.detail.birthday'), ''),
                ('binghuo_height', tr('actor.detail.height'), ''),
                ('local_total', tr('actor.detail.local_total'), ''),
                ('web_total', tr('actor.detail.web_total'), ''),
                ('appearance_code_count', tr('actor.detail.appearance_code_count'), ''),
                ('code_prefix_library_count', tr('actor.detail.code_prefix_library_count'), ''),
                ('binghuo_cup', tr('actor.detail.cup'), ''),
                ('web_update_frequency', tr('actor.detail.update_frequency'), ''),
            ]
        )
        basic_layout.addWidget(self.basic_grid)
        self.basic_measurements_grid = DetailSummaryGrid(columns=1)
        self.basic_measurements_grid.set_items(
            [
                ('measurements', tr('actor.detail.measurements'), ''),
            ]
        )
        basic_layout.addWidget(self.basic_measurements_grid)
        self.basic_status_grid = DetailSummaryGrid(columns=1)
        self.basic_status_grid.set_items(
            [
                ('web_status', tr('actor.detail.web_status'), ''),
            ]
        )
        basic_layout.addWidget(self.basic_status_grid)

        local_group = QGroupBox(tr('actor.detail.local_group'))
        local_layout = QVBoxLayout(local_group)
        self.local_grid = DetailSummaryGrid(columns=1)
        self.local_grid.set_items(
            [
                ('local_prefix', tr('actor.detail.local_prefix'), ''),
                ('local_year', tr('actor.detail.local_year'), ''),
            ]
        )
        local_layout.addWidget(self.local_grid)

        web_group = QGroupBox(tr('actor.detail.web_group'))
        web_layout = QVBoxLayout(web_group)
        self.web_grid = DetailSummaryGrid(columns=4)
        self.web_grid.set_items(
            [
                ('eligible_video_count', tr('actor.detail.eligible_video_count'), ''),
                ('web_earliest', tr('actor.detail.web_earliest'), ''),
                ('web_latest', tr('actor.detail.web_latest'), ''),
                ('eligible_enriched_video_count', tr('actor.detail.eligible_enriched_video_count'), ''),
            ]
        )
        web_layout.addWidget(self.web_grid)
        self.web_last_enriched_grid = DetailSummaryGrid(columns=1)
        self.web_last_enriched_grid.set_items(
            [
                ('web_last_enriched', tr('actor.detail.web_last_enriched'), ''),
            ]
        )
        web_layout.addWidget(self.web_last_enriched_grid)
        self.web_prefix_grid = DetailSummaryGrid(columns=1)
        self.web_prefix_grid.set_items(
            [
                ('web_prefix', tr('actor.detail.web_prefix'), ''),
            ]
        )
        web_prefix_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        web_prefix_font.setStyleHint(QFont.TypeWriter)
        web_prefix_font.setFixedPitch(True)
        self.web_prefix_grid.value_labels['web_prefix'].setFont(web_prefix_font)
        web_layout.addWidget(self.web_prefix_grid)
        self.web_year_grid = DetailSummaryGrid(columns=1)
        self.web_year_grid.set_items(
            [
                ('web_year', tr('actor.detail.web_year'), ''),
            ]
        )
        web_layout.addWidget(self.web_year_grid)
        self.web_video_category_grid = DetailSummaryGrid(columns=1)
        self.web_video_category_grid.set_items(
            [
                ('web_video_categories', tr('actor.detail.web_video_categories'), ''),
            ]
        )
        web_layout.addWidget(self.web_video_category_grid)

        self.collaborator_group = QGroupBox('共演演员')
        self.collaborator_layout = QVBoxLayout(self.collaborator_group)

        local_movie_group = QGroupBox(tr('actor.detail.local_movie_group'))
        local_movie_layout = QVBoxLayout(local_movie_group)
        self.local_movie_count_label = QLabel(tr('actor.detail.local_movie_count', count=0))
        self.btn_local_movie_detail = QPushButton(tr('actor.detail.detail'))
        self.btn_local_movie_detail.clicked.connect(self.show_local_movie_detail)
        local_movie_top_layout = QHBoxLayout()
        local_movie_top_layout.addWidget(self.local_movie_count_label)
        local_movie_top_layout.addStretch()
        local_movie_top_layout.addWidget(self.btn_local_movie_detail)
        local_movie_layout.addLayout(local_movie_top_layout)

        web_movie_group = QGroupBox(tr('actor.detail.web_movie_group'))
        web_movie_layout = QVBoxLayout(web_movie_group)
        self.web_movie_count_label = QLabel(tr('actor.detail.web_movie_count', count=0))
        self.btn_web_movie_detail = QPushButton(tr('actor.detail.detail'))
        self.btn_web_movie_detail.clicked.connect(self.show_web_movie_detail)
        web_movie_top_layout = QHBoxLayout()
        web_movie_top_layout.addWidget(self.web_movie_count_label)
        web_movie_top_layout.addStretch()
        web_movie_top_layout.addWidget(self.btn_web_movie_detail)
        web_movie_layout.addLayout(web_movie_top_layout)

        layout.addWidget(action_group)
        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addWidget(self.collaborator_group)
        layout.addWidget(local_movie_group)
        layout.addWidget(web_movie_group)
        layout.addStretch()
        self.set_async_busy_widgets(
            [
                self.btn_prev_item,
                self.btn_next_item,
                self.btn_copy_actor_name,
                self.btn_open_web,
                self.tier_combo,
                self.btn_update_tier,
                self.btn_refresh,
                self.btn_local_movie_detail,
                self.btn_web_movie_detail,
            ]
        )

    def apply_query_context(self, context):
        entity = getattr(context, 'entity', None)
        if getattr(entity, 'entity_type', '') != 'actor':
            return
        actor_name = str(getattr(entity, 'entity_key', '') or '').strip()
        if actor_name and actor_name != self.actor_name:
            self._switch_actor(actor_name)

    def load_data(self, force_refresh=False, silent_errors=False, allow_deferred_close=False):
        if self.is_async_task_running():
            self._deferred_force_refresh = self._deferred_force_refresh or bool(force_refresh)
            self._deferred_silent_errors = self._deferred_silent_errors or bool(silent_errors)
            self._deferred_allow_deferred_close = (
                self._deferred_allow_deferred_close or bool(allow_deferred_close)
            )
            self.schedule_deferred_reload(0)
            return
        request_token = self._next_detail_request_token()
        requested_actor_name = str(self.actor_name or '').strip()
        self._active_request_token = request_token
        self._active_request_actor_name = requested_actor_name
        self._suppress_async_error_dialog = bool(silent_errors)
        self.start_async_task(
            lambda: self._load_detail_payload(
                requested_actor_name,
                force_refresh=force_refresh,
                request_token=request_token,
            ),
            self._on_load_data_finished,
            tr('common.read_failed'),
            block_ui=not bool(allow_deferred_close),
            allow_deferred_close=allow_deferred_close,
        )

    def _perform_deferred_load(self):
        force_refresh = self._deferred_force_refresh
        silent_errors = self._deferred_silent_errors
        allow_deferred_close = self._deferred_allow_deferred_close
        self._deferred_force_refresh = False
        self._deferred_silent_errors = False
        self._deferred_allow_deferred_close = False
        self.load_data(
            force_refresh=force_refresh,
            silent_errors=silent_errors,
            allow_deferred_close=allow_deferred_close,
        )

    def _load_detail_payload(self, actor_name, force_refresh=False, request_token=0):
        requested_actor_name = str(actor_name or '').strip()
        if hasattr(self.refresh_client, 'get_actor_detail_snapshot'):
            payload = self.refresh_client.get_actor_detail_snapshot(
                requested_actor_name,
                force_refresh=force_refresh,
            )
        else:
            detail = self.backend_client.get_actor_detail(requested_actor_name)
            payload = {
                'actor': dict(detail or {}),
                'refreshed_at': '',
                'cache_hit': False,
            }
        return {
            **dict(payload or {}),
            'request_token': int(request_token or 0),
            'request_actor_name': requested_actor_name,
        }

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        if not self._is_current_detail_response(payload):
            return
        self.detail = dict(payload.get('actor', payload or {}) or {})
        self._suppress_async_error_dialog = False
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or tr('common.empty')
        self.last_refreshed_label.setText(tr('data_center.last_refreshed', value=refreshed_at))
        try:
            self._apply_detail_to_widgets()
        except Exception as exc:
            self._LOGGER.exception('渲染演员详情失败: %s', self.actor_name)
            QMessageBox.critical(self, tr('common.operation_failed'), str(exc))
            return
        if self._startup_refresh_pending:
            self._startup_refresh_pending = False
            if bool(payload.get('cache_hit')):
                self.load_data(force_refresh=True, silent_errors=True, allow_deferred_close=True)

    def _next_detail_request_token(self):
        self._detail_request_sequence += 1
        return self._detail_request_sequence

    def _is_current_detail_response(self, payload):
        payload = dict(payload or {})
        request_token = payload.get('request_token')
        request_actor_name = str(payload.get('request_actor_name', '') or '').strip()
        if request_token is None and not request_actor_name:
            return True
        return (
            int(request_token or 0) == int(getattr(self, '_active_request_token', 0) or 0)
            and request_actor_name == str(self.actor_name or '').strip()
            and request_actor_name == str(getattr(self, '_active_request_actor_name', '') or '').strip()
        )

    def _handle_async_task_failed(self, message):
        if self._suppress_async_error_dialog:
            self._suppress_async_error_dialog = False
            return
        super()._handle_async_task_failed(message)

    def _apply_detail_to_widgets(self):
        self.basic_grid.set_value('name', self.detail.get('name', ''))
        self.basic_grid.set_value('actor_id', self.detail.get('actor_id', '') or tr('common.empty'))
        self.basic_grid.set_value('binghuo_person_id', self.detail.get('binghuo_person_id', '') or tr('common.empty'))
        self.basic_grid.set_value('ladder_tier', self.detail.get('ladder_tier', '') or tr('common.empty'))
        self.basic_grid.set_value(
            'update_status',
            tr(f"detail.update_status.{self.detail.get('update_status', 'inactive')}"),
        )
        self.basic_grid.set_value('age', self.detail.get('age', '') or tr('common.empty'))
        self.basic_grid.set_value('birthday', self.detail.get('birthday', '') or tr('common.empty'))
        self.basic_grid.set_value('binghuo_height', self._format_height(self.detail.get('binghuo_height', '')))
        self.basic_grid.set_value('local_total', str(self.detail.get('local_video_count', 0)))
        self.basic_grid.set_value('web_total', str(self.detail.get('web_total_videos', 0)))
        self.basic_grid.set_value('appearance_code_count', str(self.detail.get('appearance_code_count', 0)))
        self.basic_grid.set_value('code_prefix_library_count', str(self.detail.get('code_prefix_library_count', 0)))
        self.basic_grid.set_value('binghuo_cup', self.detail.get('binghuo_cup', '') or tr('common.empty'))
        self.basic_grid.set_value(
            'web_update_frequency',
            format_update_frequency_summary(self.detail.get('web_update_frequency', {})),
        )
        self.basic_measurements_grid.set_value(
            'measurements',
            self._format_measurements(
                self.detail.get('binghuo_bust', ''),
                self.detail.get('binghuo_waist', ''),
                self.detail.get('binghuo_hip', ''),
            ),
        )
        self.basic_status_grid.set_value(
            'web_status',
            self.detail.get('web_enrichment_status', '') or tr('actor.detail.web_status_default'),
        )

        self.local_grid.set_value(
            'local_prefix',
            format_distribution_summary(self.detail.get('local_prefix_distribution', []), 'prefix', items_per_line=10),
        )
        self.local_grid.set_value(
            'local_year',
            format_distribution_summary(self.detail.get('local_year_distribution', []), 'year', items_per_line=10),
        )

        self.web_grid.set_value('eligible_video_count', str(self.detail.get('eligible_video_count', 0)))
        self.web_grid.set_value('web_earliest', self.detail.get('web_earliest_release_date', '') or tr('common.empty'))
        self.web_grid.set_value('web_latest', self.detail.get('web_latest_release_date', '') or tr('common.empty'))
        self.web_grid.set_value(
            'eligible_enriched_video_count',
            str(self.detail.get('eligible_enriched_video_count', 0)),
        )
        self.web_last_enriched_grid.set_value(
            'web_last_enriched',
            self.detail.get('web_last_enriched_at', '') or tr('common.empty'),
        )
        self.web_prefix_grid.set_value(
            'web_prefix',
            format_distribution_summary(
                self.detail.get('web_prefix_distribution', []),
                'prefix',
                items_per_line=10,
                align_columns=True,
            ),
        )
        self.web_year_grid.set_value(
            'web_year',
            format_distribution_summary(self.detail.get('web_year_distribution', []), 'year', items_per_line=10),
        )
        self.web_video_category_grid.set_value(
            'web_video_categories',
            format_distribution_summary(
                self.detail.get('web_video_category_distribution', []),
                'name',
                items_per_line=4,
            ),
        )

        local_rows = list(self.detail.get('local_videos', []) or [])
        web_rows = list(self.detail.get('web_movies', []) or [])
        self.local_movie_count_label.setText(tr('actor.detail.local_movie_count', count=len(local_rows)))
        self.web_movie_count_label.setText(tr('actor.detail.web_movie_count', count=len(web_rows)))
        self.btn_local_movie_detail.setEnabled(bool(local_rows))
        self.btn_web_movie_detail.setEnabled(bool(web_rows))
        self.btn_open_web.setEnabled(bool(str(self.detail.get('web_url', '') or '').strip()))
        self._render_collaborator_sections()
        self._sync_tier_combo()
        self._refresh_navigation_buttons()

    def copy_actor_name(self):
        actor_name = str(self.detail.get('name', '') or self.actor_name).strip()
        if actor_name:
            QApplication.clipboard().setText(actor_name)

    def open_web_page(self):
        target_url = str(self.detail.get('web_url', '') or '').strip()
        if not target_url:
            QMessageBox.information(self, tr('common.no_data'), tr('detail.open_web_missing'))
            return
        if not QDesktopServices.openUrl(QUrl(target_url)):
            QMessageBox.warning(self, tr('common.operation_failed'), tr('detail.open_web_failed', url=target_url))

    def show_previous_item(self):
        self._jump_to_neighbor(-1)

    def show_next_item(self):
        self._jump_to_neighbor(1)

    def update_ladder_tier(self):
        selected_tier = str(self.tier_combo.currentData() or '').strip().upper()
        if not selected_tier:
            return
        try:
            self.backend_client.admit_ladder_entry(LADDER_BOARD_ACTOR, self.actor_name, selected_tier)
        except Exception as exc:
            QMessageBox.critical(self, tr('common.save_failed'), str(exc))
            return
        self.detail['ladder_tier'] = selected_tier
        self.basic_grid.set_value('ladder_tier', selected_tier)
        self._refresh_parent_after_tier_update()
        QMessageBox.information(
            self,
            tr('common.save_success'),
            tr('detail.update_tier_completed', tier=selected_tier),
        )

    def show_local_movie_detail(self):
        rows = list(self.detail.get('local_videos', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('actor.detail.local_movie_no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('actor.detail.local_movie_title', actor_name=self.actor_name),
            table_title=tr('actor.detail.local_movie_table_title', actor_name=self.actor_name),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def show_web_movie_detail(self):
        rows = list(self.detail.get('web_movies', []) or [])
        if not rows:
            QMessageBox.information(self, tr('common.no_data'), tr('actor.detail.web_movie_no_data'))
            return
        viewer = VideoListDetailWindow(
            title=tr('actor.detail.web_movie_title', actor_name=self.actor_name),
            table_title=tr('actor.detail.web_movie_table_title', actor_name=self.actor_name),
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def on_filter_rules_saved(self):
        if self.isVisible():
            self.load_data(force_refresh=True)

    def on_video_categories_updated(self):
        if self.isVisible():
            self.load_data(force_refresh=True)

    def _detail_host(self):
        if self.coordinator is not None:
            detail_host = self.coordinator.get_window(('list', EntityType.ACTOR))
            if detail_host is not None and hasattr(detail_host, 'neighbor_detail_key'):
                return detail_host
        detail_host = self.parent()
        if detail_host is None:
            return None
        if not hasattr(detail_host, 'neighbor_detail_key'):
            return None
        return detail_host

    def _refresh_navigation_buttons(self):
        detail_host = self._detail_host()
        if detail_host is None:
            self.btn_prev_item.setEnabled(False)
            self.btn_next_item.setEnabled(False)
            return
        self.btn_prev_item.setEnabled(bool(detail_host.neighbor_detail_key(self.actor_name, -1)))
        self.btn_next_item.setEnabled(bool(detail_host.neighbor_detail_key(self.actor_name, 1)))

    def _jump_to_neighbor(self, offset):
        detail_host = self._detail_host()
        if detail_host is None:
            self._refresh_navigation_buttons()
            return
        target_name = detail_host.neighbor_detail_key(self.actor_name, offset)
        if target_name:
            self._switch_actor(target_name)
            return
        self._refresh_navigation_buttons()

    def _switch_actor(self, actor_name):
        self.actor_name = str(actor_name or '').strip()
        self.detail = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self._deferred_silent_errors = False
        self._deferred_allow_deferred_close = False
        self._active_request_actor_name = self.actor_name
        self.setWindowTitle(tr('actor.detail.title', actor_name=self.actor_name))
        detail_host = self._detail_host()
        if detail_host is not None and hasattr(detail_host, 'select_actor_row'):
            detail_host.select_actor_row(self.actor_name)
        self.load_data()

    def _sync_tier_combo(self):
        current_tier = str((self.detail or {}).get('ladder_tier', '') or '').strip().upper()
        combo_index = self.tier_combo.findData(current_tier or LADDER_TIERS[0])
        self.tier_combo.setCurrentIndex(max(combo_index, 0))

    def _refresh_parent_after_tier_update(self):
        parent = self.parent()
        try:
            if hasattr(parent, 'load_board'):
                parent.load_board()
                return
            if hasattr(parent, 'load_data'):
                parent.load_data(force_refresh=True)
        except Exception as exc:
            QMessageBox.warning(self, tr('common.operation_failed'), str(exc))

    @staticmethod
    def _format_height(height_text):
        normalized = str(height_text or '').strip()
        if not normalized:
            return tr('common.empty')
        if normalized.lower().endswith('cm'):
            return normalized
        return f'{normalized} cm'

    def _render_collaborator_sections(self):
        while self.collaborator_layout.count():
            item = self.collaborator_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.collaborator_tables = {}
        self.collaborator_grids = {}
        self.collaborator_section_labels = {}
        sections = list(self.detail.get('collaborator_sections', []) or [])
        if not sections:
            self.collaborator_group.setVisible(False)
            return

        self.collaborator_group.setVisible(True)
        for section in sections:
            actor_name = str((section or {}).get('actor_name', '') or '').strip()
            ladder_tier = str((section or {}).get('ladder_tier', '') or '').strip().upper()
            section_widget = QWidget(self.collaborator_group)
            group_layout = QVBoxLayout(section_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            section_label = QLabel(f'{actor_name} ({ladder_tier})')
            section_label.setStyleSheet('font-weight: 600; padding-left: 4px;')
            group_layout.addWidget(section_label)
            self.collaborator_section_labels[actor_name] = section_label
            rows = list((section or {}).get('collaborators', []) or [])
            if not rows:
                empty_label = QLabel('暂无共演演员数据')
                empty_label.setStyleSheet('color: #777777;')
                group_layout.addWidget(empty_label)
            else:
                grid_container = QWidget(section_widget)
                grid_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                grid_layout = QGridLayout(grid_container)
                grid_layout.setContentsMargins(8, 6, 8, 6)
                grid_layout.setHorizontalSpacing(28)
                grid_layout.setVerticalSpacing(8)
                for column_index in range(self._COLLABORATOR_COLUMNS):
                    grid_layout.setColumnStretch(column_index, 1)
                for index, collaborator in enumerate(rows):
                    row_index = index // self._COLLABORATOR_COLUMNS
                    column_index = index % self._COLLABORATOR_COLUMNS
                    label = (
                        f'{str((collaborator or {}).get("actor_name", "") or "")} '
                        f'x{int((collaborator or {}).get("count", 0) or 0)}'
                    )
                    item_label = QLabel(label)
                    item_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    item_label.setMinimumWidth(92)
                    item_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                    item_label.setStyleSheet('padding: 3px 8px;')
                    grid_layout.addWidget(item_label, row_index, column_index)
                group_layout.addWidget(grid_container)
                self.collaborator_grids[actor_name] = grid_layout
                self.collaborator_tables[actor_name] = grid_layout
            self.collaborator_layout.addWidget(section_widget)

    @staticmethod
    def _format_measurements(bust_text, waist_text, hip_text):
        normalized_bust = str(bust_text or '').strip()
        normalized_waist = str(waist_text or '').strip()
        normalized_hip = str(hip_text or '').strip()
        if not any((normalized_bust, normalized_waist, normalized_hip)):
            return tr('common.empty')
        return (
            f'胸围: {ActorDetailViewerWindow._format_measurement_value(normalized_bust)} '
            f'腰围: {ActorDetailViewerWindow._format_measurement_value(normalized_waist)} '
            f'臀围: {ActorDetailViewerWindow._format_measurement_value(normalized_hip)}'
        )

    @staticmethod
    def _format_measurement_value(value):
        normalized = str(value or '').strip()
        if not normalized:
            return tr('common.empty')
        if normalized.lower().endswith('cm'):
            return normalized
        return f'{normalized} cm'
