from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QGridLayout,
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
from app.gui.backend_task_worker import AsyncTaskHostMixin


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


class GlobalMedalPickerDialog(QDialog):
    def __init__(self, medals, owned_medals=None, parent=None):
        super().__init__(parent)
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
            self.table.setCellWidget(row_index, 1, description_editor)
            self.table.setCellWidget(row_index, 2, self._build_action_widget(row_index, name, description_editor))

        self.summary_label.setText(f'共 {len(self.rows)} 枚勋章')
        self.table.resizeColumnsToContents()

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
