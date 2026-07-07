from html import escape

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QGroupBox,
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

from app.core.ladder_board import split_ladder_medals
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.medal_catalog_viewer import GlobalMedalPickerDialog, build_medal_text


class MasterpieceWindow(QDialog, AsyncTaskHostMixin):
    _MEDAL_STYLES = {
        'border': '#b96a3b',
        'background': '#f6d8c3',
        'text': '#7a3513',
    }

    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.setWindowTitle('名作堂')
        self.resize(980, 640)
        self._init_ui()
        self.load_entries()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('视频编号'))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText('输入视频编号，例如 PFSA-001')
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
        self.table.setHorizontalHeaderLabels(['编号', '标题', '演员', '勋章', '操作', '详情'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)

        layout.addLayout(toolbar)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

        self.set_async_busy_widgets([self.code_input, self.btn_add, self.btn_refresh, self.table])

    def load_entries(self):
        self.start_async_task(
            lambda: self.backend_client.list_masterpiece_entries(),
            self._on_entries_loaded,
            '读取名作堂失败',
        )

    def handle_add_entry(self):
        code = str(self.code_input.text() or '').strip()
        if not code:
            QMessageBox.warning(self, '缺少编号', '请先输入要加入名作堂的视频编号。')
            return

        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.add_masterpiece_entry(code),
                self.backend_client.list_masterpiece_entries,
                entry_code=str(code or '').strip().upper(),
            ),
            self._on_rows_reloaded_after_add,
            '添加名作堂失败',
        )

    def _on_rows_reloaded_after_add(self, payload):
        payload = dict(payload or {})
        added_code = str(payload.get('entry_code', '') or '').strip()
        self.code_input.clear()
        self.code_input.setFocus()
        self._on_entries_loaded(payload)
        if added_code:
            self.edit_medal(added_code, '')

    def _on_entries_loaded(self, payload):
        rows = payload
        if isinstance(payload, dict):
            rows = payload.get('rows', [])
        self.rows = [dict(row or {}) for row in (rows or [])]
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
            self.table.setItem(row_index, 0, QTableWidgetItem(code))
            self.table.setItem(row_index, 1, QTableWidgetItem(title))
            self.table.setItem(row_index, 2, QTableWidgetItem(author))
            self.table.setCellWidget(row_index, 3, self._build_medal_widget(medals))
            self.table.setCellWidget(row_index, 4, self._build_medal_button(code, medal_text))
            self.table.setCellWidget(row_index, 5, self._build_detail_button(code))

        self.summary_label.setText(f'共 {len(self.rows)} 条')
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()

    def _build_medal_widget(self, medals):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setMargin(4)
        label.setText(self._build_medal_html(medals))
        return label

    def _build_medal_button(self, code, medal_text):
        button = QPushButton('选择勋章')
        button.clicked.connect(
            lambda _checked=False, target_code=code, target_medal=medal_text: self.edit_medal(
                target_code,
                target_medal,
            )
        )
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

    def edit_medal(self, code, medal_text):
        current_medals = list(split_ladder_medals(medal_text))
        self.start_async_task(
            lambda: self.backend_client.list_global_medals(),
            lambda medals: self._open_medal_picker(code, current_medals, medals),
            '读取勋章堂失败',
        )

    def _open_medal_picker(self, code, current_medals, medals):
        dialog = GlobalMedalPickerDialog(medals, owned_medals=current_medals, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return

        merged_text = build_medal_text(current_medals, dialog.selected_medal_names())
        if merged_text == build_medal_text(current_medals, []):
            return

        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.update_masterpiece_entry_medal(code, merged_text),
                self.backend_client.list_masterpiece_entries,
            ),
            self._on_entries_loaded,
            '保存勋章失败',
        )

    def show_detail(self, code):
        dialog = MasterpieceDetailWindow(self.backend_client, code, self)
        dialog.exec_()

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)


