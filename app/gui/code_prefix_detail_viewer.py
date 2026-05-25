from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QDialog, QGroupBox, QMessageBox, QScrollArea, QVBoxLayout

from app.gui.backend_task_worker import BackendTaskWorker
from app.gui.detail_summary_widgets import DetailSummaryGrid, format_distribution_summary


class CodePrefixDetailViewerWindow(QDialog):
    def __init__(self, backend_client, prefix, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.prefix = str(prefix or '').strip().upper()
        self.detail = {}
        self.task_thread = None
        self.task_worker = None
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
        if self.task_thread is not None:
            return

        self.task_thread = QThread(self)
        self.task_worker = BackendTaskWorker(lambda: self.backend_client.get_code_prefix_detail(self.prefix))
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
            format_distribution_summary(
                self.detail.get('year_distribution', []),
                'year',
                items_per_line=3,
            ),
        )
        self.stats_grid.set_value(
            'top_actors',
            format_distribution_summary(
                self.detail.get('top_actors', []),
                'name',
                items_per_line=2,
            ),
        )

    def _on_load_data_failed(self, message):
        QMessageBox.critical(self, '读取失败', f'读取番号详情失败：\n{str(message or "")}')
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
