from PyQt5.QtCore import QThread, Qt
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
    QWidget,
)

from app.gui.backend_task_worker import BackendTaskWorker
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow


class CodePrefixViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.editing_prefix = None
        self.editing_row = None
        self.action_buttons = {}
        self.task_thread = None
        self.task_worker = None
        self._task_success_handler = None
        self._task_error_title = ''
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('番号库')
        self.resize(1160, 560)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入番号前缀实时筛选，例如 AARM、IPX...')
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset = QPushButton('选中重置')
        self.btn_reset.clicked.connect(self.reset_selected_rows)

        self.btn_refresh = QPushButton('刷新数据')
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选：'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                '番号',
                '本地视频数',
                '补全状态',
                'AVFan作品数',
                '最早发布日期',
                '最晚发布日期',
                '详情',
                '操作',
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        search_text = self.search_input.text().strip()

        def task():
            rows = self.backend_client.list_code_prefixes(search_text)
            return {
                'rows': rows,
            }

        self._start_background_task(task, self._on_load_data_finished, '读取失败')

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('prefix', ''),
                row_data.get('video_count', 0),
                row_data.get('enrichment_status', ''),
                row_data.get('avfan_total_videos', 0),
                row_data.get('earliest_release_date', ''),
                row_data.get('latest_release_date', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            prefix = row_data.get('prefix', '')
            self.table.setCellWidget(row_idx, 6, self.build_detail_button(prefix))
            self.table.setCellWidget(row_idx, 7, self.build_action_buttons(prefix))

    def build_detail_button(self, prefix):
        button = QPushButton('查看详情')
        button.clicked.connect(lambda _checked=False, value=prefix: self.show_prefix_detail(value))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, prefix):
        edit_button = QPushButton('修改')
        edit_button.clicked.connect(lambda _checked=False, value=prefix: self.handle_edit_button(value))

        delete_button = QPushButton('删除')
        delete_button.clicked.connect(lambda _checked=False, value=prefix: self.delete_prefix(value))

        self.action_buttons[prefix] = {
            'edit': edit_button,
            'delete': delete_button,
        }

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_prefix_detail(self, prefix):
        if not prefix:
            return
        viewer = CodePrefixDetailViewerWindow(
            backend_client=self.backend_client,
            prefix=prefix,
            parent=self,
        )
        viewer.exec_()

    def filter_data(self, text):
        if self.task_thread is not None:
            return

        self.clear_edit_state()
        search_text = (text or '').strip()
        if not search_text:
            self.load_data()
            return

        try:
            self.rows = self.backend_client.list_code_prefixes(search_text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选番号库失败: {exc}')

    def clear_edit_state(self):
        self.editing_prefix = None
        self.editing_row = None

    def refresh_current_view(self):
        self.load_data()

    def handle_edit_button(self, prefix):
        if self.editing_prefix is None:
            self.start_prefix_edit(prefix)
            return

        if self.editing_prefix != prefix:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的番号行。')
            return

        self.confirm_prefix_edit()

    def start_prefix_edit(self, prefix):
        row = self.find_row_by_prefix(prefix)
        if row < 0:
            QMessageBox.warning(self, '提示', f'未找到番号前缀：{prefix}')
            return

        self.editing_prefix = prefix
        self.editing_row = row
        self.set_prefix_cell_editable(row, True)

        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText('确认')

        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_prefix_edit(self):
        if self.editing_prefix is None or self.editing_row is None:
            return

        item = self.table.item(self.editing_row, 0)
        old_prefix = self.editing_prefix
        if item is None:
            self.clear_edit_state()
            return

        new_prefix = item.text().strip().upper()
        self.set_prefix_cell_editable(self.editing_row, False)

        if not new_prefix:
            item.setText(old_prefix)
            self.reset_row_button_text(old_prefix)
            self.clear_edit_state()
            QMessageBox.warning(self, '提示', '番号前缀不能为空')
            return

        self.clear_edit_state()

        def task():
            self.backend_client.rename_code_prefix(old_prefix, new_prefix)
            rows = self.backend_client.list_code_prefixes(self.search_input.text().strip())
            return {
                'rows': rows,
                'old_prefix': old_prefix,
                'new_prefix': new_prefix,
            }

        def on_success(result):
            self._on_load_data_finished(result)
            QMessageBox.information(
                self,
                '修改完成',
                f"已将番号前缀 {result.get('old_prefix', old_prefix)} 修改为 {result.get('new_prefix', new_prefix)}。",
            )

        self._start_background_task(task, on_success, '修改失败')

    def reset_row_button_text(self, prefix):
        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText('修改')

    def set_prefix_cell_editable(self, row, editable):
        item = self.table.item(row, 0)
        if item is None:
            return
        flags = item.flags()
        if editable:
            item.setFlags(flags | Qt.ItemIsEditable)
            return
        item.setFlags(flags & ~Qt.ItemIsEditable)

    def find_row_by_prefix(self, prefix):
        target = str(prefix or '').strip().upper()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip().upper() == target:
                return row
        return -1

    def delete_prefix(self, prefix):
        if self.editing_prefix is not None:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的番号行。')
            return

        answer = QMessageBox.question(
            self,
            '确认删除',
            (
                f'确定删除番号前缀 {prefix} 吗？\n'
                '这会从番号库隐藏该前缀，并清除对应的网页补全数据，不会删除本地视频记录。'
            ),
        )
        if answer != QMessageBox.Yes:
            return

        def task():
            self.backend_client.delete_code_prefix(prefix)
            rows = self.backend_client.list_code_prefixes(self.search_input.text().strip())
            return {
                'rows': rows,
                'prefix': prefix,
            }

        def on_success(result):
            self._on_load_data_finished(result)
            QMessageBox.information(self, '删除完成', f"已删除番号前缀 {result.get('prefix', prefix)}。")

        self._start_background_task(task, on_success, '删除失败')

    def reset_selected_rows(self):
        prefixes = self.selected_prefixes()
        if not prefixes:
            QMessageBox.information(self, '未选择', '请先选中要重置的番号行。')
            return

        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(prefixes)} 个番号补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()

        def task():
            reset_count = self.backend_client.reset_code_prefix_enrichments(prefixes)
            rows = self.backend_client.list_code_prefixes(search_text)
            return {
                'reset_count': reset_count,
                'rows': rows,
            }

        self._start_background_task(task, self._on_reset_finished, '重置失败')

    def selected_prefixes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        prefixes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                prefixes.append(item.text().strip())
        return prefixes

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
        self.search_input.setEnabled(not busy)
        self.btn_reset.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)

    def _on_reset_finished(self, result):
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        self._on_load_data_finished(result)
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个番号的补全状态。')

    def closeEvent(self, event):
        if self.task_thread and self.task_thread.isRunning():
            QMessageBox.information(self, '操作进行中', '请等待当前操作完成后再关闭窗口。')
            event.ignore()
            return
        super().closeEvent(event)
