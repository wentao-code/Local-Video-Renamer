from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin


class TimeoutSettingsViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.custom_editors = {}
        self.indicator_labels = {}
        self.row_keys = []
        self._init_async_task_host()
        self._init_ui()
        self.load_data()

    def _init_ui(self):
        self.setWindowTitle('超时器')
        self.resize(900, 560)
        self.setMinimumSize(760, 420)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ['操作名称', '默认值（秒）', '修改值（秒）', '当前生效值', '状态']
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        root_layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.btn_save = QPushButton('确认修改')
        self.btn_reset_selected = QPushButton('恢复选中项默认值')
        self.btn_reset_all = QPushButton('全部恢复默认值')
        self.btn_refresh = QPushButton('刷新')
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_reset_selected.clicked.connect(self.reset_selected)
        self.btn_reset_all.clicked.connect(self.reset_all)
        self.btn_refresh.clicked.connect(self.load_data)
        button_layout.addWidget(self.btn_save)
        button_layout.addWidget(self.btn_reset_selected)
        button_layout.addWidget(self.btn_reset_all)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(button_layout)

        self.set_async_busy_widgets(
            [self.table, self.btn_save, self.btn_reset_selected, self.btn_reset_all, self.btn_refresh]
        )

    def load_data(self):
        if self.is_async_task_running():
            return
        self.start_async_task(
            self.backend_client.list_operation_timeouts,
            self._render_rows,
            '读取超时设置失败',
            task_title='超时器 读取设置',
        )

    def save_changes(self):
        if self.is_async_task_running():
            return
        values = {
            setting_key: editor.text().strip()
            for setting_key, editor in self.custom_editors.items()
        }
        self.start_async_task(
            lambda: self.backend_client.update_operation_timeouts(values),
            self._render_rows,
            '保存超时设置失败',
            task_title='超时器 保存设置',
        )

    def reset_selected(self):
        if self.is_async_task_running():
            return
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        setting_keys = [self.row_keys[row] for row in selected_rows if 0 <= row < len(self.row_keys)]
        if not setting_keys:
            QMessageBox.information(self, '请选择操作', '请先选中需要恢复默认值的操作。')
            return
        self._reset(setting_keys)

    def reset_all(self):
        if self.is_async_task_running():
            return
        self._reset(None)

    def _reset(self, setting_keys):
        self.start_async_task(
            lambda: self.backend_client.reset_operation_timeouts(setting_keys),
            self._render_rows,
            '恢复默认值失败',
            task_title='超时器 恢复默认值',
        )

    def _render_rows(self, rows):
        normalized_rows = list(rows or [])
        self.table.setRowCount(len(normalized_rows))
        self.custom_editors = {}
        self.indicator_labels = {}
        self.row_keys = []

        for row_index, row in enumerate(normalized_rows):
            setting_key = str(row.get('setting_key', '') or '').strip()
            self.row_keys.append(setting_key)
            self._set_read_only_item(row_index, 0, row.get('operation_name', ''))
            self._set_read_only_item(
                row_index,
                1,
                self._format_seconds(row.get('default_value_seconds')),
                Qt.AlignCenter,
            )

            editor = QLineEdit(self.table)
            editor.setAlignment(Qt.AlignCenter)
            validator = QDoubleValidator(
                float(row.get('minimum_value_seconds', 0.1) or 0.1),
                float(row.get('maximum_value_seconds', 3600) or 3600),
                3,
                editor,
            )
            validator.setNotation(QDoubleValidator.StandardNotation)
            editor.setValidator(validator)
            custom_value = row.get('custom_value_seconds')
            editor.setText('' if custom_value is None else self._format_seconds(custom_value))
            editor.setPlaceholderText('使用默认值')
            self.table.setCellWidget(row_index, 2, editor)
            self.custom_editors[setting_key] = editor

            self._set_read_only_item(
                row_index,
                3,
                self._format_seconds(row.get('effective_value_seconds')),
                Qt.AlignCenter,
            )
            indicator = QLabel('●', self.table)
            indicator.setAlignment(Qt.AlignCenter)
            uses_default = bool(row.get('uses_default', True))
            color = '#2e7d32' if uses_default else '#c62828'
            indicator.setStyleSheet(f'color: {color}; font-size: 18px;')
            indicator.setToolTip('使用默认值' if uses_default else '使用修改值')
            self.table.setCellWidget(row_index, 4, indicator)
            self.indicator_labels[setting_key] = indicator

        self.table.resizeRowsToContents()

    def _set_read_only_item(self, row, column, value, alignment=Qt.AlignLeft | Qt.AlignVCenter):
        item = QTableWidgetItem(str(value or ''))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setTextAlignment(alignment)
        self.table.setItem(row, column, item)

    @staticmethod
    def _format_seconds(value):
        if value is None:
            return ''
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
        return f'{numeric_value:.3f}'.rstrip('0').rstrip('.')
