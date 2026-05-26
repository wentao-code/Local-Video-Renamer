from PyQt5.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary
from app.gui.video_list_detail_viewer import VideoListDetailWindow


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
        self.resize(1380, 980)

        root_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QGroupBox()
        content.setStyleSheet('QGroupBox { border: 0; margin-top: 0; }')
        scroll_area.setWidget(content)

        layout = QVBoxLayout(content)

        basic_group = QGroupBox('基础信息')
        basic_layout = QVBoxLayout(basic_group)
        self.basic_grid = DetailSummaryGrid(columns=2)
        self.basic_grid.set_items(
            [
                ('name', '姓名：', ''),
                ('actor_id', '作者 ID：', ''),
                ('age', '年龄：', ''),
                ('birthday', '生日：', ''),
                ('local_total', '本地视频总数：', ''),
            ]
        )
        basic_layout.addWidget(self.basic_grid)

        local_group = QGroupBox('本地视频统计')
        local_layout = QVBoxLayout(local_group)
        self.local_grid = DetailSummaryGrid(columns=1)
        self.local_grid.set_items([('local_prefix', '番号分布：', ''), ('local_year', '年份分布：', '')])
        local_layout.addWidget(self.local_grid)

        web_group = QGroupBox('网页作品统计')
        web_layout = QVBoxLayout(web_group)
        self.web_grid = DetailSummaryGrid(columns=2)
        self.web_grid.set_items(
            [
                ('web_status', '补全状态：', ''),
                ('web_total', '网页作品总数：', ''),
                ('web_pages', '网页总页数：', ''),
                ('eligible_video_count', '满足要求视频数：', ''),
                ('web_earliest', '最早发布日期：', ''),
                ('web_latest', '最晚发布日期：', ''),
                ('eligible_enriched_video_count', '已补全满足要求视频数：', ''),
                ('web_last_enriched', '最近补全时间：', ''),
                ('web_prefix', '网页番号分布：', ''),
                ('web_year', '网页年份分布：', ''),
            ]
        )
        web_layout.addWidget(self.web_grid)

        local_movie_group = QGroupBox('本地视频明细')
        local_movie_layout = QVBoxLayout(local_movie_group)
        self.local_movie_count_label = QLabel('当前演员的本地视频共 0 条')
        self.btn_local_movie_detail = QPushButton('详情')
        self.btn_local_movie_detail.clicked.connect(self.show_local_movie_detail)
        local_movie_top_layout = QHBoxLayout()
        local_movie_top_layout.addWidget(self.local_movie_count_label)
        local_movie_top_layout.addStretch()
        local_movie_top_layout.addWidget(self.btn_local_movie_detail)
        local_movie_layout.addLayout(local_movie_top_layout)

        web_movie_group = QGroupBox('网页作品明细')
        web_movie_layout = QVBoxLayout(web_movie_group)
        self.web_movie_count_label = QLabel('当前演员的网页作品共 0 条')
        self.btn_web_movie_detail = QPushButton('详情')
        self.btn_web_movie_detail.clicked.connect(self.show_web_movie_detail)
        web_movie_top_layout = QHBoxLayout()
        web_movie_top_layout.addWidget(self.web_movie_count_label)
        web_movie_top_layout.addStretch()
        web_movie_top_layout.addWidget(self.btn_web_movie_detail)
        web_movie_layout.addLayout(web_movie_top_layout)

        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addWidget(local_movie_group)
        layout.addWidget(web_movie_group)
        layout.addStretch()

    def load_data(self):
        try:
            self.detail = self.backend_client.get_actor_detail(self.actor_name)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取演员详情失败：\n{exc}')
            self.reject()
            return

        self.basic_grid.set_value('name', self.detail.get('name', ''))
        self.basic_grid.set_value('actor_id', self.detail.get('actor_id', '') or '暂无')
        self.basic_grid.set_value('age', self.detail.get('age', '') or '暂无')
        self.basic_grid.set_value('birthday', self.detail.get('birthday', '') or '暂无')
        self.basic_grid.set_value('local_total', str(self.detail.get('local_video_count', 0)))

        self.local_grid.set_value(
            'local_prefix',
            format_distribution_summary(self.detail.get('local_prefix_distribution', []), 'prefix', items_per_line=3),
        )
        self.local_grid.set_value(
            'local_year',
            format_distribution_summary(self.detail.get('local_year_distribution', []), 'year', items_per_line=3),
        )

        self.web_grid.set_value('web_status', self.detail.get('web_enrichment_status', '') or '未补全')
        self.web_grid.set_value('web_total', str(self.detail.get('web_total_videos', 0)))
        self.web_grid.set_value('web_pages', str(self.detail.get('web_total_pages', 0)))
        self.web_grid.set_value('eligible_video_count', str(self.detail.get('eligible_video_count', 0)))
        self.web_grid.set_value('web_earliest', self.detail.get('web_earliest_release_date', '') or '暂无')
        self.web_grid.set_value('web_latest', self.detail.get('web_latest_release_date', '') or '暂无')
        self.web_grid.set_value(
            'eligible_enriched_video_count',
            str(self.detail.get('eligible_enriched_video_count', 0)),
        )
        self.web_grid.set_value('web_last_enriched', self.detail.get('web_last_enriched_at', '') or '暂无')
        self.web_grid.set_value(
            'web_prefix',
            format_distribution_summary(self.detail.get('web_prefix_distribution', []), 'prefix', items_per_line=3),
        )
        self.web_grid.set_value(
            'web_year',
            format_distribution_summary(self.detail.get('web_year_distribution', []), 'year', items_per_line=3),
        )

        local_rows = list(self.detail.get('local_videos', []) or [])
        web_rows = list(self.detail.get('web_movies', []) or [])
        self.local_movie_count_label.setText(f'当前演员的本地视频共 {len(local_rows)} 条')
        self.web_movie_count_label.setText(f'当前演员的网页作品共 {len(web_rows)} 条')
        self.btn_local_movie_detail.setEnabled(bool(local_rows))
        self.btn_web_movie_detail.setEnabled(bool(web_rows))

    def show_local_movie_detail(self):
        rows = list(self.detail.get('local_videos', []) or [])
        if not rows:
            QMessageBox.information(self, '暂无数据', '当前演员还没有可显示的本地视频明细。')
            return
        viewer = VideoListDetailWindow(
            title=f'本地视频详情 - {self.actor_name}',
            table_title=f'{self.actor_name} 的本地视频',
            rows=rows,
            parent=self,
        )
        viewer.exec_()

    def show_web_movie_detail(self):
        rows = list(self.detail.get('web_movies', []) or [])
        if not rows:
            QMessageBox.information(self, '暂无数据', '当前演员还没有可显示的网页作品明细。')
            return
        viewer = VideoListDetailWindow(
            title=f'网页作品详情 - {self.actor_name}',
            table_title=f'{self.actor_name} 的网页作品',
            rows=rows,
            parent=self,
        )
        viewer.exec_()
