from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
)

from app.gui.backend_task_worker import enable_minimize_button
from app.gui.task_queue import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_DELETED,
    TASK_STATUS_PARTIAL,
    get_gui_task_queue,
)


SUCCESS_ROW_COLOR = '#16a34a'
FAILED_ROW_COLOR = '#dc2626'
PARTIAL_ROW_COLOR = '#b54708'


class TaskQueueViewerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.task_queue_owner = parent
        enable_minimize_button(self)
        self.setWindowTitle('任务列表')
        self.resize(980, 520)
        self.task_queue = get_gui_task_queue()
        self._selected_task_ids = set()

        layout = QVBoxLayout()
        self.summary_label = QLabel('')
        self.btn_delete_selected = QPushButton('删除选中任务')
        self.btn_delete_selected.setEnabled(False)
        self.btn_delete_selected.clicked.connect(self.delete_selected_tasks)
        self.table = QTableWidget()
        self.table.setColumnCount(15)
        self.table.setHorizontalHeaderLabels([
            '编号',
            '任务',
            '分类',
            '来源',
            '状态',
            '次数',
            '计划编号',
            '批次进度',
            '待处理',
            '成功',
            '失败',
            '创建时间',
            '开始时间',
            '完成时间/错误',
            '暂停原因',
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._update_delete_button)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        for column in range(6, 13):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(13, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(14, QHeaderView.Stretch)

        action_layout = QHBoxLayout()
        action_layout.addWidget(self.btn_delete_selected)
        action_layout.addStretch(1)
        layout.addWidget(self.summary_label)
        layout.addLayout(action_layout)
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
        selected_task_ids = set(self._selected_task_ids)
        self.summary_label.setText(f'共 {len(records)} 个任务')
        if any(getattr(record, 'status', '') == TASK_STATUS_PARTIAL for record in records):
            self.summary_label.setStyleSheet('color: #b54708; font-weight: 700;')
        elif self.task_queue.is_all_done():
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
                record.plan_id,
                f'{record.batch_current}/{record.batch_total}' if record.batch_total else '',
                record.plan_pending_count if record.plan_id else '',
                record.plan_success_count if record.plan_id else '',
                record.plan_failed_count if record.plan_id else '',
                record.created_at,
                record.started_at,
                error_text,
                record.pause_reason,
            ]
            row_brush = self._row_foreground(record)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if row_brush is not None:
                    item.setForeground(row_brush)
                self.table.setItem(row, column, item)
            if record.task_id in selected_task_ids:
                self.table.selectRow(row)
        self._update_delete_button()

    def _selected_records(self):
        records = self.task_queue.records()
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [records[row] for row in rows if 0 <= row < len(records)]

    def _update_delete_button(self):
        if self.table.rowCount():
            records = self.task_queue.records()
            self._selected_task_ids = {
                records[index.row()].task_id
                for index in self.table.selectionModel().selectedRows()
                if 0 <= index.row() < len(records)
            }
        eligible = [
            record for record in self._selected_records()
            if record.status not in {TASK_STATUS_COMPLETED, TASK_STATUS_PARTIAL, TASK_STATUS_DELETED}
        ]
        self.btn_delete_selected.setEnabled(bool(eligible))

    def confirm_delete(self, records):
        names = '\n'.join(
            f"- {record.title}"
            for record in records[:8]
        )
        if len(records) > 8:
            names += f'\n- 以及其他 {len(records) - 8} 个任务'
        answer = QMessageBox.question(
            self,
            '确认删除任务',
            f'删除后这些任务将不再执行：\n{names}',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def delete_selected_tasks(self):
        records = [
            record for record in self._selected_records()
            if record.status not in {TASK_STATUS_COMPLETED, TASK_STATUS_PARTIAL, TASK_STATUS_DELETED}
        ]
        if not records or not self.confirm_delete(records):
            return 0
        parent = self.task_queue_owner
        cancel_handler = getattr(parent, 'cancel_task_records', None)
        if callable(cancel_handler):
            count = int(cancel_handler(records) or 0)
        else:
            count = self.task_queue.cancel_tasks(
                [record.task_id for record in records],
                '用户删除任务',
            )
        self.refresh_rows()
        return count

    @staticmethod
    def _row_foreground(record):
        if bool(getattr(record, 'exhausted', False)):
            return QBrush(QColor(FAILED_ROW_COLOR))
        if getattr(record, 'status', '') == TASK_STATUS_PARTIAL:
            return QBrush(QColor(PARTIAL_ROW_COLOR))
        if getattr(record, 'status', '') == TASK_STATUS_COMPLETED:
            return QBrush(QColor(SUCCESS_ROW_COLOR))
        return None

    def closeEvent(self, event):
        self.refresh_timer.stop()
        super().closeEvent(event)
