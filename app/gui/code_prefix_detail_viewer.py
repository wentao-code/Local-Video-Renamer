from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class CodePrefixDetailViewerWindow(QDialog):
    def __init__(self, backend_client, prefix, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'番号详情 - {self.prefix}')
        self.resize(1000, 780)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        summary_group = QGroupBox('基础信息')
        summary_form = QFormLayout()
        self.prefix_label = QLabel('')
        self.video_count_label = QLabel('')
        self.total_pages_label = QLabel('')
        self.total_videos_label = QLabel('')
        self.earliest_date_label = QLabel('')
        self.latest_date_label = QLabel('')
        self.last_enriched_label = QLabel('')
        for label in (
            self.prefix_label,
            self.video_count_label,
            self.total_pages_label,
            self.total_videos_label,
            self.earliest_date_label,
            self.latest_date_label,
            self.last_enriched_label,
        ):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        summary_form.addRow('番号：', self.prefix_label)
        summary_form.addRow('该番号视频数：', self.video_count_label)
        summary_form.addRow('AVFan总页数：', self.total_pages_label)
        summary_form.addRow('AVFan作品数：', self.total_videos_label)
        summary_form.addRow('最早发布时间：', self.earliest_date_label)
        summary_form.addRow('最新发布时间：', self.latest_date_label)
        summary_form.addRow('最近补全时间：', self.last_enriched_label)
        summary_group.setLayout(summary_form)

        self.year_table = QTableWidget()
        self.year_table.setColumnCount(2)
        self.year_table.setHorizontalHeaderLabels(['发布年份', '视频数量'])
        self.year_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.year_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.year_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.year_table.setSelectionBehavior(QTableWidget.SelectRows)

        self.actor_table = QTableWidget()
        self.actor_table.setColumnCount(2)
        self.actor_table.setHorizontalHeaderLabels(['主演演员', '视频数量'])
        self.actor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.actor_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.actor_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.actor_table.setSelectionBehavior(QTableWidget.SelectRows)

        self.movie_table = QTableWidget()
        self.movie_table.setColumnCount(4)
        self.movie_table.setHorizontalHeaderLabels(['编号', '标题', '演员名', '日期'])
        self.movie_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.movie_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.movie_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.movie_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.movie_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.movie_table.setSelectionBehavior(QTableWidget.SelectRows)

        year_group = QGroupBox('发布年份构成')
        year_layout = QVBoxLayout()
        year_layout.addWidget(self.year_table)
        year_group.setLayout(year_layout)

        actor_group = QGroupBox('主演演员前十名')
        actor_layout = QVBoxLayout()
        actor_layout.addWidget(self.actor_table)
        actor_group.setLayout(actor_layout)

        movie_group = QGroupBox('作品明细')
        movie_layout = QVBoxLayout()
        movie_layout.addWidget(self.movie_table)
        movie_group.setLayout(movie_layout)

        layout.addWidget(summary_group)
        layout.addWidget(year_group)
        layout.addWidget(actor_group)
        layout.addWidget(movie_group)
        self.setLayout(layout)

    def load_data(self):
        try:
            self.detail = self.backend_client.get_code_prefix_detail(self.prefix)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取番号详情失败：\n{str(exc)}')
            self.reject()
            return

        self.prefix_label.setText(self.detail.get('prefix', ''))
        self.video_count_label.setText(str(self.detail.get('video_count', 0)))
        self.total_pages_label.setText(str(self.detail.get('avfan_total_pages', 0)))
        self.total_videos_label.setText(str(self.detail.get('avfan_total_videos', 0)))
        self.earliest_date_label.setText(self.detail.get('earliest_release_date', '') or '暂无')
        self.latest_date_label.setText(self.detail.get('latest_release_date', '') or '暂无')
        self.last_enriched_label.setText(self.detail.get('last_enriched_at', '') or '暂无')

        self.render_rows(self.year_table, self.detail.get('year_distribution', []), ('year', 'video_count'))
        self.render_rows(self.actor_table, self.detail.get('top_actors', []), ('name', 'video_count'))
        self.render_rows(self.movie_table, self.detail.get('movies', []), ('code', 'title', 'author', 'release_date'))

    def render_rows(self, table, rows, fields):
        table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if field != 'title':
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)
