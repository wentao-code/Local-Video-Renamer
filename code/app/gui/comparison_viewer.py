from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.query_context import EntityType


class ComparisonWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, first, second, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.first = first
        self.second = second
        self._init_async_task_host()
        self._init_ui()

    def set_entities(self, first, second):
        if first.entity_type != second.entity_type:
            raise ValueError('对比对象类型必须一致')
        self.first = first
        self.second = second
        self.setWindowTitle(
            f'数据对比 - {self.first.display_name or self.first.entity_key} / '
            f'{self.second.display_name or self.second.entity_key}'
        )
        self.table.setHorizontalHeaderLabels([
            '项目',
            self.first.display_name or self.first.entity_key,
            self.second.display_name or self.second.entity_key,
        ])
        self.load_data()

    def _init_ui(self):
        self.setWindowTitle(f'数据对比 - {self.first.display_name or self.first.entity_key} / {self.second.display_name or self.second.entity_key}')
        self.resize(860, 620)
        self.setWindowModality(Qt.NonModal)
        layout = QVBoxLayout(self)
        self.status_label = QLabel('正在读取…')
        self.btn_refresh = QPushButton('刷新')
        self.btn_refresh.clicked.connect(self.load_data)
        top = QGridLayout()
        top.addWidget(self.status_label, 0, 0)
        top.addWidget(self.btn_refresh, 0, 1)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['项目', self.first.display_name or self.first.entity_key, self.second.display_name or self.second.entity_key])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        self.set_async_busy_widgets([self.btn_refresh])

    def load_data(self):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: {
                'first': self._load_reference(self.first),
                'second': self._load_reference(self.second),
            },
            self._on_loaded,
            '对比数据读取失败',
            block_ui=False,
            show_in_task_queue=False,
            task_title='数据对比 读取数据',
        )

    def _load_reference(self, reference):
        if reference.entity_type == EntityType.ACTOR:
            return self.backend_client.get_actor_detail(reference.entity_key)
        if reference.entity_type == EntityType.CODE_PREFIX:
            return self.backend_client.get_code_prefix_detail(reference.entity_key)
        raise ValueError('当前只支持演员和番号前缀对比')

    def _on_loaded(self, result):
        first = dict(result.get('first') or {})
        second = dict(result.get('second') or {})
        self.table.setRowCount(0)
        keys = ('name', 'birthday', 'age', 'movie_count', 'ladder_tier', 'matched', 'video_count')
        labels = {
            'name': '名称',
            'birthday': '生日',
            'age': '年龄',
            'movie_count': '作品数',
            'ladder_tier': '天梯等级',
            'matched': '匹配状态',
            'video_count': '视频数',
        }
        for key in keys:
            if key not in first and key not in second:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(labels[key]))
            self.table.setItem(row, 1, QTableWidgetItem(self._display_value(first.get(key))))
            self.table.setItem(row, 2, QTableWidgetItem(self._display_value(second.get(key))))
        self.status_label.setText('读取完成')

    @staticmethod
    def _display_value(value):
        if isinstance(value, bool):
            return '是' if value else '否'
        if isinstance(value, (dict, list)):
            return str(value)
        return str(value or '')
