from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.query_context import EntityReference, EntityType, QueryContext


class DataDashboardWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None, coordinator=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.coordinator = coordinator
        self.metric_buttons = []
        self.metric_windows = []
        self._init_async_task_host()
        self._init_ui()
        self.load_data()

    def _init_ui(self):
        self.setWindowTitle('数据看板')
        self.resize(1020, 720)
        self.setMinimumSize(820, 560)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        top_layout = QHBoxLayout()
        self.refreshed_label = QLabel('最后刷新：暂无')
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.refreshed_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(top_layout)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget(self.scroll_area)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self.scroll_area.setWidget(self.content_widget)
        root_layout.addWidget(self.scroll_area)
        self.set_async_busy_widgets([self.btn_refresh, self.scroll_area])

    def load_data(self, force_refresh=False):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: self.backend_client.get_data_dashboard(force_refresh=force_refresh),
            self._render_dashboard,
            '读取数据看板失败',
            task_title='数据看板 刷新',
        )

    def _render_dashboard(self, dashboard):
        payload = dict(dashboard or {})
        refreshed_at = str(payload.get('refreshed_at', '') or '').strip() or '暂无'
        self.refreshed_label.setText(f'最后刷新：{refreshed_at}')
        self._clear_content()
        self.metric_buttons = []

        for section in payload.get('sections', []) or []:
            group = QGroupBox(str(section.get('title', '') or ''))
            grid = QGridLayout(group)
            grid.setContentsMargins(10, 14, 10, 10)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            for index, metric in enumerate(section.get('metrics', []) or []):
                metric_data = dict(metric or {})
                button = QPushButton(
                    '{}\n{}'.format(
                        str(metric_data.get('title', '') or ''),
                        str(metric_data.get('value', '') or '暂无'),
                    )
                )
                button.setMinimumSize(170, 68)
                button.setEnabled(bool(metric_data.get('clickable', False)))
                button.setStyleSheet(
                    'QPushButton { text-align: center; padding: 8px; }'
                    'QPushButton:disabled { color: #666666; }'
                )
                button.clicked.connect(
                    lambda _checked=False, item=metric_data: self.open_metric_items(item)
                )
                grid.addWidget(button, index // 4, index % 4)
                self.metric_buttons.append(button)
            self.content_layout.addWidget(group)
        self.content_layout.addStretch()

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def open_metric_items(self, metric):
        metric_data = dict(metric or {})
        metric_key = str(metric_data.get('key', '') or '').strip()
        if not metric_key:
            return
        for existing in self.metric_windows:
            if str(getattr(existing, 'metric_key', '') or '').strip() == metric_key:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
        window = DashboardMetricItemsWindow(
            self.backend_client,
            metric_key,
            str(metric_data.get('title', '') or ''),
            self,
            coordinator=self.coordinator,
        )
        self.metric_windows.append(window)
        window.finished.connect(
            lambda _result, current=window: self._forget_metric_window(current)
        )
        window.show()

    def _forget_metric_window(self, window):
        self.metric_windows = [item for item in self.metric_windows if item is not window]


class DashboardMetricItemsWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, metric_key, metric_title, parent=None, coordinator=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.metric_key = str(metric_key or '').strip()
        self.metric_title = str(metric_title or '').strip()
        self.coordinator = coordinator
        self.items = []
        self._init_async_task_host()
        self._init_ui()
        self.load_data()

    def _init_ui(self):
        self.setWindowTitle(f'数据看板 - {self.metric_title}')
        self.resize(900, 620)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        top_layout = QHBoxLayout()
        self.count_label = QLabel('共 0 条')
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_data)
        top_layout.addWidget(self.count_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)
        root_layout.addLayout(top_layout)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(['类型', '名称/编号', '标题', '演员/分类', '指标值', '操作'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        root_layout.addWidget(self.table)
        self.set_async_busy_widgets([self.btn_refresh, self.table])

    def load_data(self):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: self.backend_client.get_data_dashboard_items(self.metric_key),
            self._render_items,
            '读取指标明细失败',
            task_title=f'数据看板 {self.metric_title}明细',
        )

    def _render_items(self, items):
        self.items = [dict(item or {}) for item in items or []]
        self.count_label.setText(f'共 {len(self.items)} 条')
        self.table.setRowCount(len(self.items))
        for row_index, item in enumerate(self.items):
            entity_type = str(item.get('entity_type', '') or '').strip()
            type_label = {'actor': '演员', 'code_prefix': '番号', 'video': '视频'}.get(entity_type, '')
            author_category = str(item.get('author', '') or '').strip()
            category = str(item.get('category', '') or '').strip()
            if category:
                author_category = f'{author_category} / {category}' if author_category else category
            values = (
                type_label,
                str(item.get('name', '') or item.get('key', '') or ''),
                str(item.get('title', '') or ''),
                author_category,
                str(item.get('value', '') or ''),
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
            detail_button = QPushButton('详情')
            detail_button.setEnabled(self.coordinator is not None and bool(item.get('key')))
            detail_button.clicked.connect(
                lambda _checked=False, current=dict(item): self.open_item_detail(current)
            )
            self.table.setCellWidget(row_index, 5, detail_button)
        self.table.resizeRowsToContents()

    def open_item_detail(self, item):
        if self.coordinator is None:
            return
        entity_type = str(item.get('entity_type', '') or '').strip()
        entity_key = str(item.get('key', '') or '').strip()
        type_map = {
            'actor': EntityType.ACTOR,
            'code_prefix': EntityType.CODE_PREFIX,
            'video': EntityType.VIDEO,
        }
        target_type = type_map.get(entity_type)
        if target_type is None or not entity_key:
            return
        reference = EntityReference(target_type, entity_key, display_name=entity_key)
        self.coordinator.open_entity(
            reference,
            QueryContext(source='data_dashboard', entity=reference),
        )
