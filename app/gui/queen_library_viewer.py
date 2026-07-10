from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
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

from app.core.queen_library_domain import (
    QUEEN_PROFILE_FIELD_OPTIONS,
    QUEEN_VIDEO_CONTENT_LEVELS,
    QUEEN_VIDEO_CONTENT_TYPES,
    normalize_queen_profile_value,
    normalize_queen_video_content_level,
    normalize_queen_video_content_type,
)
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr
from app.gui.queen_library_sorting import sort_queen_rows


BUTTONS_PER_ROW = 9
KEYWORDS_PER_ROW = 6
QUEEN_PROFILE_LIKE_LEVEL_STYLES = {
    'A': {'background': '#E74C3C', 'foreground': '#FFFFFF', 'border': '#C0392B'},
    'B': {'background': '#F39C12', 'foreground': '#FFFFFF', 'border': '#D68910'},
    'C': {'background': '#BDC3C7', 'foreground': '#1F2933', 'border': '#A6ACAF'},
    'D': {'background': '#95A5A6', 'foreground': '#1F2933', 'border': '#7F8C8D'},
}


def _tr_joined_preview(values, limit=10):
    rows = [str(value or '').strip() for value in values or [] if str(value or '').strip()]
    preview = '\n'.join(rows[:limit])
    if len(rows) > limit:
        preview += tr('queen.keyword.delete_more_suffix', count=len(rows))
    return preview


def _combo_value(combo):
    data = combo.currentData()
    return str(data if data is not None else combo.currentText() or '').strip()


def _set_combo_value(combo, value):
    normalized = str(value or '').strip()
    index = combo.findData(normalized)
    if index < 0:
        index = combo.findText(normalized)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _add_empty_and_options(combo, options, label_key_prefix):
    combo.addItem('', '')
    for option in options:
        combo.addItem(tr(f'{label_key_prefix}.{option}'), option)


def _profile_label(field_key):
    return tr(f'queen.profile.field.{field_key}')


def _translated_backend_message(payload, fallback_key=''):
    data = dict(payload or {})
    message_key = str(data.get('message_key', '') or '').strip()
    if message_key:
        return tr(message_key, **dict(data.get('message_args', {}) or {}))
    message = str(data.get('message', '') or '').strip()
    if message.startswith('queen.'):
        return tr(message)
    return message or (tr(fallback_key) if fallback_key else '')


class KeywordLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.keywords = []
        self._keyword_buttons = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('queen.keyword_library.title'))
        self.resize(980, 520)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.info_label = QLabel(tr('queen.keyword.saved'))
        self.btn_delete_selected = QPushButton(tr('queen.keyword.delete_selected'))
        self.btn_delete_selected.clicked.connect(self.delete_selected_keywords)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.info_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_delete_selected)
        top_layout.addWidget(self.btn_refresh)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setHorizontalSpacing(10)
        self.grid_layout.setVerticalSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.scroll_widget)

        layout.addLayout(top_layout)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_delete_selected, self.btn_refresh])

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.list_queen_keywords_snapshot(force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.keywords = list(payload.get('keywords', []) or [])
        self.info_label.setText(tr('queen.keyword.saved_count', count=len(self.keywords)))
        self._render_keyword_buttons()

    def _render_keyword_buttons(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._keyword_buttons.clear()
        for index, row in enumerate(self.keywords):
            keyword = str((row or {}).get('keyword', '') or '').strip()
            button = QPushButton(keyword)
            button.setCheckable(True)
            button.setMinimumWidth(140)
            button.setStyleSheet(
                'QPushButton { text-align: center; padding: 8px 10px; }'
                'QPushButton:checked { background-color: #0078d4; color: white; }'
            )
            self._keyword_buttons.append(button)
            self.grid_layout.addWidget(button, index // KEYWORDS_PER_ROW, index % KEYWORDS_PER_ROW)

    def delete_selected_keywords(self):
        selected = [btn for btn in self._keyword_buttons if btn.isChecked()]
        if not selected:
            QMessageBox.information(self, tr('common.prompt'), tr('queen.keyword.select_delete_first'))
            return
        names = [btn.text() for btn in selected]
        answer = QMessageBox.question(
            self,
            tr('queen.common.confirm_delete'),
            tr(
                'queen.keyword.delete_confirm',
                count=len(names),
                preview=_tr_joined_preview(names),
            ),
        )
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self._delete_keywords(names),
            self._on_delete_finished,
            tr('queen.keyword.delete_failed'),
        )

    def _delete_keywords(self, names):
        deleted = 0
        for name in names:
            count = self.backend_client.delete_queen_keyword(name)
            deleted += int(count or 0)
        return {'deleted': deleted}

    def _on_delete_finished(self, result):
        payload = dict(result or {})
        deleted = int(payload.get('deleted', 0) or 0)
        self.info_label.setText(tr('queen.keyword.deleted_refreshing', count=deleted))
        self.load_data(force_refresh=True)


class QueenDetailWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, queen_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.queen_name = str(queen_name or '').strip()
        self.rows = []
        self.profile = {}
        self.profile_fields = {}
        self.video_metadata_fields = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('queen.detail.title', queen_name=self.queen_name))
        self.resize(1040, 620)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.queen_name_input = QLineEdit(self.queen_name)
        self.queen_name_input.setFixedWidth(220)
        self.info_label = QLabel('')
        self.btn_edit_queen_name = QPushButton(tr('queen.detail.edit_name'))
        self.btn_edit_queen_name.clicked.connect(self.start_edit_queen_name)
        self.btn_save_queen_name = QPushButton(tr('queen.detail.save_name'))
        self.btn_save_queen_name.clicked.connect(self.save_queen_name)
        self.btn_cancel_queen_name = QPushButton(tr('common.cancel'))
        self.btn_cancel_queen_name.clicked.connect(self.cancel_edit_queen_name)
        self.btn_delete_queen = QPushButton(tr('queen.detail.delete_queen'))
        self.btn_delete_queen.clicked.connect(self.delete_queen)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.queen_name_input)
        top_layout.addWidget(QLabel('|'))
        top_layout.addWidget(self.info_label)
        top_layout.addWidget(self.btn_save_queen_name)
        top_layout.addWidget(self.btn_cancel_queen_name)
        top_layout.addWidget(self.btn_edit_queen_name)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_delete_queen)
        top_layout.addWidget(self.btn_refresh)

        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel(tr('queen.profile.basic')))
        for field_key, options in QUEEN_PROFILE_FIELD_OPTIONS.items():
            profile_layout.addWidget(QLabel(_profile_label(field_key)))
            combo = QComboBox()
            _add_empty_and_options(combo, options, f'queen.profile.{field_key}')
            combo.setFixedWidth(86)
            self.profile_fields[field_key] = combo
            profile_layout.addWidget(combo)
        self.btn_confirm_profile = QPushButton(tr('queen.profile.confirm'))
        self.btn_confirm_profile.clicked.connect(self.confirm_profile)
        self.btn_modify_profile = QPushButton(tr('queen.profile.modify'))
        self.btn_modify_profile.clicked.connect(self.modify_profile)
        profile_layout.addWidget(self.btn_confirm_profile)
        profile_layout.addWidget(self.btn_modify_profile)
        profile_layout.addStretch()

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(tr('queen.detail.headers'))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, self.table.horizontalHeader().ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addLayout(top_layout)
        layout.addLayout(profile_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [
                self.queen_name_input,
                self.btn_edit_queen_name,
                self.btn_save_queen_name,
                self.btn_cancel_queen_name,
                self.btn_delete_queen,
                self.btn_refresh,
                self.table,
            ]
        )
        self._set_queen_name_editable(False)

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.get_queen_detail_snapshot(self.queen_name, force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.queen_name = str(payload.get('queen_name', self.queen_name) or '').strip()
        self.rows = list(payload.get('videos', []) or [])
        self.profile = dict(payload.get('profile', {}) or {})
        self.setWindowTitle(tr('queen.detail.title', queen_name=self.queen_name))
        self.queen_name_input.setText(self.queen_name)
        self._set_queen_name_editable(False)
        self.info_label.setText(tr('queen.detail.video_count', queen_name=self.queen_name, count=len(self.rows)))
        self._apply_profile_to_fields(self.profile)
        self._render_rows()

    def _set_queen_name_editable(self, editable):
        editable = bool(editable)
        self.queen_name_input.setReadOnly(not editable)
        self.btn_edit_queen_name.setEnabled(not editable)
        self.btn_save_queen_name.setEnabled(editable)
        self.btn_cancel_queen_name.setEnabled(editable)
        if editable:
            self.queen_name_input.setFocus()
            self.queen_name_input.selectAll()

    def start_edit_queen_name(self):
        self._set_queen_name_editable(True)

    def cancel_edit_queen_name(self):
        self.queen_name_input.setText(self.queen_name)
        self._set_queen_name_editable(False)

    def save_queen_name(self):
        new_name = self.queen_name_input.text().strip()
        if not new_name:
            QMessageBox.information(self, tr('common.prompt'), tr('queen.detail.name_required'))
            return
        self.start_async_task(
            lambda: self.backend_client.rename_queen(
                self.queen_name,
                new_name,
                self._collect_profile_payload(),
            ),
            self._on_queen_renamed,
            tr('queen.detail.save_name_failed'),
        )

    def _on_queen_renamed(self, result):
        self._on_load_data_finished(result)

    def _apply_profile_to_fields(self, profile):
        payload = dict(profile or {})
        for field_key, combo in self.profile_fields.items():
            value = normalize_queen_profile_value(field_key, payload.get(field_key, ''))
            _set_combo_value(combo, value)
        self._set_profile_editable(not bool(payload.get('profile_confirmed')))

    def _set_profile_editable(self, editable):
        editable = bool(editable)
        for combo in self.profile_fields.values():
            combo.setEnabled(editable)
        self.btn_confirm_profile.setEnabled(editable)
        self.btn_modify_profile.setEnabled(not editable)

    def _collect_profile_payload(self):
        return {field_key: _combo_value(combo) for field_key, combo in self.profile_fields.items()}

    def confirm_profile(self):
        profile = self._collect_profile_payload()
        missing_labels = [
            _profile_label(field_key)
            for field_key in QUEEN_PROFILE_FIELD_OPTIONS
            if not profile.get(field_key)
        ]
        if missing_labels:
            QMessageBox.information(
                self,
                tr('common.prompt'),
                tr('queen.profile.select_required', fields=tr('queen.common.list_separator').join(missing_labels)),
            )
            return
        self.start_async_task(
            lambda: self.backend_client.update_queen_profile(self.queen_name, profile),
            self._on_profile_saved,
            tr('queen.profile.save_failed'),
        )

    def _on_profile_saved(self, result):
        payload = dict(result or {})
        self.profile = dict(payload.get('profile', {}) or {})
        self._apply_profile_to_fields(self.profile)

    def modify_profile(self):
        self._set_profile_editable(True)

    def _render_rows(self):
        self.table.setRowCount(0)
        self.video_metadata_fields.clear()
        for row_index, row_data in enumerate(self.rows):
            self.table.insertRow(row_index)
            for column_index, value in enumerate((row_data.get('video_title', ''), row_data.get('raw_title', ''))):
                item = QTableWidgetItem(str(value or ''))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)
            record_id = int(row_data.get('id', 0) or 0)
            content_combo = self._build_content_type_combo(row_data.get('content_type', ''))
            level_combo = self._build_level_combo(row_data.get('content_level', ''))
            self.video_metadata_fields[record_id] = {
                'content_type': content_combo,
                'content_level': level_combo,
            }
            content_combo.currentIndexChanged.connect(lambda _index, value=record_id: self.save_video_metadata(value))
            level_combo.currentIndexChanged.connect(lambda _index, value=record_id: self.save_video_metadata(value))
            self.table.setCellWidget(row_index, 2, content_combo)
            self.table.setCellWidget(row_index, 3, level_combo)
            self.table.setCellWidget(row_index, 4, self._build_delete_button(record_id))
            self.table.setCellWidget(row_index, 5, self._build_detail_indicator(row_data.get('detail_url', '')))

    def _build_content_type_combo(self, current_value):
        combo = QComboBox()
        _add_empty_and_options(combo, QUEEN_VIDEO_CONTENT_TYPES, 'queen.video.content_type')
        _set_combo_value(combo, normalize_queen_video_content_type(current_value))
        combo.setFixedWidth(86)
        return combo

    def _build_level_combo(self, current_value):
        combo = QComboBox()
        _add_empty_and_options(combo, QUEEN_VIDEO_CONTENT_LEVELS, 'queen.video.content_level')
        _set_combo_value(combo, normalize_queen_video_content_level(current_value))
        combo.setFixedWidth(86)
        return combo

    def save_video_metadata(self, record_id):
        fields = self.video_metadata_fields.get(int(record_id or 0))
        if not fields:
            return
        content_type = _combo_value(fields['content_type'])
        content_level = _combo_value(fields['content_level'])
        self.start_async_task(
            lambda: self.backend_client.update_queen_video_metadata(record_id, content_type, content_level),
            self._on_video_metadata_saved,
            tr('common.operation_failed'),
        )

    def _on_video_metadata_saved(self, result):
        payload = dict(result or {})
        video = dict(payload.get('video', payload) or {})
        record_id = int(video.get('id', 0) or 0)
        for row in self.rows:
            if int((row or {}).get('id', 0) or 0) == record_id:
                row.update({
                    'content_type': normalize_queen_video_content_type(video.get('content_type', '')),
                    'content_level': normalize_queen_video_content_level(video.get('content_level', '')),
                })
                break

    def _build_delete_button(self, record_id):
        button = QPushButton(tr('path.viewer.delete'))
        button.clicked.connect(lambda _checked=False, value=record_id: self.delete_video(value))
        return button

    @staticmethod
    def _build_detail_indicator(detail_url):
        label = QLabel()
        label.setFixedSize(16, 16)
        has_url = bool(str(detail_url or '').strip())
        color = '#f0c040' if has_url else '#d04040'
        label.setStyleSheet(
            f'QLabel {{ background-color: {color}; border-radius: 8px; border: 1px solid #666; }}'
        )
        label.setToolTip(tr('queen.detail.link_ready') if has_url else tr('queen.detail.link_missing'))
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(label)
        return container

    def delete_video(self, record_id):
        answer = QMessageBox.question(
            self,
            tr('queen.common.confirm_delete'),
            tr('queen.detail.delete_video_confirm'),
        )
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.delete_queen_video(record_id)),
            self._on_load_data_finished,
            tr('common.operation_failed'),
        )

    def delete_queen(self):
        answer = QMessageBox.question(
            self,
            tr('queen.common.confirm_delete'),
            tr('queen.detail.delete_queen_confirm', queen_name=self.queen_name),
        )
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self.backend_client.delete_queen(self.queen_name),
            self._on_delete_queen_finished,
            tr('common.operation_failed'),
        )

    def _reload_after(self, operation):
        operation()
        return self.backend_client.get_queen_detail_snapshot(self.queen_name, force_refresh=True)

    def _on_delete_queen_finished(self, _result):
        self.accept()


class QueenLibraryDataCenterWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('queen.data_center.title'))
        self.resize(640, 460)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        summary_layout = QHBoxLayout()
        summary_layout.addWidget(QLabel(tr('queen.data_center.queen_count')))
        self.queen_count_value = QLabel('0')
        summary_layout.addWidget(self.queen_count_value)
        summary_layout.addSpacing(24)
        summary_layout.addWidget(QLabel(tr('queen.data_center.video_count')))
        self.video_count_value = QLabel('0')
        summary_layout.addWidget(self.video_count_value)
        summary_layout.addStretch()
        self.btn_refresh_stats = QPushButton(tr('common.refresh'))
        self.btn_refresh_stats.clicked.connect(self.load_data)
        summary_layout.addWidget(self.btn_refresh_stats)

        layout.addLayout(summary_layout)
        layout.addWidget(QLabel(tr('queen.data_center.like_level_distribution')))
        self.like_level_table = self._build_distribution_table()
        layout.addWidget(self.like_level_table)
        layout.addWidget(QLabel(tr('queen.data_center.video_level_distribution')))
        self.video_level_table = self._build_distribution_table()
        layout.addWidget(self.video_level_table)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_refresh_stats, self.like_level_table, self.video_level_table])

    def load_data(self):
        self.start_async_task(
            lambda: self.backend_client.get_queen_library_stats(),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.queen_count_value.setText(str(int(payload.get('queen_count', 0) or 0)))
        self.video_count_value.setText(str(int(payload.get('video_count', 0) or 0)))
        self._render_distribution_table(self.like_level_table, payload.get('like_level_distribution', []) or [])
        self._render_distribution_table(self.video_level_table, payload.get('video_level_distribution', []) or [])

    @staticmethod
    def _build_distribution_table():
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(tr('queen.data_center.distribution_headers'))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        return table

    @staticmethod
    def _render_distribution_table(table, rows):
        table.setRowCount(0)
        for row_index, row in enumerate(rows or []):
            payload = dict(row or {})
            table.insertRow(row_index)
            level = str(payload.get('level', '') or '').strip() or tr('queen.common.unfilled')
            count = str(int(payload.get('count', 0) or 0))
            table.setItem(row_index, 0, QTableWidgetItem(level))
            table.setItem(row_index, 1, QTableWidgetItem(count))


class QueenLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.queens = []
        self.keywords = []
        self.stats = {}
        self.keyword_window = None
        self.data_center_window = None
        self.crawl_progress_timer = None
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('queen.library.title'))
        self.resize(1120, 680)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText(tr('queen.library.search_placeholder'))
        self.btn_search = QPushButton(tr('queen.library.search'))
        self.btn_search.clicked.connect(self.search_keyword)
        self.btn_keyword_library = QPushButton(tr('queen.keyword_library.title'))
        self.btn_keyword_library.clicked.connect(self.show_keyword_library)
        self.btn_data_center = QPushButton(tr('queen.data_center.button'))
        self.btn_data_center.clicked.connect(self.show_data_center)
        self.btn_start_crawl = QPushButton(tr('queen.library.start_crawl'))
        self.btn_start_crawl.clicked.connect(self.start_crawl)
        self.btn_stop_crawl = QPushButton(tr('queen.library.stop_crawl'))
        self.btn_stop_crawl.clicked.connect(self.stop_crawl)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))

        top_layout.addWidget(QLabel(tr('queen.library.keyword_label')))
        top_layout.addWidget(self.keyword_input, 1)
        top_layout.addWidget(self.btn_search)
        top_layout.addWidget(self.btn_keyword_library)
        top_layout.addWidget(self.btn_data_center)
        top_layout.addWidget(self.btn_start_crawl)
        top_layout.addWidget(self.btn_stop_crawl)
        top_layout.addWidget(self.btn_refresh)

        self.status_label = QLabel(tr('queen.library.initial_status'))
        self.crawl_progress_timer = QTimer(self)
        self.crawl_progress_timer.setInterval(2000)
        self.crawl_progress_timer.timeout.connect(self.poll_crawl_progress)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setHorizontalSpacing(10)
        self.grid_layout.setVerticalSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.scroll_widget)

        layout.addLayout(top_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [
                self.keyword_input,
                self.btn_search,
                self.btn_keyword_library,
                self.btn_data_center,
                self.btn_start_crawl,
                self.btn_stop_crawl,
                self.btn_refresh,
            ]
        )
        self._set_crawl_running_state(False)

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: {
                'queens': self.backend_client.list_queen_library_snapshot(force_refresh=force_refresh).get('queens', []),
                'keywords': self.backend_client.list_queen_keywords_snapshot(force_refresh=force_refresh).get('keywords', []),
                'stats': self.backend_client.get_queen_library_stats(),
            },
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        self.stats = dict(payload.get('stats', {}) or {})
        self._update_status_summary()
        self._render_queen_buttons()
        self._sync_keyword_window()

    def _sync_keyword_window(self):
        if self.keyword_window is not None and self.keyword_window.isVisible():
            self.keyword_window.keywords = list(self.keywords)
            self.keyword_window._render_keyword_buttons()
            self.keyword_window.info_label.setText(tr('queen.keyword.saved_count', count=len(self.keywords)))

    def _update_status_summary(self):
        self.status_label.setText(
            tr(
                'queen.library.summary',
                queen_count=len(self.queens),
                video_count=self._current_video_count(),
                keyword_count=len(self.keywords),
            )
        )

    def _current_video_count(self):
        if self.stats:
            return int(self.stats.get('video_count', 0) or 0)
        return sum(int((row or {}).get('video_count', 0) or 0) for row in self.queens)

    def _render_queen_buttons(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, row in enumerate(self.queens):
            queen_name = str((row or {}).get('queen_name', '') or '').strip()
            button = QPushButton(queen_name)
            button.setFixedSize(104, 36)
            button_style = self._build_queen_button_like_level_style((row or {}).get('like_level', ''))
            if button_style:
                button.setStyleSheet(button_style)
            button.clicked.connect(lambda _checked=False, value=queen_name: self.show_queen_detail(value))
            self.grid_layout.addWidget(button, index // BUTTONS_PER_ROW, index % BUTTONS_PER_ROW)

    @staticmethod
    def _build_queen_button_like_level_style(like_level):
        style = QUEEN_PROFILE_LIKE_LEVEL_STYLES.get(str(like_level or '').strip().upper())
        if not style:
            return ''
        return (
            'QPushButton {'
            f' background-color: {style["background"]};'
            f' color: {style["foreground"]};'
            f' border: 1px solid {style["border"]};'
            ' border-radius: 4px;'
            ' font-weight: 600;'
            '}'
            'QPushButton:hover {'
            f' background-color: {style["border"]};'
            '}'
        )

    def search_keyword(self):
        keyword = self.keyword_input.text().strip()
        if not keyword:
            QMessageBox.information(self, tr('common.prompt'), tr('queen.library.keyword_required'))
            return
        existing_keywords = {
            str((row or {}).get('keyword', '') or '').strip()
            for row in self.keywords
            if str((row or {}).get('keyword', '') or '').strip()
        }
        if keyword in existing_keywords:
            QMessageBox.information(self, tr('common.prompt'), tr('queen.library.keyword_exists'))
            return
        self.start_async_task(
            lambda: self.backend_client.search_queen_keyword(keyword, show_browser=True),
            self._on_search_finished,
            tr('queen.library.search_failed'),
        )

    def _on_search_finished(self, result):
        payload = dict(result or {})
        self.keyword_input.clear()
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        self.stats = dict(payload.get('stats', {}) or self.stats or {})
        self.status_label.setText(
            tr(
                'queen.library.search_completed',
                scanned_count=int(payload.get('scanned_count', 0) or 0),
                imported_count=int(payload.get('imported_count', 0) or 0),
                skipped_count=int(payload.get('skipped_count', 0) or 0),
                video_count=self._current_video_count(),
            )
        )
        self._render_queen_buttons()
        self._sync_keyword_window()

    def start_crawl(self):
        self._set_crawl_running_state(True)
        self.status_label.setText(tr('queen.library.starting_crawl'))
        self.start_async_task(
            lambda: self.backend_client.refresh_queen_library(show_browser=True),
            self._on_crawl_finished,
            tr('queen.library.crawl_failed'),
            block_ui=False,
        )

    def stop_crawl(self):
        try:
            result = self.backend_client.cancel_queen_library_refresh()
        except Exception as exc:
            QMessageBox.critical(self, tr('common.operation_failed'), str(exc))
            return
        payload = dict(result or {})
        self.status_label.setText(_translated_backend_message(payload, 'queen.library.stop_requested'))
        self.btn_stop_crawl.setEnabled(False)

    def _set_crawl_running_state(self, is_running):
        running = bool(is_running)
        self.btn_start_crawl.setEnabled(not running)
        self.btn_stop_crawl.setEnabled(running)

    def _on_crawl_finished(self, result):
        payload = dict(result or {})
        if 'progress' in payload:
            self._apply_crawl_progress(dict(payload.get('progress', {}) or {}))
            return
        self._set_crawl_running_state(False)
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        self.stats = dict(payload.get('stats', {}) or self.stats or {})
        self.status_label.setText(self._format_crawl_completed(payload))
        self._render_queen_buttons()
        self._sync_keyword_window()

    def _format_crawl_completed(self, payload):
        log_path = str(payload.get('log_path', '') or '').strip()
        log_text = tr('queen.library.log_suffix', log_path=log_path) if log_path else ''
        return tr(
            'queen.library.crawl_completed',
            processed_count=int(payload.get('processed_count', payload.get('query_count', 0)) or 0),
            total_count=int(payload.get('total_count', payload.get('query_count', 0)) or 0),
            scanned_count=int(payload.get('scanned_count', 0) or 0),
            imported_count=int(payload.get('imported_count', 0) or 0),
            skipped_count=int(payload.get('skipped_count', 0) or 0),
            video_count=self._current_video_count(),
            log_text=log_text,
        )

    def poll_crawl_progress(self):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: {'progress': self.backend_client.get_queen_refresh_progress()},
            self._on_crawl_progress_loaded,
            tr('common.read_failed'),
            block_ui=False,
        )

    def _on_crawl_progress_loaded(self, result):
        payload = dict(result or {})
        self._apply_crawl_progress(dict(payload.get('progress', {}) or {}))

    def _apply_crawl_progress(self, progress):
        payload = dict(progress or {})
        if not payload:
            return
        if bool(payload.get('is_running')):
            if self.crawl_progress_timer is not None and not self.crawl_progress_timer.isActive():
                self.crawl_progress_timer.start()
            self._set_crawl_running_state(True)
            processed_count = int(payload.get('processed_count', 0) or 0)
            total_count = int(payload.get('total_count', payload.get('query_count', 0)) or 0)
            imported_count = int(payload.get('imported_count', 0) or 0)
            skipped_count = int(payload.get('skipped_count', 0) or 0)
            self.status_label.setText(
                tr(
                    'queen.library.crawl_running',
                    processed_count=processed_count,
                    total_count=total_count,
                    imported_count=imported_count,
                    skipped_count=skipped_count,
                    video_count=self._current_video_count(),
                )
            )
            return

        if self.crawl_progress_timer is not None and self.crawl_progress_timer.isActive():
            self.crawl_progress_timer.stop()
        self._set_crawl_running_state(False)
        if bool(payload.get('failed')):
            self.status_label.setText(
                _translated_backend_message(payload, 'queen.library.crawl_failed')
                or str(payload.get('error', '') or '')
            )
            return
        if bool(payload.get('stopped')):
            processed_count = int(payload.get('processed_count', payload.get('query_count', 0)) or 0)
            total_count = int(payload.get('total_count', payload.get('query_count', 0)) or 0)
            self.status_label.setText(
                _translated_backend_message(payload)
                or tr(
                    'queen.library.crawl_stopped',
                    processed_count=processed_count,
                    total_count=total_count,
                )
            )
            return
        if bool(payload.get('completed')):
            self.queens = sort_queen_rows(payload.get('queens', []) or [])
            self.keywords = list(payload.get('keywords', []) or [])
            self.stats = dict(payload.get('stats', {}) or self.stats or {})
            self.status_label.setText(self._format_crawl_completed(payload))
            self._render_queen_buttons()
            self._sync_keyword_window()

    def show_data_center(self):
        self.data_center_window = QueenLibraryDataCenterWindow(self.backend_client, self)
        self.data_center_window.show()
        self.data_center_window.raise_()
        self.data_center_window.activateWindow()

    def show_keyword_library(self):
        self.keyword_window = KeywordLibraryWindow(self.backend_client, self)
        self.keyword_window.exec_()

    def show_queen_detail(self, queen_name):
        viewer = QueenDetailWindow(self.backend_client, queen_name, self)
        viewer.exec_()
        self.load_data(force_refresh=True)
