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


class ActorDetailViewerWindow(QDialog):
    def __init__(self, backend_client, actor_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.actor_name = actor_name
        self.detail = {}
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'演员详情 - {self.actor_name}')
        self.resize(920, 760)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        basic_group = QGroupBox('基础信息')
        basic_form = QFormLayout()
        self.name_label = QLabel('')
        self.age_label = QLabel('')
        self.birthday_label = QLabel('')
        self.local_total_label = QLabel('')
        for label in (
            self.name_label,
            self.age_label,
            self.birthday_label,
            self.local_total_label,
        ):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
        basic_form.addRow('姓名：', self.name_label)
        basic_form.addRow('年龄：', self.age_label)
        basic_form.addRow('出生日期：', self.birthday_label)
        basic_form.addRow('本地视频总数：', self.local_total_label)
        basic_group.setLayout(basic_form)

        local_group = QGroupBox('本地视频统计')
        local_form = QFormLayout()
        self.local_prefix_label = self._build_multiline_label()
        self.local_year_label = self._build_multiline_label()
        local_form.addRow('番号分布：', self.local_prefix_label)
        local_form.addRow('年份构成：', self.local_year_label)
        local_group.setLayout(local_form)

        web_group = QGroupBox('网页作品统计')
        web_form = QFormLayout()
        self.web_status_label = QLabel('')
        self.web_total_label = QLabel('')
        self.web_pages_label = QLabel('')
        self.web_earliest_label = QLabel('')
        self.web_latest_label = QLabel('')
        self.web_last_enriched_label = QLabel('')
        self.web_prefix_label = self._build_multiline_label()
        self.web_year_label = self._build_multiline_label()
        for label in (
            self.web_status_label,
            self.web_total_label,
            self.web_pages_label,
            self.web_earliest_label,
            self.web_latest_label,
            self.web_last_enriched_label,
        ):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
        web_form.addRow('补全状态：', self.web_status_label)
        web_form.addRow('网页作品总数：', self.web_total_label)
        web_form.addRow('网页总页数：', self.web_pages_label)
        web_form.addRow('最早发布时间：', self.web_earliest_label)
        web_form.addRow('最新发布时间：', self.web_latest_label)
        web_form.addRow('最近补全时间：', self.web_last_enriched_label)
        web_form.addRow('网页番号分布：', self.web_prefix_label)
        web_form.addRow('网页年份构成：', self.web_year_label)
        web_group.setLayout(web_form)

        self.web_movie_table = QTableWidget()
        self.web_movie_table.setColumnCount(4)
        self.web_movie_table.setHorizontalHeaderLabels(['编号', '标题', '演员名', '日期'])
        self.web_movie_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.web_movie_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.web_movie_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.web_movie_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.web_movie_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.web_movie_table.setSelectionBehavior(QTableWidget.SelectRows)

        web_movie_group = QGroupBox('网页作品明细')
        web_movie_layout = QVBoxLayout()
        web_movie_layout.addWidget(self.web_movie_table)
        web_movie_group.setLayout(web_movie_layout)

        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addWidget(web_movie_group)
        self.setLayout(layout)

    def load_data(self):
        try:
            self.detail = self.backend_client.get_actor_detail(self.actor_name)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取演员详情失败：\n{str(exc)}')
            self.reject()
            return

        self.name_label.setText(self.detail.get('name', ''))
        self.age_label.setText(self.detail.get('age', '') or '暂无')
        self.birthday_label.setText(self.detail.get('birthday', '') or '暂无')
        self.local_total_label.setText(str(self.detail.get('local_video_count', 0)))

        self.local_prefix_label.setText(
            self.format_distribution(self.detail.get('local_prefix_distribution', []), 'prefix')
        )
        self.local_year_label.setText(
            self.format_distribution(self.detail.get('local_year_distribution', []), 'year')
        )

        self.web_status_label.setText(self.detail.get('web_enrichment_status', '') or '未补全')
        self.web_total_label.setText(str(self.detail.get('web_total_videos', 0)))
        self.web_pages_label.setText(str(self.detail.get('web_total_pages', 0)))
        self.web_earliest_label.setText(self.detail.get('web_earliest_release_date', '') or '暂无')
        self.web_latest_label.setText(self.detail.get('web_latest_release_date', '') or '暂无')
        self.web_last_enriched_label.setText(self.detail.get('web_last_enriched_at', '') or '暂无')
        self.web_prefix_label.setText(
            self.format_distribution(self.detail.get('web_prefix_distribution', []), 'prefix')
        )
        self.web_year_label.setText(
            self.format_distribution(self.detail.get('web_year_distribution', []), 'year')
        )

        self.render_web_movies(self.detail.get('web_movies', []))

    def render_web_movies(self, rows):
        self.web_movie_table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.web_movie_table.insertRow(row_idx)
            fields = ('code', 'title', 'author', 'release_date')
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if field != 'title':
                    item.setTextAlignment(Qt.AlignCenter)
                self.web_movie_table.setItem(row_idx, col_idx, item)

    @staticmethod
    def _build_multiline_label():
        label = QLabel('')
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    @staticmethod
    def format_distribution(rows, key_name):
        if not rows:
            return '暂无'
        return '\n'.join(
            f"{row.get(key_name, '未知')}: {row.get('video_count', 0)}"
            for row in rows
        )
