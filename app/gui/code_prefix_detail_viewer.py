from PyQt5.QtWidgets import QDialog, QGroupBox, QScrollArea, QVBoxLayout

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary


class CodePrefixDetailViewerWindow(QDialog, AsyncTaskHostMixin):
    def __init__(self, backend_client, prefix, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'番号详情 - {self.prefix}')
        self.resize(1280, 760)

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
                ('video_count', '该番号视频数：', ''),
                ('total_pages', 'AVFan总页数：', ''),
                ('total_videos', 'AVFan作品数：', ''),
                ('eligible_video_count', '满足要求视频数量：', ''),
                ('eligible_enriched_video_count', '补全满足要求视频数量：', ''),
                ('earliest_date', '最早发布时间：', ''),
                ('latest_date', '最新发布时间：', ''),
                ('last_enriched', '最近补全时间：', ''),
            ]
        )
        summary_layout.addWidget(self.summary_grid)

        stats_group = QGroupBox('摘要统计')
        stats_layout = QVBoxLayout(stats_group)
        self.stats_grid = DetailSummaryGrid(columns=1)
        self.stats_grid.set_items(
            [
                ('year_distribution', '发布年份构成：', ''),
                ('top_actors', '主演演员前十名：', ''),
            ]
        )
        stats_layout.addWidget(self.stats_grid)

        layout.addWidget(summary_group)
        layout.addWidget(stats_group)
        layout.addStretch()

    def load_data(self):
        self.start_async_task(
            lambda: self.backend_client.get_code_prefix_detail(self.prefix),
            self._on_load_data_finished,
            '读取失败',
        )

    def _on_load_data_finished(self, detail):
        self.detail = dict(detail or {})
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

    def closeEvent(self, event):
        if self.block_close_while_async_running(event, '加载进行中', '请等待当前加载完成后再关闭窗口。'):
            return
        super().closeEvent(event)
