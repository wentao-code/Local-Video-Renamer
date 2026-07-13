from uuid import uuid4

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.query_context import EntityReference, EntityType, QueryContext
from app.gui.query_history import QueryHistoryStore


ENTITY_LABELS = {
    EntityType.VIDEO: '视频',
    EntityType.ACTOR: '演员',
    EntityType.CODE_PREFIX: '番号前缀',
    EntityType.LADDER: '天梯榜',
    EntityType.MASTERPIECE: '名作堂',
}


class UnifiedSearchWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, coordinator, parent=None, history_store=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.coordinator = coordinator
        self.history_store = history_store or QueryHistoryStore()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._start_search)
        self._requested_query = ''
        self._request_token = ''
        self._active_request_token = ''
        self._init_async_task_host()
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle('统一查询中心')
        self.resize(900, 620)
        self.setWindowModality(Qt.NonModal)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('搜索视频、演员、番号、天梯榜或名作堂')
        self.search_input.textChanged.connect(self._on_query_changed)
        self.search_input.returnPressed.connect(self._start_search)
        self.btn_search = QPushButton('查询')
        self.btn_search.clicked.connect(self._start_search)
        self.btn_clear = QPushButton('清空')
        self.btn_clear.clicked.connect(self._clear_search)
        self.btn_compare = QPushButton('对比选中')
        self.btn_compare.clicked.connect(self._compare_selected)
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.btn_search)
        toolbar.addWidget(self.btn_clear)
        toolbar.addWidget(self.btn_compare)

        self.status_label = QLabel('输入关键词开始查询')
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['类型', '名称', '关联信息'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._open_row)

        layout.addLayout(toolbar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        self.set_async_busy_widgets([self.search_input, self.btn_search, self.btn_clear, self.btn_compare])

    def _on_query_changed(self, text):
        self._requested_query = str(text or '').strip()
        self._search_timer.start()

    def _clear_search(self):
        self.search_input.clear()
        self.table.setRowCount(0)
        self.status_label.setText('输入关键词开始查询')

    def _start_search(self):
        self._search_timer.stop()
        query = str(self.search_input.text() or '').strip()
        self._requested_query = query
        if not query:
            self._clear_search()
            return
        if self.is_async_task_running():
            self.status_label.setText('正在读取，查询完成后将加载最新关键词')
            return

        token = uuid4().hex
        self._request_token = token
        self._active_request_token = token
        self.status_label.setText(f'正在查询“{query}”…')
        self.start_async_task(
            lambda: {'token': token, 'payload': self.backend_client.search_all(query, limit=20)},
            self._on_search_finished,
            '统一查询失败',
            block_ui=False,
            show_in_task_queue=False,
            task_title='统一查询 读取数据',
        )

    def _on_search_finished(self, result):
        result = dict(result or {})
        if result.get('token') != self._request_token:
            self._start_search()
            return
        payload = dict(result.get('payload') or {})
        rows = list(payload.get('results', []) or [])
        self.table.setRowCount(0)
        for row in rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            entity_type = str(row.get('entity_type') or '')
            self.table.setItem(row_index, 0, QTableWidgetItem(ENTITY_LABELS.get(entity_type, entity_type)))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(row.get('display_name') or row.get('entity_key') or '')))
            self.table.setItem(row_index, 2, QTableWidgetItem(str(row.get('secondary_text') or '')))
            self.table.item(row_index, 0).setData(Qt.UserRole, row)
        self.status_label.setText(f'找到 {len(rows)} 条结果')
        self.history_store.record_search(payload.get('query', ''))
        if self._requested_query != payload.get('query', ''):
            self._start_search()

    def _open_row(self, row_index, _column):
        item = self.table.item(row_index, 0)
        row = item.data(Qt.UserRole) if item is not None else None
        if not isinstance(row, dict):
            return
        reference = self._reference_from_row(row)
        if reference is None:
            QMessageBox.information(self, '无法打开', '该结果缺少可定位的对象信息。')
            return
        self.coordinator.open_entity(
            reference,
            QueryContext(search_text=self.search_input.text(), source='unified_search', entity=reference),
        )
        self.history_store.record_entity(reference)

    def _compare_selected(self):
        rows = []
        for item in self.table.selectedItems():
            row = self.table.item(item.row(), 0).data(Qt.UserRole)
            if row not in rows:
                rows.append(row)
        references = [self._reference_from_row(row) for row in rows]
        references = [reference for reference in references if reference is not None]
        if len(references) != 2 or references[0].entity_type not in (EntityType.ACTOR, EntityType.CODE_PREFIX):
            self.status_label.setText('请选择同类型的两名演员或两个番号前缀进行对比')
            return
        self.coordinator.compare_entities(references[0], references[1])

    @staticmethod
    def _reference_from_row(row):
        entity_type = str(row.get('entity_type') or '')
        metadata = dict(row.get('metadata') or {})
        if entity_type == EntityType.LADDER:
            entity_type = str(metadata.get('entity_type') or '')
            entity_key = str(metadata.get('entity_name') or '')
        else:
            entity_key = str(row.get('entity_key') or '')
        if entity_type not in EntityType.ALL or not entity_key:
            return None
        return EntityReference(
            entity_type=entity_type,
            entity_key=entity_key,
            display_name=str(row.get('display_name') or entity_key),
            secondary_text=str(row.get('secondary_text') or ''),
            source=str(row.get('source') or ''),
        )

    def closeEvent(self, event):
        if self.block_close_while_async_running(event):
            return
        super().closeEvent(event)
