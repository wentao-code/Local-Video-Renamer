from PyQt5.QtCore import Qt
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

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.gui.backend_task_worker import AsyncTaskHostMixin


class DatabaseViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('视频库')
        self.resize(1440, 720)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入视频编号、标题、演员、分类或补全状态实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset_avfan = QPushButton('天陨重置')
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton('辛聚重置')
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton('刷新数据')
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选：'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_refresh)

        self.summary_label = QLabel('已补全数: 0 | 未补全数: 0 | 视频总数: 0')
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels(
            [
                '视频编号',
                '视频标题',
                '作者/演员',
                '视频分类',
                '时长',
                '大小(GB)',
                '存放位置',
                '天陨ID',
                '辛聚ID',
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
        self.table.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [self.search_input, self.btn_reset_avfan, self.btn_reset_javtxt, self.btn_refresh, self.table]
        )

    def load_data(self):
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'rows': self.backend_client.list_videos(search_text),
            },
            self._on_load_data_finished,
            '读取失败',
        )

    def render_rows(self, rows):
        self.table.setRowCount(0)
        fields = (
            'code',
            'title',
            'author',
            'video_category',
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
        centered_columns = {0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def refresh_summary(self):
        total_count = len(self.rows)
        enriched_count = sum(1 for row in self.rows if '已补全' in str(row.get('enrichment_status', '') or ''))
        unenriched_count = max(total_count - enriched_count, 0)
        self.summary_label.setText(
            f'已补全数: {enriched_count} | 未补全数: {unenriched_count} | 视频总数: {total_count}'
        )

    def filter_data(self, text):
        if self.is_async_task_running():
            return
        if not str(text or '').strip():
            self.load_data()
            return

        try:
            self.rows = self.backend_client.list_videos(str(text or '').strip())
            self.render_rows(self.rows)
            self.refresh_summary()
        except Exception as exc:
            print(f'筛选视频库失败: {exc}')

    def reset_selected_rows(self, source_key):
        codes = self.selected_codes()
        if not codes:
            QMessageBox.information(self, '未选择', '请先选中要重置的视频行。')
            return

        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(codes)} 个视频的{source_label}补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_video_enrichments(codes, source_key=source_key),
                'rows': self.backend_client.list_videos(search_text),
                'source_label': source_label,
            },
            self._on_reset_finished,
            '重置失败',
        )

    def selected_codes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        codes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                codes.append(item.text().strip())
        return codes

    def _on_load_data_finished(self, result):
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)
        self.refresh_summary()

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or '所选来源')
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个视频的{source_label}补全状态。')
