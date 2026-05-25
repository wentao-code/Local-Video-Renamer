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
)

from app.gui.backend_task_worker import BackendTaskWorker


class DatabaseViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.all_rows = []
        self.task_thread = None
        self.task_worker = None
        self._task_success_handler = None
        self._task_error_title = ''
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('视频库')
        self.resize(1240, 640)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入视频编号、标题、演员、来源 ID 或存放位置，实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset = QPushButton('选中重置')
        self.btn_reset.clicked.connect(self.reset_selected_rows)

        self.btn_refresh = QPushButton('刷新数据')
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选：'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset)
        top_layout.addWidget(self.btn_refresh)

        self.summary_label = QLabel('已补全数: 0 | 未补全数: 0 | 视频总数: 0')
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels(
            [
                '视频编号',
                '视频标题',
                '作者/演员',
                '时长',
                '大小(GB)',
                '存放位置',
                '天限阁 ID',
                '辛聚谷 ID',
                '发行日期',
                '制作商',
                '发行商',
                '补全状态',
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        search_text = self.search_input.text().strip()

        def task():
            rows = self.backend_client.list_videos(search_text)
            return {
                'rows': rows,
                'search_text': search_text,
            }

        self._start_background_task(task, self._on_load_data_finished, '读取失败')

    def refresh_summary(self):
        summary = self._build_summary_from_rows(self.rows)
        self.summary_label.setText(
            '已补全数: {enriched_count} | 未补全数: {unenriched_count} | 视频总数: {total_count}'.format(
                enriched_count=summary.get('enriched_count', 0),
                unenriched_count=summary.get('unenriched_count', 0),
                total_count=summary.get('total_count', 0),
            )
        )

    @staticmethod
    def _build_summary_from_rows(rows):
        total_count = len(rows)
        enriched_count = sum(1 for row in rows if '已补全' in str(row.get('enrichment_status', '') or ''))
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def render_rows(self, rows):
        self.table.setRowCount(0)
        fields = (
            'code',
            'title',
            'author',
            'duration',
            'size',
            'storage_location',
            'avfan_movie_id',
            'javtxt_movie_id',
            'release_date',
            'maker',
            'publisher',
            'enrichment_status',
        )

        centered_columns = {0, 3, 4, 5, 6, 7, 8, 9, 10, 11}
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def filter_data(self, text):
        if self.task_thread is not None:
            return

        search_text = (text or '').strip()
        if not search_text:
            self.load_data()
            return

        try:
            self.rows = self.backend_client.list_videos(search_text)
            self.render_rows(self.rows)
            self.refresh_summary()
        except Exception as exc:
            print(f'筛选视频库失败: {exc}')

    def reset_selected_rows(self):
        codes = self.selected_codes()
        if not codes:
            QMessageBox.information(self, '未选择', '请先选中要重置的视频行。')
            return

        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(codes)} 个视频补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()

        def task():
            reset_count = self.backend_client.reset_video_enrichments(codes)
            rows = self.backend_client.list_videos(search_text)
            return {
                'reset_count': reset_count,
                'rows': rows,
                'search_text': search_text,
            }

        self._start_background_task(task, self._on_reset_finished, '重置失败')

    def selected_codes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        codes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                codes.append(item.text().strip())
        return codes

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
        rows = list((result or {}).get('rows', []) or [])
        search_text = str((result or {}).get('search_text', '') or '').strip()
        if not search_text:
            self.all_rows = list(rows)
        self.rows = rows
        self.render_rows(self.rows)
        self.refresh_summary()

    def _on_reset_finished(self, result):
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        self._on_load_data_finished(result)
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个视频的补全状态。')

    def closeEvent(self, event):
        if self.task_thread and self.task_thread.isRunning():
            QMessageBox.information(self, '操作进行中', '请等待当前操作完成后再关闭窗口。')
            event.ignore()
            return
        super().closeEvent(event)