class MasterpieceDetailWindow(QDialog):
    _SOURCE_TITLES = {
        'video_library': '视频库参考',
        'actor_library': '演员库参考',
        'code_prefix_library': '番号库参考',
    }
    _SOURCE_ORDER = ('video_library', 'actor_library', 'code_prefix_library')
    _ACTOR_HEADERS = ['演员', '生日', '年龄', '出演年龄', '身高', '三围', '罩杯', '详情']

    def __init__(self, backend_client, code, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.code = str(code or '').strip()
        self.detail = {}
        self.collaborator_tables = {}
        self.setWindowTitle(f'名作堂详情 - {self.code}')
        self.resize(980, 760)
        self._init_ui()
        self.load_detail()

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        self.summary_label = QLabel('')
        self.summary_label.setWordWrap(True)
        root_layout.addWidget(self.summary_label)

        self.btn_open_primary = QPushButton('打开主链接')
        self.btn_open_primary.clicked.connect(self.open_primary_link)
        root_layout.addWidget(self.btn_open_primary, 0, Qt.AlignLeft)

        actor_group = QGroupBox('演员信息')
        actor_layout = QVBoxLayout(actor_group)
        self.actor_table = QTableWidget()
        self.actor_table.setColumnCount(len(self._ACTOR_HEADERS))
        self.actor_table.setHorizontalHeaderLabels(list(self._ACTOR_HEADERS))
        self.actor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.actor_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.actor_table.verticalHeader().setVisible(False)
        actor_layout.addWidget(self.actor_table)
        root_layout.addWidget(actor_group)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        scroll_area.setWidget(self.content_widget)

    def load_detail(self):
        self.detail = dict(self.backend_client.get_masterpiece_detail(self.code) or {})
        display_title = str(self.detail.get('display_title', '') or self.detail.get('title', '') or '')
        display_author = str(self.detail.get('display_author', '') or self.detail.get('author', '') or '')
        primary_source = self._source_title(str(self.detail.get('primary_source', '') or ''))
        self.summary_label.setText(
            f'编号: {self.detail.get("code", "")} | 标题: {display_title} | 演员: {display_author or "暂无"} | 主来源: {primary_source}'
        )
        self.btn_open_primary.setEnabled(bool(str(self.detail.get('primary_detail_url', '') or '').strip()))
        self._render_actor_details()
        self._render_detail_sections()

    def _render_actor_details(self):
        actor_rows = list(self.detail.get('actor_details', []) or [])
        self.actor_table.setRowCount(0)
        for row_index, actor in enumerate(actor_rows):
            self.actor_table.insertRow(row_index)
            values = [
                str((actor or {}).get('actor_name', '') or ''),
                str((actor or {}).get('birthday', '') or ''),
                str((actor or {}).get('current_age', '') or ''),
                str((actor or {}).get('appearance_age', '') or ''),
                str((actor or {}).get('height', '') or ''),
                self._build_measurements_text(actor),
                str((actor or {}).get('cup', '') or ''),
                str((actor or {}).get('measurements_raw', '') or ''),
            ]
            for column_index, value in enumerate(values):
                self.actor_table.setItem(row_index, column_index, QTableWidgetItem(value))

        self.actor_table.resizeColumnsToContents()
        self.actor_table.resizeRowsToContents()

    @staticmethod
    def _build_measurements_text(actor):
        bust = str((actor or {}).get('bust', '') or '').strip()
        waist = str((actor or {}).get('waist', '') or '').strip()
        hip = str((actor or {}).get('hip', '') or '').strip()
        if bust and waist and hip:
            return f'{bust}/{waist}/{hip}'
        return str((actor or {}).get('measurements_raw', '') or '').strip()

    def _render_detail_sections(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.collaborator_tables = {}
        self._render_collaborator_sections()
        self._render_reference_groups()

    def _render_collaborator_sections(self):
        sections = list(self.detail.get('collaborator_sections', []) or [])
        for section in sections:
            actor_name = str((section or {}).get('actor_name', '') or '').strip()
            ladder_tier = str((section or {}).get('ladder_tier', '') or '').strip().upper()
            group_box = QGroupBox(f'{actor_name} ({ladder_tier})')
            group_layout = QVBoxLayout(group_box)
            rows = list((section or {}).get('collaborators', []) or [])
            if not rows:
                empty_label = QLabel('鏆傛棤鍚堜綔婕斿憳')
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
                    label = f'{str((collaborator or {}).get("actor_name", "") or "")} x{int((collaborator or {}).get("count", 0) or 0)}'
                    table.setItem(row_index, column_index, QTableWidgetItem(label))
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
