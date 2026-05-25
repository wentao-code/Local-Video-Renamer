from PyQt5.QtCore import QThread, Qt
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

from app.gui.backend_task_worker import BackendTaskWorker


class PathLibraryWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.selected_path = ''
        self.paths = []
        self.summary = {}
        self.task_thread = None
        self.task_worker = None
        self._task_success_handler = None
        self._task_error_title = ''
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
        self.table.setHorizontalHeaderLabels(
            [
                'ID',
                '入口',
                '路径',
                '总容量',
                '剩余空间',
                '已用空间',
                '使用率',
                '创建时间',
            ]
        )
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

    def load_data(self):
        def task():
            result = self.backend_client.get_path_library()
            return {
                'paths': result.get('paths', []),
                'summary': result.get('summary', {}),
            }

        self._start_background_task(task, self._on_load_data_finished, '读取失败')

    def render_rows(self, paths, summary):
        self.table.setRowCount(0)

        for row_idx, row_data in enumerate(paths):
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

        self.append_summary_row(summary)

    def append_summary_row(self, summary):
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        usage_percent = summary.get('usage_percent', '')
        usage_text = f'{usage_percent}%' if usage_percent != '' else ''
        values = (
            '合计',
            f"共 {summary.get('path_count', 0)} 条 / 在线 {summary.get('connected_count', 0)} 条",
            '所有路径',
            summary.get('total', ''),
            summary.get('free', ''),
            summary.get('used', ''),
            usage_text,
            '',
        )

        for col_idx, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter if col_idx != 2 else Qt.AlignLeft | Qt.AlignVCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.table.setItem(row_idx, col_idx, item)

    def add_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, '添加路径到路径库')
        if not folder_path:
            return

        def task():
            self.backend_client.add_path(folder_path)
            result = self.backend_client.get_path_library()
            return {
                'paths': result.get('paths', []),
                'summary': result.get('summary', {}),
            }

        self._start_background_task(task, self._on_load_data_finished, '添加失败')

    def delete_selected_path(self):
        row = self.current_row()
        if row < 0:
            QMessageBox.warning(self, '提示', '请先选择要删除的路径')
            return

        path_id = self.table.item(row, 0).text()
        path_text = self.table.item(row, 2).text()
        confirmed = QMessageBox.question(
            self,
            '确认删除',
            f'确定从路径库删除这个路径吗？\n{path_text}',
        )
        if confirmed != QMessageBox.Yes:
            return

        def task():
            self.backend_client.delete_path(int(path_id))
            result = self.backend_client.get_path_library()
            return {
                'paths': result.get('paths', []),
                'summary': result.get('summary', {}),
            }

        self._start_background_task(task, self._on_load_data_finished, '删除失败')

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
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return -1
        return row

    def _start_background_task(self, task, success_handler, error_title):
        if self.task_thread is not None:
            return False

        self._set_busy(True)
        self._task_success_handler = success_handler
        self._task_error_title = str(error_title or '操作失败')
        self.task_thread = QThread(self)
        self.task_worker = BackendTaskWorker(task)
        self.task_worker.moveToThread(self.task_thread)
        self.task_thread.started.connect(self.task_worker.run)
        self.task_worker.finished.connect(self._handle_task_finished)
        self.task_worker.failed.connect(self._handle_task_failed)
        self.task_worker.finished.connect(self.task_thread.quit)
        self.task_worker.failed.connect(self.task_thread.quit)
        self.task_thread.finished.connect(self._cleanup_task_thread)
        self.task_thread.start()
        return True

    def _handle_task_finished(self, result):
        handler = self._task_success_handler
        self._task_success_handler = None
        self._task_error_title = ''
        if handler is not None:
            handler(result)

    def _handle_task_failed(self, message):
        error_title = self._task_error_title or '操作失败'
        self._task_success_handler = None
        self._task_error_title = ''
        QMessageBox.critical(self, error_title, str(message or '发生未知错误。'))

    def _cleanup_task_thread(self):
        if self.task_worker is not None:
            self.task_worker.deleteLater()
        if self.task_thread is not None:
            self.task_thread.deleteLater()
        self.task_worker = None
        self.task_thread = None
        self._set_busy(False)

    def _set_busy(self, busy):
        self.btn_add.setEnabled(not busy)
        self.btn_delete.setEnabled(not busy)
        self.btn_use.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def _on_load_data_finished(self, result):
        self.paths = list((result or {}).get('paths', []) or [])
        self.summary = dict((result or {}).get('summary', {}) or {})
        self.render_rows(self.paths, self.summary)

    def closeEvent(self, event):
        if self.task_thread and self.task_thread.isRunning():
            QMessageBox.information(self, '操作进行中', '请等待当前操作完成后再关闭窗口。')
            event.ignore()
            return
        super().closeEvent(event)
