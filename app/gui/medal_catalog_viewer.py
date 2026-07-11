from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QGridLayout,
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

from app.core.ladder_board import normalize_ladder_medal_text, split_ladder_medals
from app.gui.backend_task_worker import AsyncTaskHostMixin, enable_minimize_button


def merge_medal_names(existing_medals=None, new_medals=None):
    merged = []
    seen = set()
    for medal in list(existing_medals or []) + list(new_medals or []):
        normalized = str(medal or '').strip()
        if not normalized or normalized in seen:
            continue
        merged.append(normalized)
        seen.add(normalized)
    return merged


def build_medal_text(existing_medals=None, new_medals=None):
    return normalize_ladder_medal_text('\n'.join(merge_medal_names(existing_medals, new_medals)))


class MedalSelectionSidebar(QWidget):
    _BUTTON_STYLES = {
        'idle': 'background:#f2f2f2; border:1px solid #dddddd; color:#a0a0a0;',
        'active': 'background:#fff8e5; border:1px solid #d4b15c; color:#7a5a16;',
        'editable': 'background:#ffffff; border:1px solid #d6d6d6; color:#333333;',
    }

    def __init__(self, title='勋章选择', inactive_hint='点击左侧添加后可编辑勋章', parent=None):
        super().__init__(parent)
        self.title = str(title or '').strip() or '勋章选择'
        self.inactive_hint = str(inactive_hint or '').strip() or '点击左侧添加后可编辑勋章'
        self.medals = []
        self.medal_names = []
        self.medal_buttons = {}
        self._selected_medals = set()
        self._editing = False
        self._active_label = ''
        self._empty_label = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet('font-size:14px; font-weight:600; color:#333333;')
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(self.inactive_hint)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet('color:#7a7a7a;')
        layout.addWidget(self.hint_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        layout.addWidget(self.scroll_area, 1)

        self.container = QWidget()
        self.button_layout = QVBoxLayout(self.container)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout.setSpacing(8)
        self.button_layout.addStretch()
        self.scroll_area.setWidget(self.container)

    def set_medals(self, medals):
        self.medals = [dict(row or {}) for row in (medals or [])]
        self.medal_names = []
        seen = set()
        for row in self.medals:
            name = str((row or {}).get('name', '') or '').strip()
            if not name or name in seen:
                continue
            self.medal_names.append(name)
            seen.add(name)
        self._selected_medals = set(name for name in self._selected_medals if name in seen)
        self._render_buttons()
        self._apply_state()

    def begin_edit(self, label, selected_medals=None):
        self._editing = True
        self._active_label = str(label or '').strip()
        self._selected_medals = set(
            name for name in (str(medal or '').strip() for medal in (selected_medals or [])) if name in self.medal_names
        )
        self._apply_state()

    def end_edit(self):
        self._editing = False
        self._active_label = ''
        self._selected_medals = set()
        self._apply_state()

    def is_editing(self):
        return self._editing

    def selected_medal_names(self):
        return [name for name in self.medal_names if name in self._selected_medals]

    def _render_buttons(self):
        self.medal_buttons = {}
        while self.button_layout.count():
            item = self.button_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.medal_names:
            self._empty_label = QLabel('暂无勋章')
            self._empty_label.setStyleSheet('color:#9a9a9a; padding:10px 4px;')
            self.button_layout.addWidget(self._empty_label)
        else:
            self._empty_label = None
            for name in self.medal_names:
                button = QPushButton(name)
                button.setCheckable(True)
                button.setMinimumHeight(34)
                button.clicked.connect(lambda checked=False, medal_name=name: self._toggle_medal(medal_name, checked))
                self.medal_buttons[name] = button
                self.button_layout.addWidget(button)

        self.button_layout.addStretch()

    def _toggle_medal(self, medal_name, checked):
        if not self._editing:
            return
        if checked:
            self._selected_medals.add(medal_name)
        else:
            self._selected_medals.discard(medal_name)
        self._refresh_button_style(medal_name)

    def _apply_state(self):
        if self._editing and self._active_label:
            self.hint_label.setText(f'正在编辑：{self._active_label}\n点击勋章切换选中，再点确认保存。')
            self.hint_label.setStyleSheet('color:#6d5423;')
        else:
            self.hint_label.setText(self.inactive_hint)
            self.hint_label.setStyleSheet('color:#7a7a7a;')

        for name, button in self.medal_buttons.items():
            button.blockSignals(True)
            button.setEnabled(self._editing)
            button.setChecked(self._editing and name in self._selected_medals)
            button.blockSignals(False)
            self._refresh_button_style(name)

    def _refresh_button_style(self, medal_name):
        button = self.medal_buttons.get(medal_name)
        if button is None:
            return
        if not self._editing:
            style = self._BUTTON_STYLES['idle']
        elif button.isChecked():
            style = self._BUTTON_STYLES['active']
        else:
            style = self._BUTTON_STYLES['editable']
        button.setStyleSheet(
            f'QPushButton {{ {style} padding:6px 10px; text-align:left; border-radius:8px; font-weight:600; }}'
        )


class GlobalMedalPickerDialog(QDialog):
    def __init__(self, medals, owned_medals=None, parent=None):
        super().__init__(parent)
        enable_minimize_button(self)
        self.medals = [dict(row or {}) for row in (medals or [])]
        self.owned_medals = set(str(medal or '').strip() for medal in (owned_medals or []) if str(medal or '').strip())
        self.medal_checkboxes = {}
        self.setWindowTitle('选择勋章')
        self.resize(720, 420)
        self._init_ui()
        self._render_medals()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        hint = QLabel('可多选勋章。已拥有的勋章会灰显，不能重复选择。')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        layout.addWidget(self.scroll_area)

        self.grid_container = QWidget()
        self.medal_grid = QGridLayout(self.grid_container)
        self.medal_grid.setContentsMargins(8, 8, 8, 8)
        self.medal_grid.setHorizontalSpacing(14)
        self.medal_grid.setVerticalSpacing(12)
        for column in range(4):
            self.medal_grid.setColumnStretch(column, 1)
        self.scroll_area.setWidget(self.grid_container)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.btn_confirm = QPushButton('确认')
        self.btn_confirm.clicked.connect(self.accept)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.clicked.connect(self.reject)
        button_row.addWidget(self.btn_confirm)
        button_row.addWidget(self.btn_cancel)
        layout.addLayout(button_row)

    def _render_medals(self):
        self.medal_checkboxes = {}
        while self.medal_grid.count():
            item = self.medal_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for row_index, medal in enumerate(self.medals):
            name = str(medal.get('name', '') or '').strip()
            if not name:
                continue
            is_owned = name in self.owned_medals
            checkbox = QCheckBox(name)
            checkbox.setEnabled(not is_owned)
            checkbox.setChecked(False)
            checkbox.setToolTip(name)
            if is_owned:
                checkbox.setStyleSheet('color: #9a9a9a;')
            self.medal_checkboxes[name] = checkbox
            self.medal_grid.addWidget(checkbox, row_index // 4, row_index % 4)

    def selected_medal_names(self):
        return [
            name
            for name, checkbox in self.medal_checkboxes.items()
            if checkbox.isEnabled() and checkbox.isChecked()
        ]


class MedalCatalogWindow(QDialog, AsyncTaskHostMixin):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.setWindowTitle('勋章堂')
        self.resize(880, 620)
        self._init_ui()
        self.load_medals()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('勋章名称'))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('输入勋章名称')
        toolbar.addWidget(self.name_input)

        toolbar.addWidget(QLabel('描述'))
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText('输入勋章描述')
        self.description_input.setMinimumWidth(520)
        toolbar.addWidget(self.description_input, 1)

        self.btn_add = QPushButton('添加')
        self.btn_add.clicked.connect(self.handle_add_medal)
        toolbar.addWidget(self.btn_add)

        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_medals)
        toolbar.addWidget(self.btn_refresh)
        layout.addLayout(toolbar)

        self.summary_label = QLabel('共 0 枚勋章')
        layout.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['勋章', '描述', '操作'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.set_async_busy_widgets([self.name_input, self.description_input, self.btn_add, self.btn_refresh, self.table])

    def load_medals(self):
        self.start_async_task(
            lambda: self.backend_client.list_global_medals(),
            self._on_medals_loaded,
            '读取勋章堂失败',
        )

    def handle_add_medal(self):
        name = str(self.name_input.text() or '').strip()
        description = str(self.description_input.text() or '').strip()
        if not name:
            QMessageBox.warning(self, '缺少勋章', '请先输入勋章名称。')
            return
        self.start_async_task(
            lambda: self._reload_medals_after(lambda: self.backend_client.add_global_medal(name, description)),
            self._on_medals_reloaded_after_add,
            '添加勋章失败',
        )

    def _reload_medals_after(self, operation):
        operation()
        return self.backend_client.list_global_medals()

    def _on_medals_reloaded_after_add(self, rows):
        self.name_input.clear()
        self.description_input.clear()
        self.name_input.setFocus()
        self._on_medals_loaded(rows)

    def _on_medals_loaded(self, rows):
        self.rows = [dict(row or {}) for row in (rows or [])]
        self._render_rows()

    def _render_rows(self):
        self.table.setRowCount(0)
        for row_index, row in enumerate(self.rows):
            name = str(row.get('name', '') or '').strip()
            description = str(row.get('description', '') or '').strip()

            self.table.insertRow(row_index)
            self.table.setItem(row_index, 0, QTableWidgetItem(name))

            description_editor = QLineEdit(description)
            description_editor.setMinimumWidth(320)
            self.table.setCellWidget(row_index, 1, description_editor)
            self.table.setCellWidget(row_index, 2, self._build_action_widget(row_index, name, description_editor))

        self.summary_label.setText(f'共 {len(self.rows)} 枚勋章')
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(2)

    def _build_action_widget(self, row_index, name, description_editor):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        save_button = QPushButton('保存')
        save_button.setObjectName(f'save_button_{row_index}')
        save_button.clicked.connect(
            lambda _checked=False, medal_name=name, editor=description_editor: self.save_medal_description(
                medal_name,
                editor.text(),
            )
        )
        delete_button = QPushButton('删除')
        delete_button.setObjectName(f'delete_button_{row_index}')
        delete_button.clicked.connect(
            lambda _checked=False, medal_name=name: self.delete_medal(medal_name)
        )
        layout.addWidget(save_button)
        layout.addWidget(delete_button)
        return widget

    def save_medal_description(self, name, description):
        self.start_async_task(
            lambda: self._reload_medals_after(
                lambda: self.backend_client.update_global_medal_description(name, description)
            ),
            self._on_medals_loaded,
            '保存勋章描述失败',
        )

    def delete_medal(self, name):
        self.start_async_task(
            lambda: self._reload_medals_after(lambda: self.backend_client.delete_global_medal(name)),
            self._on_medals_loaded,
            '删除勋章失败',
        )

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
