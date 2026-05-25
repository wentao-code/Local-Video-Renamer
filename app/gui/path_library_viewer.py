from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin


class PathLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.selected_path = ''
        self.paths = []
        self.summary = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('路径库')
        self.resize(900, 460)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()

        self.btn_add = QPushButton('添加')
        self.btn_add.clicked.connect(self.add_path)
        self.btn_delete = QPushButton('删除')
        self.btn_delete.clicked.connect(self.delete_selected_path)
        self.btn_use = QPushButton('使用选中路径')
        self.btn_use.clicked.connect(self.use_selected_path)
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('已保存路径'))
        top_layout.addStretch()
        top_layout.addWidget(self.btn_add)
        top_layout.addWidget(self.btn_delete)
        top_layout.addWidget(self.btn_use)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['ID', '入口', '路径', '总容量', '剩余空间', '已用空间', '使用率', '创建时间'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self.use_selected_path)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_add, self.btn_delete, self.btn_use, self.btn_refresh, self.table])

    def load_data(self):
        self.start_async_task(
            lambda: self.backend_client.get_path_library(),
            self._on_load_data_finished,
            '读取失败',
        )

    def render_rows(self):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(self.paths):
            self.table.insertRow(row_idx)
            if row_data.get('exists'):
                entrance = 'U盘入口'
            elif row_data.get('uses_last_snapshot'):
                entrance = '未连接（上次记录）'
            else:
                entrance = '未连接'

            usage_percent = row_data.get('usage_percent', '')
            usage_text = f'{usage_percent}%' if usage_percent != '' else ''
            values = (
                row_data.get('id', ''),
                entrance,
                row_data.get('path', ''),
                row_data.get('total', ''),
                row_data.get('free', ''),
                row_data.get('used', ''),
                usage_text,
                row_data.get('created_at', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (0, 1, 3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        usage_percent = self.summary.get('usage_percent', '')
        usage_text = f'{usage_percent}%' if usage_percent != '' else ''
        summary_values = (
            '合计',
            f"共 {self.summary.get('path_count', 0)} 条 / 在线 {self.summary.get('connected_count', 0)} 条",
            '所有路径',
            self.summary.get('total', ''),
            self.summary.get('free', ''),
            self.summary.get('used', ''),
            usage_text,
            '',
        )
        for col_idx, value in enumerate(summary_values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter if col_idx != 2 else Qt.AlignLeft | Qt.AlignVCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.table.setItem(row_idx, col_idx, item)

    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, '添加路径到路径库')
        if not folder_path:
            return
        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.add_path(folder_path)),
            self._on_load_data_finished,
            '添加失败',
        )

    def delete_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, '提示', '请先选择要删除的路径')
            return

        path_id = int(self.table.item(row, 0).text())
        path_text = self.table.item(row, 2).text()
        answer = QMessageBox.question(self, '确认删除', f'确定从路径库删除这个路径吗？\n{path_text}')
        if answer != QMessageBox.Yes:
            return

        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.delete_path(path_id)),
            self._on_load_data_finished,
            '删除失败',
        )

    def _reload_after(self, operation):
        operation()
        return self.backend_client.get_path_library()

    def use_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, '提示', '请先选择一个路径')
            return
        self.selected_path = self.table.item(row, 2).text()
        self.accept()

    def current_row(self):
        selected_ranges = self.table.selectedRanges()
        if not selected_ranges:
            return -1
        row = selected_ranges[0].topRow()
        item = self.table.item(row, 0)
        if not item or not item.text().isdigit():
            return -1
        return row

    def _on_load_data_finished(self, result):
        result = dict(result or {})
        self.paths = list(result.get('paths', []) or [])
        self.summary = dict(result.get('summary', {}) or {})
        self.render_rows()
