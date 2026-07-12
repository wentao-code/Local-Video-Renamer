from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.backend_task_worker import enable_minimize_button
from app.gui.task_queue import TASK_STATUS_COMPLETED, get_gui_task_queue


SUCCESS_ROW_COLOR = '#16a34a'
FAILED_ROW_COLOR = '#dc2626'


class TaskQueueViewerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        enable_minimize_button(self)
        self.setWindowTitle('任务列表')
        self.resize(980, 520)
        self.task_queue = get_gui_task_queue()

        layout = QVBoxLayout()
        self.summary_label = QLabel('')
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            '编号',
            '任务',
            '分类',
            '来源',
            '状态',
            '次数',
            '创建时间',
            '开始时间',
            '完成时间/错误',
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)

        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh_rows)
        self.task_queue.changed.connect(self.refresh_rows)
        self.refresh_timer.start()
        self.refresh_rows()

    def refresh_rows(self):
        records = self.task_queue.records()
        self.summary_label.setText(f'共 {len(records)} 个任务')
        if self.task_queue.is_all_done():
            self.summary_label.setStyleSheet('color: #16a34a; font-weight: 700;')
        else:
            self.summary_label.setStyleSheet('')
        self.table.setRowCount(0)
        for row, record in enumerate(records):
            self.table.insertRow(row)
            error_text = record.completed_at or ''
            if record.last_error:
                error_text = f'{error_text} | {record.last_error}' if error_text else record.last_error
            values = [
                record.task_id,
                record.title,
                getattr(record, 'task_category', ''),
                record.source,
                record.status,
                f'{record.attempts}/{record.max_attempts}',
                record.created_at,
                record.started_at,
                error_text,
            ]
            row_brush = self._row_foreground(record)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if row_brush is not None:
                    item.setForeground(row_brush)
                self.table.setItem(row, column, item)

    @staticmethod
    def _row_foreground(record):
        if bool(getattr(record, 'exhausted', False)):
            return QBrush(QColor(FAILED_ROW_COLOR))
        if getattr(record, 'status', '') == TASK_STATUS_COMPLETED:
            return QBrush(QColor(SUCCESS_ROW_COLOR))
        return None

    def closeEvent(self, event):
        self.refresh_timer.stop()
        super().closeEvent(event)
