from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QDialog, QGroupBox, QMessageBox, QScrollArea, QVBoxLayout

from app.gui.backend_task_worker import BackendTaskWorker
from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary


class ActorDetailViewerWindow(QDialog):
    def __init__(self, backend_client, actor_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.actor_name = actor_name
        self.detail = {}
        self.task_thread = None
        self.task_worker = None
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'演员详情 - {self.actor_name}')
        self.resize(1280, 760)

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
                ('birthday', '出生日期：', ''),
                ('local_total', '本地视频总数：', ''),
            ]
        )
        basic_layout.addWidget(self.basic_grid)

        local_group = QGroupBox('本地视频统计')
        local_layout = QVBoxLayout(local_group)
        self.local_grid = DetailSummaryGrid(columns=1)
        self.local_grid.set_items(
            [
                ('local_prefix', '番号分布：', ''),
                ('local_year', '年份构成：', ''),
            ]
        )
        local_layout.addWidget(self.local_grid)

        web_group = QGroupBox('网页作品统计')
        web_layout = QVBoxLayout(web_group)
        self.web_grid = DetailSummaryGrid(columns=2)
        self.web_grid.set_items(
            [
                ('web_status', '补全状态：', ''),
                ('web_total', '网页作品总数：', ''),
                ('web_pages', '网页总页数：', ''),
                ('eligible_video_count', '满足要求视频数量：', ''),
                ('web_earliest', '最早发布时间：', ''),
                ('web_latest', '最新发布时间：', ''),
                ('eligible_enriched_video_count', '补全满足要求视频数量：', ''),
                ('web_last_enriched', '最近补全时间：', ''),
                ('web_prefix', '网页番号分布：', ''),
                ('web_year', '网页年份构成：', ''),
            ]
        )
        web_layout.addWidget(self.web_grid)

        layout.addWidget(basic_group)
        layout.addWidget(local_group)
        layout.addWidget(web_group)
        layout.addStretch()

    def load_data(self):
        if self.task_thread is not None:
            return

        self.task_thread = QThread(self)
        self.task_worker = BackendTaskWorker(lambda: self.backend_client.get_actor_detail(self.actor_name))
        self.task_worker.moveToThread(self.task_thread)
        self.task_thread.started.connect(self.task_worker.run)
        self.task_worker.finished.connect(self._on_load_data_finished)
        self.task_worker.failed.connect(self._on_load_data_failed)
        self.task_worker.finished.connect(self.task_thread.quit)
        self.task_worker.failed.connect(self.task_thread.quit)
        self.task_thread.finished.connect(self._cleanup_task_thread)
        self.task_thread.start()

    def _on_load_data_finished(self, detail):
        self.detail = dict(detail or {})
        self.basic_grid.set_value('name', self.detail.get('name', ''))
        self.basic_grid.set_value('actor_id', self.detail.get('actor_id', '') or '暂无')
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

    def _on_load_data_failed(self, message):
        QMessageBox.critical(self, '读取失败', f'读取演员详情失败：\n{str(message or "")}')
        self.reject()

    def _cleanup_task_thread(self):
        if self.task_worker is not None:
            self.task_worker.deleteLater()
        if self.task_thread is not None:
            self.task_thread.deleteLater()
        self.task_worker = None
        self.task_thread = None

    def closeEvent(self, event):
        if self.task_thread and self.task_thread.isRunning():
            QMessageBox.information(self, '加载进行中', '请等待当前加载完成后再关闭窗口。')
            event.ignore()
            return
        super().closeEvent(event)
