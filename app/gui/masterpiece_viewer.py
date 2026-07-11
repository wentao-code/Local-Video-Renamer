from html import escape

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backend.client import BackendClient
from app.core.enrichment_status import ENRICHED_STATUS
from app.core.ladder_board import split_ladder_medals
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.deferred_reload_mixin import DeferredReloadMixin
from app.gui.detail_summary_widgets import DetailSummaryGrid
from app.gui.medal_catalog_viewer import MedalSelectionSidebar, build_medal_text


def _build_refresh_client(backend_client, minimum_timeout=90):
    base_url = str(getattr(backend_client, 'base_url', '') or '').strip()
    if not base_url:
        return backend_client
    return BackendClient(
        base_url=base_url,
        timeout=max(int(getattr(backend_client, 'timeout', 30) or 30), minimum_timeout),
    )


class MasterpieceWindow(QDialog, AsyncTaskHostMixin):
    _FULLY_ENRICHED_CODE_COLOR = QColor('#7b1fa2')
    _MEDAL_STYLES = {
        'border': '#b96a3b',
        'background': '#f6d8c3',
        'text': '#7a3513',
    }

    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.global_medals = []
        self.active_medal_code = ''
        self._init_async_task_host()
        self.setWindowTitle('名作堂')
        self.resize(1120, 640)
        self._init_ui()
        self.load_entries()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('视频番号'))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText('输入视频番号，例如 PFSA-001')
        self.code_input.returnPressed.connect(self.handle_add_entry)
        toolbar.addWidget(self.code_input, 1)

        self.btn_add = QPushButton('添加')
        self.btn_add.clicked.connect(self.handle_add_entry)
        toolbar.addWidget(self.btn_add)

        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_entries)
        toolbar.addWidget(self.btn_refresh)

        self.summary_label = QLabel('共 0 条')

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['番号', '标题', '演员', '勋章', '操作', '详情'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)

        left_layout.addLayout(toolbar)
        left_layout.addWidget(self.summary_label)
        left_layout.addWidget(self.table, 1)
        layout.addWidget(left_panel, 1)

        self.medal_sidebar = MedalSelectionSidebar(
            title='勋章侧栏',
            inactive_hint='点击左侧添加后即可选择或取消勋章。',
        )
        self.medal_sidebar.setFixedWidth(220)
        layout.addWidget(self.medal_sidebar)

        self.set_async_busy_widgets([self.code_input, self.btn_add, self.btn_refresh, self.table])

    def load_entries(self):
        self.start_async_task(
            self._build_entries_payload,
            self._on_entries_loaded,
            '读取名作堂失败',
        )

    def _build_entries_payload(self):
        return {
            'rows': self.backend_client.list_masterpiece_entries(),
            'global_medals': self.backend_client.list_global_medals(),
        }

    def handle_add_entry(self):
        code = str(self.code_input.text() or '').strip()
        if not code:
            QMessageBox.warning(self, '缺少番号', '请先输入要加入名作堂的视频番号。')
            return

        self.start_async_task(
            lambda: self._reload_entries_after(
                lambda: self.backend_client.add_masterpiece_entry(code),
                entry_code=str(code or '').strip().upper(),
            ),
            self._on_rows_reloaded_after_add,
            '添加名作堂失败',
        )

    def _reload_entries_after(self, operation, **payload):
        operation()
        return {
            **self._build_entries_payload(),
            **payload,
        }

    def _on_rows_reloaded_after_add(self, payload):
        payload = dict(payload or {})
        added_code = str(payload.get('entry_code', '') or '').strip()
        self.code_input.clear()
        self.code_input.setFocus()
        self._on_entries_loaded(payload)
        if added_code:
            self._begin_medal_edit(added_code, [])

    def _on_entries_loaded(self, payload):
        rows = payload
        medals = self.global_medals
        if isinstance(payload, dict):
            rows = payload.get('rows', payload.get('entries', []))
            medals = payload.get('global_medals', medals)
        self.rows = [dict(row or {}) for row in (rows or [])]
        self.global_medals = [dict(row or {}) for row in (medals or [])]
        self.active_medal_code = ''
        self.medal_sidebar.set_medals(self.global_medals)
        self.medal_sidebar.end_edit()
        self._render_rows()

    def _render_rows(self):
        self.table.setRowCount(0)
        for row_index, row in enumerate(self.rows):
            code = str((row or {}).get('code', '') or '').strip()
            title = str((row or {}).get('title', '') or '').strip()
            author = str((row or {}).get('author', '') or '').strip()
            medal_text = str((row or {}).get('medal', '') or '').strip()
            medals = list((row or {}).get('medals', []) or split_ladder_medals(medal_text))

            self.table.insertRow(row_index)
            code_item = QTableWidgetItem(code)
            if self._is_fully_enriched(row):
                code_item.setForeground(self._FULLY_ENRICHED_CODE_COLOR)
            self.table.setItem(row_index, 0, code_item)
            self.table.setItem(row_index, 1, QTableWidgetItem(title))
            self.table.setItem(row_index, 2, QTableWidgetItem(author))
            self.table.setCellWidget(row_index, 3, self._build_medal_widget(medals))
            self.table.setCellWidget(row_index, 4, self._build_medal_button(code))
            self.table.setCellWidget(row_index, 5, self._build_detail_button(code))

        self.summary_label.setText(f'共 {len(self.rows)} 条')
        self.table.setColumnWidth(0, 120)
        self.table.resizeRowsToContents()

    @staticmethod
    def _is_fully_enriched(row):
        row = dict(row or {})
        avfan_status = str(row.get('avfan_enrichment_status', '') or '').strip()
        javtxt_status = str(row.get('javtxt_enrichment_status', '') or '').strip()
        return avfan_status == ENRICHED_STATUS and javtxt_status == ENRICHED_STATUS

    def _build_medal_widget(self, medals):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setMargin(4)
        label.setText(self._build_medal_html(medals))
        return label

    def _build_medal_button(self, code):
        button = QPushButton('确认' if str(code or '').strip().upper() == self.active_medal_code else '添加')
        button.clicked.connect(lambda _checked=False, target_code=code: self.edit_medal(target_code))
        return button

    def _build_detail_button(self, code):
        button = QPushButton('详情')
        button.clicked.connect(lambda _checked=False, target_code=code: self.show_detail(target_code))
        return button

    def _build_medal_html(self, medals):
        if not medals:
            return '<span style="color:#888888;">暂无勋章</span>'

        palette = dict(self._MEDAL_STYLES)
        chips = []
        for medal in medals:
            chips.append(
                (
                    '<span style="display:inline-block; margin:0 6px 6px 0; '
                    f'padding:3px 10px; border:1px solid {palette["border"]}; border-radius:10px; '
                    f'background-color:{palette["background"]}; color:{palette["text"]};">'
                    f'{escape(str(medal or ""))}'
                    '</span>'
                )
            )
        return ''.join(chips)

    def edit_medal(self, code):
        normalized_code = str(code or '').strip().upper()
        row = self._find_row_by_code(normalized_code) or {}
        current_medals = list((row or {}).get('medals', []) or split_ladder_medals((row or {}).get('medal', '')))
        if self.active_medal_code != normalized_code:
            self._begin_medal_edit(normalized_code, current_medals)
            return

        merged_text = build_medal_text(new_medals=self.medal_sidebar.selected_medal_names())
        if merged_text == str((self._find_row_by_code(normalized_code) or {}).get('medal', '') or '').strip():
            self._cancel_medal_edit()
            return

        self.start_async_task(
            lambda: self._reload_entries_after(
                lambda: self.backend_client.update_masterpiece_entry_medal(normalized_code, merged_text),
            ),
            self._on_entries_loaded,
            '保存勋章失败',
        )

    def _begin_medal_edit(self, code, current_medals):
        self.active_medal_code = str(code or '').strip().upper()
        self.medal_sidebar.begin_edit(self.active_medal_code, current_medals)
        self._refresh_medal_buttons()

    def _cancel_medal_edit(self):
        self.active_medal_code = ''
        self.medal_sidebar.end_edit()
        self._refresh_medal_buttons()

    def _refresh_medal_buttons(self):
        for row_index, row in enumerate(self.rows):
            button = self.table.cellWidget(row_index, 4)
            if button is None:
                continue
            code = str((row or {}).get('code', '') or '').strip().upper()
            button.setText('确认' if code == self.active_medal_code else '添加')

    def _find_row_by_code(self, code):
        normalized_code = str(code or '').strip().upper()
        for row in self.rows:
            if str((row or {}).get('code', '') or '').strip().upper() == normalized_code:
                return row
        return None

    def show_detail(self, code):
        dialog = MasterpieceDetailWindow(self.backend_client, code, self)
        dialog.exec_()

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)


