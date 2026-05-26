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
        self.resize(1380, 920)

        root_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        content = QGroupBox()
        content.setStyleSheet('QGroupBox { border: 0; margin-top: 0; }')
        scroll_area.setWidget(content)

        layout = QVBoxLayout(content)

        summary_group = QGroupBox('基础信息')
        summary_layout = QVBoxLayout(summary_group)
        self.summary_grid = DetailSummaryGrid(columns=2)
        self.summary_grid.set_items(
            [
                ('prefix', '番号：', ''),
                ('video_count', '本地视频数：', ''),
                ('total_pages', 'AVFan 总页数：', ''),
                ('total_videos', 'AVFan 作品数：', ''),
                ('eligible_video_count', '满足要求视频数：', ''),
                ('eligible_enriched_video_count', '已补全满足要求视频数：', ''),
                ('earliest_date', '最早发布日期：', ''),
                ('latest_date', '最晚发布日期：', ''),
                ('last_enriched', '最近补全时间：', ''),
            ]
        )
        summary_layout.addWidget(self.summary_grid)

        stats_group = QGroupBox('摘要统计')
        stats_layout = QVBoxLayout(stats_group)
        self.stats_grid = DetailSummaryGrid(columns=1)
        self.stats_grid.set_items(
            [
                ('year_distribution', '年份分布：', ''),
                ('top_actors', '主演演员前十：', ''),
            ]
        )
        stats_layout.addWidget(self.stats_grid)

        movie_group = QGroupBox('网页作品明细')
        movie_layout = QVBoxLayout(movie_group)
        self.movie_count_label = QLabel('当前番号下的网页作品共 0 条')
        self.btn_movie_detail = QPushButton('详情')
        self.btn_movie_detail.clicked.connect(self.show_movie_detail)
        movie_top_layout = QHBoxLayout()
        movie_top_layout.addWidget(self.movie_count_label)
        movie_top_layout.addStretch()
        movie_top_layout.addWidget(self.btn_movie_detail)
        movie_layout.addLayout(movie_top_layout)

        layout.addWidget(summary_group)
        layout.addWidget(stats_group)
        layout.addWidget(movie_group)
        layout.addStretch()

    def load_data(self):
        try:
            self.detail = self.backend_client.get_code_prefix_detail(self.prefix)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取番号详情失败：\n{exc}')
            self.reject()
            return

        self.summary_grid.set_value('prefix', self.detail.get('prefix', ''))
        self.summary_grid.set_value('video_count', str(self.detail.get('video_count', 0)))
        self.summary_grid.set_value('total_pages', str(self.detail.get('avfan_total_pages', 0)))
        self.summary_grid.set_value('total_videos', str(self.detail.get('avfan_total_videos', 0)))
        self.summary_grid.set_value('eligible_video_count', str(self.detail.get('eligible_video_count', 0)))
        self.summary_grid.set_value(
            'eligible_enriched_video_count',
            str(self.detail.get('eligible_enriched_video_count', 0)),
        )
        self.summary_grid.set_value('earliest_date', self.detail.get('earliest_release_date', '') or '暂无')
        self.summary_grid.set_value('latest_date', self.detail.get('latest_release_date', '') or '暂无')
        self.summary_grid.set_value('last_enriched', self.detail.get('last_enriched_at', '') or '暂无')
        self.stats_grid.set_value(
            'year_distribution',
            format_distribution_summary(self.detail.get('year_distribution', []), 'year', items_per_line=3),
        )
        self.stats_grid.set_value(
            'top_actors',
            format_distribution_summary(self.detail.get('top_actors', []), 'name', items_per_line=2),
        )

        rows = list(self.detail.get('movies', []) or [])
        self.movie_count_label.setText(f'当前番号下的网页作品共 {len(rows)} 条')
        self.btn_movie_detail.setEnabled(bool(rows))

    def show_movie_detail(self):
        rows = list(self.detail.get('movies', []) or [])
        if not rows:
            QMessageBox.information(self, '暂无数据', '当前番号还没有可显示的网页作品明细。')
            return
        viewer = VideoListDetailWindow(
            title=f'网页作品详情 - {self.prefix}',
            table_title=f'{self.prefix} 的网页作品',
            rows=rows,
            parent=self,
        )
        viewer.exec_()
