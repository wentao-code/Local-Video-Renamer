from PyQt5.QtWidgets import QDialog, QGroupBox, QMessageBox, QScrollArea, QVBoxLayout

from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary


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
        self.resize(980, 760)

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
        self.basic_grid.set_items([
            ('name', '姓名：', ''),
            ('age', '年龄：', ''),
            ('birthday', '出生日期：', ''),
            ('local_total', '本地视频总数：', ''),
        ])
        basic_layout.addWidget(self.basic_grid)

        local_group = QGroupBox('本地视频统计')
        local_layout = QVBoxLayout(local_group)
        self.local_grid = DetailSummaryGrid(columns=1)
        self.local_grid.set_items([
            ('local_prefix', '番号分布：', ''),
            ('local_year', '年份构成：', ''),
        ])
        local_layout.addWidget(self.local_grid)

        web_group = QGroupBox('网页作品统计')
        web_layout = QVBoxLayout(web_group)
        self.web_grid = DetailSummaryGrid(columns=2)
        self.web_grid.set_items([
            ('web_status', '补全状态：', ''),
            ('web_total', '网页作品总数：', ''),
            ('web_pages', '网页总页数：', ''),
            ('web_earliest', '最早发布时间：', ''),
            ('web_latest', '最新发布时间：', ''),
            ('web_last_enriched', '最近补全时间：', ''),
            ('web_prefix', '网页番号分布：', ''),
            ('web_year', '网页年份构成：', ''),
        ])
        web_layout.addWidget(self.web_grid)

        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addStretch()

    def load_data(self):
        try:
            self.detail = self.backend_client.get_actor_detail(self.actor_name)
        except Exception as exc:
            QMessageBox.critical(self, '读取失败', f'读取演员详情失败：\n{str(exc)}')
            self.reject()
            return

        self.basic_grid.set_value('name', self.detail.get('name', ''))
        self.basic_grid.set_value('age', self.detail.get('age', '') or '暂无')
        self.basic_grid.set_value('birthday', self.detail.get('birthday', '') or '暂无')
        self.basic_grid.set_value('local_total', str(self.detail.get('local_video_count', 0)))

        self.local_grid.set_value(
            'local_prefix',
            format_distribution_summary(
                self.detail.get('local_prefix_distribution', []),
                'prefix',
                items_per_line=3,
            ),
        )
        self.local_grid.set_value(
            'local_year',
            format_distribution_summary(
                self.detail.get('local_year_distribution', []),
                'year',
                items_per_line=3,
            ),
        )

        self.web_grid.set_value('web_status', self.detail.get('web_enrichment_status', '') or '未补全')
        self.web_grid.set_value('web_total', str(self.detail.get('web_total_videos', 0)))
        self.web_grid.set_value('web_pages', str(self.detail.get('web_total_pages', 0)))
        self.web_grid.set_value('web_earliest', self.detail.get('web_earliest_release_date', '') or '暂无')
        self.web_grid.set_value('web_latest', self.detail.get('web_latest_release_date', '') or '暂无')
        self.web_grid.set_value('web_last_enriched', self.detail.get('web_last_enriched_at', '') or '暂无')
        self.web_grid.set_value(
            'web_prefix',
            format_distribution_summary(
                self.detail.get('web_prefix_distribution', []),
                'prefix',
                items_per_line=3,
            ),
        )
        self.web_grid.set_value(
            'web_year',
            format_distribution_summary(
                self.detail.get('web_year_distribution', []),
                'year',
                items_per_line=3,
            ),
        )
