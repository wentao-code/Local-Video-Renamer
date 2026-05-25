from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.services.video_category_service import VIDEO_CATEGORY_COLLECTION, VIDEO_CATEGORY_CO_STAR, VIDEO_CATEGORY_SINGLE


class VideoCategoryViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.category_groups = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('天机阁')
        self.resize(1200, 640)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.summary_label = QLabel('待手动分类视频: 0')
        self.btn_refresh = QPushButton('刷新数据')
        self.btn_refresh.clicked.connect(self.load_data)
        top_layout.addWidget(self.summary_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ['视频编号', '视频标题', '单体作品', '共演作品', '合集作品', '确认', '详情']
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for index in range(2, 7):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.set_async_busy_widgets([self.btn_refresh, self.table])

    def load_data(self):
        self.start_async_task(
            lambda: {'rows': self.backend_client.list_videos_requiring_manual_category()},
            self._on_load_data_finished,
            '读取失败',
        )

    def render_rows(self, rows):
        self.category_groups = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            code = str(row_data.get('code', '') or '').strip().upper()
            title = str(row_data.get('title', '') or '').strip()
            javtxt_url = str(row_data.get('javtxt_url', '') or '').strip()

            code_item = QTableWidgetItem(code)
            code_item.setTextAlignment(Qt.AlignCenter)
            title_item = QTableWidgetItem(title)
            self.table.setItem(row_idx, 0, code_item)
            self.table.setItem(row_idx, 1, title_item)

            group = QButtonGroup(self.table)
            group.setExclusive(True)
            self.category_groups[code] = group

            self.table.setCellWidget(row_idx, 2, self._build_category_radio(group, VIDEO_CATEGORY_SINGLE))
            self.table.setCellWidget(row_idx, 3, self._build_category_radio(group, VIDEO_CATEGORY_CO_STAR))
            self.table.setCellWidget(row_idx, 4, self._build_category_radio(group, VIDEO_CATEGORY_COLLECTION))
            self.table.setCellWidget(row_idx, 5, self._build_confirm_button(code))
            self.table.setCellWidget(row_idx, 6, self._build_detail_button(javtxt_url))

    def _build_category_radio(self, group, category):
        radio = QRadioButton()
        radio.setProperty('videoCategory', category)
        group.addButton(radio)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(radio)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def _build_confirm_button(self, code):
        button = QPushButton('确认')
        button.clicked.connect(lambda _checked=False, value=code: self.confirm_category(value))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def _build_detail_button(self, javtxt_url):
        button = QPushButton('详情')
        button.clicked.connect(lambda _checked=False, value=javtxt_url: self.open_detail_url(value))
        button.setEnabled(bool(javtxt_url))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def confirm_category(self, code):
        selected_category = self.selected_category(code)
        if not selected_category:
            QMessageBox.information(self, '未选择', '请先为当前视频选择作品类别。')
            return

        def task():
            self.backend_client.update_video_category(code, selected_category)
            return {
                'rows': self.backend_client.list_videos_requiring_manual_category(),
                'code': code,
                'category': selected_category,
            }

        self.start_async_task(task, self._on_update_category_finished, '保存失败')

    def selected_category(self, code):
        group = self.category_groups.get(str(code or '').strip().upper())
        if group is None:
            return ''
        checked_button = group.checkedButton()
        if checked_button is None:
            return ''
        return str(checked_button.property('videoCategory') or '').strip()

    def open_detail_url(self, javtxt_url):
        target_url = str(javtxt_url or '').strip()
        if not target_url:
            QMessageBox.information(self, '缺少链接', '当前视频还没有可打开的第二套系统详情链接。')
            return
        if not QDesktopServices.openUrl(QUrl(target_url)):
            QMessageBox.warning(self, '打开失败', f'无法打开链接：\n{target_url}')

    def _on_load_data_finished(self, result):
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)
        self.summary_label.setText(f'待手动分类视频: {len(self.rows)}')

    def _on_update_category_finished(self, result):
        self._on_load_data_finished(result)