class MasterpieceDetailWindow(DeferredReloadMixin, AsyncTaskHostMixin, QDialog):
    _SOURCE_TITLES = {
        'video_library': '视频库参考',
        'actor_library': '演员库参考',
        'code_prefix_library': '番号库参考',
    }
    _SOURCE_ORDER = ('video_library', 'actor_library', 'code_prefix_library')
    _ACTOR_HEADERS = ['演员', '生日', '年龄', '出演年龄', '身高', '三围', '罩杯']

    def __init__(self, backend_client, code, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.refresh_client = _build_refresh_client(backend_client)
        self.code = str(code or '').strip().upper()
        self.detail = {}
        self.collaborator_tables = {}
        self._startup_refresh_pending = True
        self._deferred_force_refresh = False
        self._deferred_silent_errors = False
        self._deferred_allow_deferred_close = False
        self._suppress_async_error_dialog = False
        self._init_async_task_host()
        self._init_deferred_reload(self._perform_deferred_load)
        self.setWindowTitle(f'名作堂详情 - {self.code}')
        self.resize(980, 760)
        self._init_ui()
        self.load_detail()

    def _init_ui(self):
        self.root_layout = QVBoxLayout(self)
        root_layout = self.root_layout

        top_bar = QHBoxLayout()
        self.btn_open_primary = QPushButton('打开主链接')
        self.btn_open_primary.clicked.connect(self.open_primary_link)
        top_bar.addWidget(self.btn_open_primary)
        self.btn_enrich = QPushButton('补全')
        self.btn_enrich.clicked.connect(self.handle_enrich)
        top_bar.addWidget(self.btn_enrich)
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(lambda: self.load_detail(force_refresh=True))
        top_bar.addWidget(self.btn_refresh)
        self.last_refreshed_label = QLabel('上次刷新: 暂无')
        top_bar.addWidget(self.last_refreshed_label)
        top_bar.addStretch()
        root_layout.addLayout(top_bar)

        self.detail_scroll_area = QScrollArea()
        self.detail_scroll_area.setWidgetResizable(True)
        root_layout.addWidget(self.detail_scroll_area, 1)

        self.detail_scroll_widget = QWidget()
        self.detail_scroll_layout = QVBoxLayout(self.detail_scroll_widget)
        self.detail_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_scroll_layout.setSpacing(12)
        self.detail_scroll_area.setWidget(self.detail_scroll_widget)

        self.first_source_group = QGroupBox('第一套系统')
        first_source_layout = QVBoxLayout(self.first_source_group)
        self.first_source_label = QLabel('暂无')
        self.first_source_label.setWordWrap(True)
        first_source_layout.addWidget(self.first_source_label)
        self.detail_scroll_layout.addWidget(self.first_source_group)

        self.second_source_group = QGroupBox('第二套系统')
        second_source_layout = QVBoxLayout(self.second_source_group)
        self.second_source_label = QLabel('暂无')
        self.second_source_label.setWordWrap(True)
        second_source_layout.addWidget(self.second_source_label)
        self.detail_scroll_layout.addWidget(self.second_source_group)

        self.duration_label = QLabel('片长: 暂无')
        self.duration_label.setWordWrap(True)
        self.duration_label.setVisible(False)
        self.detail_scroll_layout.addWidget(self.duration_label)
        self.description_label = QLabel('剧情描述: 暂无')
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(False)
        self.detail_scroll_layout.addWidget(self.description_label)

        self.actor_details_group = QGroupBox('演员基础信息')
        self.actor_details_layout = QVBoxLayout(self.actor_details_group)
        self.actor_details_label = QLabel('暂无')
        self.actor_details_label.setWordWrap(True)
        self.actor_detail_grids = {}
        self.actor_detail_buttons = {}
        self.detail_scroll_layout.addWidget(self.actor_details_group)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.detail_scroll_layout.addWidget(self.content_widget)
        self.set_async_busy_widgets([self.btn_open_primary, self.btn_enrich, self.btn_refresh])

    def load_detail(self, force_refresh=False, silent_errors=False, allow_deferred_close=False):
        if self.is_async_task_running():
            self._deferred_force_refresh = self._deferred_force_refresh or bool(force_refresh)
            self._deferred_silent_errors = self._deferred_silent_errors or bool(silent_errors)
            self._deferred_allow_deferred_close = (
                self._deferred_allow_deferred_close or bool(allow_deferred_close)
            )
            self.schedule_deferred_reload(0)
            return
        self._suppress_async_error_dialog = bool(silent_errors)
        self.start_async_task(
            lambda: self._load_detail_payload(force_refresh=force_refresh),
            self._on_detail_loaded,
            '读取名作堂详情失败',
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
        self.load_detail(
            force_refresh=force_refresh,
            silent_errors=silent_errors,
            allow_deferred_close=allow_deferred_close,
        )

    def _load_detail_payload(self, force_refresh=False):
        if hasattr(self.refresh_client, 'get_masterpiece_detail_snapshot'):
            return self.refresh_client.get_masterpiece_detail_snapshot(self.code, force_refresh=force_refresh)
        detail = self.backend_client.get_masterpiece_detail(self.code)
        return {
            'detail': dict(detail or {}),
            'refreshed_at': '',
            'cache_hit': False,
        }

    def handle_enrich(self):
        self.start_async_task(
            lambda: self.refresh_client.enrich_masterpiece_detail(self.code),
            self._on_detail_loaded,
            '补全名作堂详情失败',
            block_ui=True,
        )

    def _on_detail_loaded(self, result):
        payload = dict(result or {})
        self.detail = dict(payload.get('detail', payload or {}) or {})
        self._suppress_async_error_dialog = False
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or '暂无'
        self.last_refreshed_label.setText(f'上次刷新: {refreshed_at}')
        self.btn_open_primary.setEnabled(bool(str(self.detail.get('primary_detail_url', '') or '').strip()))
        self.duration_label.setText(f'片长: {self.detail.get("first_source_duration", "") or "暂无"}')
        self.description_label.setText(
            f'剧情描述: {self.detail.get("second_source_description", "") or "暂无"}'
        )
        self._render_source_columns()
        self._render_actor_details()
        self._render_detail_sections()
        if self._startup_refresh_pending:
            self._startup_refresh_pending = False
            if bool(payload.get('cache_hit')):
                self.load_detail(force_refresh=True, silent_errors=True, allow_deferred_close=True)

    def _handle_async_task_failed(self, message):
        if self._suppress_async_error_dialog:
            self._suppress_async_error_dialog = False
            return
        super()._handle_async_task_failed(message)

    def _render_source_columns(self):
        self.first_source_label.setText(
            '\n'.join(
                [
                    f'视频标题: {self.detail.get("first_source_title", "") or self.detail.get("display_title", "") or "暂无"}',
                    f'片长: {self.detail.get("first_source_duration", "") or "暂无"}',
                    f'标签: {self.detail.get("first_source_tags", "") or self.detail.get("display_tags", "") or "暂无"}',
                    f'演员: {self.detail.get("first_source_actors", "") or self.detail.get("display_author", "") or "暂无"}',
                ]
            )
        )
        self.second_source_label.setText(
            '\n'.join(
                [
                    f'视频标题: {self.detail.get("second_source_title", "") or "暂无"}',
                    f'出演女优: {self.detail.get("second_source_actors", "") or "暂无"}',
                    f'类别: {self.detail.get("second_source_tags", "") or self.detail.get("display_tags", "") or "暂无"}',
                    f'剧情介绍: {self.detail.get("second_source_description", "") or "暂无"}',
                ]
            )
        )

    def _render_actor_details(self):
        self._clear_actor_details_layout()
        self.actor_detail_grids = {}
        self.actor_detail_buttons = {}
        actor_rows = list(self.detail.get('actor_details', []) or [])
        blocks = []
        for actor in actor_rows:
            actor_name = str((actor or {}).get('actor_name', '') or '').strip()
            if not actor_name:
                continue
            values = self._actor_basic_display_values(actor, actor_name)
            blocks.append(' | '.join(values))
            self._add_actor_detail_grid(actor, actor_name)
        summary_text = '\n\n'.join(blocks) if blocks else '暂无'
        self.actor_details_label.setText(summary_text)
        if not blocks:
            empty_label = QLabel('暂无')
            empty_label.setStyleSheet('color: #777777;')
            self.actor_details_layout.addWidget(empty_label)

    def _add_actor_detail_grid(self, actor, actor_name):
        card = QGroupBox(actor_name)
        card_layout = QVBoxLayout(card)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(QLabel(actor_name))
        detail_button = QPushButton('详情')
        detail_button.setMinimumWidth(72)
        detail_button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))
        header_layout.addWidget(detail_button)
        header_layout.addStretch()
        card_layout.addLayout(header_layout)

        basic_grid = DetailSummaryGrid(columns=4)
        basic_grid.set_items(
            [
                ('name', '姓名:', actor_name),
                ('actor_id', '天限阁ID:', str((actor or {}).get('actor_id', '') or '暂无')),
                ('binghuo_person_id', '并火 ID:', str((actor or {}).get('binghuo_person_id', '') or '暂无')),
                ('ladder_tier', '演员等级:', str((actor or {}).get('ladder_tier', '') or '暂无')),
                (
                    'update_status',
                    '更新状态:',
                    str(
                        (actor or {}).get('update_status_text', '')
                        or self._update_status_text((actor or {}).get('update_status', ''))
                        or '暂无'
                    ),
                ),
                ('current_age', '年龄:', str((actor or {}).get('current_age', '') or '暂无')),
                ('birthday', '生日:', str((actor or {}).get('birthday', '') or '暂无')),
                ('height', '身高:', str((actor or {}).get('height', '') or '暂无')),
                ('local_video_count', '本地视频总数:', self._display_count((actor or {}).get('local_video_count', ''))),
                ('web_total_videos', '网页作品总数:', self._display_count((actor or {}).get('web_total_videos', ''))),
                (
                    'appearance_code_count',
                    '出演番号数量:',
                    self._display_count((actor or {}).get('appearance_code_count', '')),
                ),
                (
                    'code_prefix_library_count',
                    '番号库中数量:',
                    self._display_count((actor or {}).get('code_prefix_library_count', '')),
                ),
                ('cup', '罩杯:', str((actor or {}).get('cup', '') or '暂无')),
                (
                    'web_update_frequency',
                    '更新频率:',
                    str(
                        (actor or {}).get('web_update_frequency_text', '')
                        or self._format_update_frequency((actor or {}).get('web_update_frequency', {}))
                        or '暂无'
                    ),
                ),
            ]
        )
        card_layout.addWidget(basic_grid)

        measurements_grid = DetailSummaryGrid(columns=1)
        measurements_grid.set_items(
            [
                ('measurements', '三围:', self._build_measurements_text(actor) or '暂无'),
            ]
        )
        card_layout.addWidget(measurements_grid)

        status_grid = DetailSummaryGrid(columns=1)
        status_grid.set_items(
            [
                ('web_enrichment_status', '补全状态:', str((actor or {}).get('web_enrichment_status', '') or '暂无')),
                ('appearance_age', '出演年龄:', str((actor or {}).get('appearance_age', '') or '暂无')),
            ]
        )
        card_layout.addWidget(status_grid)

        self.actor_details_layout.addWidget(card)
        self.actor_detail_grids[actor_name] = {
            'basic': basic_grid,
            'measurements': measurements_grid,
            'status': status_grid,
        }
        self.actor_detail_buttons[actor_name] = detail_button

    def show_actor_detail(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return
        viewer = ActorDetailViewerWindow(self.backend_client, normalized_name, self)
        viewer.exec_()

    def _actor_basic_display_values(self, actor, actor_name):
        return [
            f'姓名: {actor_name}',
            f'天限阁ID: {str((actor or {}).get("actor_id", "") or "暂无")}',
            f'并火 ID: {str((actor or {}).get("binghuo_person_id", "") or "暂无")}',
            f'演员等级: {str((actor or {}).get("ladder_tier", "") or "暂无")}',
            f'更新状态: {str((actor or {}).get("update_status_text", "") or self._update_status_text((actor or {}).get("update_status", "")) or "暂无")}',
            f'年龄: {str((actor or {}).get("current_age", "") or "暂无")}',
            f'生日: {str((actor or {}).get("birthday", "") or "暂无")}',
            f'身高: {str((actor or {}).get("height", "") or "暂无")}',
            f'本地视频总数: {self._display_count((actor or {}).get("local_video_count", ""))}',
            f'网页作品总数: {self._display_count((actor or {}).get("web_total_videos", ""))}',
            f'出演番号数量: {self._display_count((actor or {}).get("appearance_code_count", ""))}',
            f'番号库中数量: {self._display_count((actor or {}).get("code_prefix_library_count", ""))}',
            f'三围: {self._build_measurements_text(actor) or "暂无"}',
            f'罩杯: {str((actor or {}).get("cup", "") or "暂无")}',
            f'更新频率: {str((actor or {}).get("web_update_frequency_text", "") or self._format_update_frequency((actor or {}).get("web_update_frequency", {})) or "暂无")}',
            f'补全状态: {str((actor or {}).get("web_enrichment_status", "") or "暂无")}',
            f'出演年龄: {str((actor or {}).get("appearance_age", "") or "暂无")}',
        ]

    def _clear_actor_details_layout(self):
        while self.actor_details_layout.count():
            item = self.actor_details_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    @staticmethod
    def _build_measurements_text(actor):
        bust = str((actor or {}).get('bust', '') or '').strip()
        waist = str((actor or {}).get('waist', '') or '').strip()
        hip = str((actor or {}).get('hip', '') or '').strip()
        if bust and waist and hip:
            return f'{bust}/{waist}/{hip}'
        return str((actor or {}).get('measurements_raw', '') or '').strip()

    @staticmethod
    def _update_status_text(update_status):
        return {
            'active': '正在更新',
            'suspect': '疑似更新',
            'inactive': '断更',
        }.get(str(update_status or '').strip(), '')

    @staticmethod
    def _format_update_frequency(stats):
        rate = dict(stats or {}).get('videos_per_month')
        if rate is None:
            return ''
        return f'{float(rate):.2f} 部/月'

    @staticmethod
    def _display_count(value):
        if value == '' or value is None:
            return '暂无'
        return str(value)

    def _render_detail_sections(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.collaborator_tables = {}
        self._render_collaborator_sections()
        self.content_layout.addStretch()

    def _reference_links_by_source(self):
        links = {}
        for reference in list(self.detail.get('references', []) or []):
            source = str((reference or {}).get('reference_source', '') or '').strip()
            detail_url = str((reference or {}).get('detail_url', '') or '').strip()
            if source and detail_url and source not in links:
                links[source] = detail_url
        return links

    def open_source_reference_link(self, source_name):
        source = str(source_name or '').strip()
        self.open_reference_link(self._reference_links_by_source().get(source, ''))

    def _render_collaborator_sections(self):
        sections = list(self.detail.get('collaborator_sections', []) or [])
        for section in sections:
            actor_name = str((section or {}).get('actor_name', '') or '').strip()
            ladder_tier = str((section or {}).get('ladder_tier', '') or '').strip().upper()
            group_box = QGroupBox(f'{actor_name} ({ladder_tier})')
            group_layout = QVBoxLayout(group_box)
            rows = list((section or {}).get('collaborators', []) or [])
            if not rows:
                empty_label = QLabel('暂无合作演员数据')
                empty_label.setStyleSheet('color: #777777;')
                group_layout.addWidget(empty_label)
            else:
                table = QTableWidget()
                table.setColumnCount(6)
                table.setEditTriggers(QTableWidget.NoEditTriggers)
                table.setSelectionMode(QAbstractItemView.NoSelection)
                table.verticalHeader().setVisible(False)
                table.horizontalHeader().setVisible(False)
                table.setShowGrid(False)
                row_count = (len(rows) + 5) // 6
                table.setRowCount(row_count)
                for index, collaborator in enumerate(rows):
                    row_index = index // 6
                    column_index = index % 6
                    label = (
                        f'{str((collaborator or {}).get("actor_name", "") or "")} '
                        f'x{int((collaborator or {}).get("count", 0) or 0)}'
                    )
                    item = QTableWidgetItem(label)
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    table.setItem(row_index, column_index, item)
                table.resizeColumnsToContents()
                table.resizeRowsToContents()
                group_layout.addWidget(table)
                self.collaborator_tables[actor_name] = table
            self.content_layout.addWidget(group_box)

    def _render_reference_groups(self):
        references = list(self.detail.get('references', []) or [])
        grouped = {source: [] for source in self._SOURCE_ORDER}
        for reference in references:
            source = str((reference or {}).get('reference_source', '') or '').strip()
            grouped.setdefault(source, []).append(dict(reference or {}))

        for source in self._SOURCE_ORDER:
            group_box = QGroupBox(self._source_title(source))
            group_layout = QVBoxLayout(group_box)
            rows = grouped.get(source, [])
            if not rows:
                empty_label = QLabel('暂无参考')
                empty_label.setStyleSheet('color: #777777;')
                group_layout.addWidget(empty_label)
            else:
                for reference in rows:
                    group_layout.addWidget(self._build_reference_card(reference))
            self.content_layout.addWidget(group_box)

        self.content_layout.addStretch()

    def _build_reference_card(self, reference):
        card = QGroupBox()
        layout = QGridLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        key_text = str((reference or {}).get('reference_key', '') or '').strip() or '暂无'
        title_text = str((reference or {}).get('title', '') or '').strip() or '暂无'
        author_text = str((reference or {}).get('author', '') or '').strip() or '暂无'
        release_text = str((reference or {}).get('release_date', '') or '').strip() or '暂无'

        layout.addWidget(QLabel(f'来源键: {key_text}'), 0, 0)
        layout.addWidget(QLabel(f'标题: {title_text}'), 0, 1)
        layout.addWidget(QLabel(f'演员: {author_text}'), 1, 0)
        layout.addWidget(QLabel(f'日期: {release_text}'), 1, 1)

        detail_url = str((reference or {}).get('detail_url', '') or '').strip()
        button = QPushButton('详情')
        button.setEnabled(bool(detail_url))
        button.clicked.connect(lambda _checked=False, url=detail_url: self.open_reference_link(url))
        layout.addWidget(button, 0, 2, 2, 1)
        return card

    def open_primary_link(self):
        self.open_reference_link(str(self.detail.get('primary_detail_url', '') or '').strip())

    def open_reference_link(self, target_url):
        normalized_url = str(target_url or '').strip()
        if not normalized_url:
            QMessageBox.information(self, '暂无链接', '当前参考没有可打开的详情链接。')
            return
        if not QDesktopServices.openUrl(QUrl(normalized_url)):
            QMessageBox.warning(self, '打开失败', f'无法打开链接: {normalized_url}')

    def _source_title(self, source_name):
        normalized_source = str(source_name or '').strip()
        return self._SOURCE_TITLES.get(normalized_source, normalized_source or '参考')
