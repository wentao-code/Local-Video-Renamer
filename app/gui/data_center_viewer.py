from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QGroupBox, QVBoxLayout

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.enrichment_summary_widgets import SummaryCard


class DataCenterWindow(QDialog, AsyncTaskHostMixin):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('数据中心')
        self.resize(1240, 520)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        summary_group = QGroupBox('补全进度')
        summary_layout = QGridLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)

        self.video_avfan_card = SummaryCard('视频库·天限阁')
        self.video_javtxt_card = SummaryCard('视频库·辛聚谷')
        self.code_prefix_avfan_card = SummaryCard('番号库·天限阁')
        self.code_prefix_javtxt_card = SummaryCard('番号库·辛聚谷')
        self.actor_avfan_card = SummaryCard('演员库·天限阁')
        self.actor_javtxt_card = SummaryCard('演员库·辛聚谷')

        summary_layout.addWidget(self.video_avfan_card, 0, 0)
        summary_layout.addWidget(self.video_javtxt_card, 0, 1)
        summary_layout.addWidget(self.code_prefix_avfan_card, 1, 0)
        summary_layout.addWidget(self.code_prefix_javtxt_card, 1, 1)
        summary_layout.addWidget(self.actor_avfan_card, 2, 0)
        summary_layout.addWidget(self.actor_javtxt_card, 2, 1)

        layout.addWidget(summary_group)
        self.setLayout(layout)

    def load_data(self):
        self.start_async_task(
            lambda: self.backend_client.get_data_center_summary() or {},
            self._on_load_data_finished,
            '读取失败',
        )

    def _set_async_busy(self, busy):
        self.setCursor(Qt.WaitCursor if busy else Qt.ArrowCursor)

    def _on_load_data_finished(self, summary):
        summary = dict(summary or {})
        video_summary = summary.get('video_library', {}).get('sources', {})
        code_prefix_summary = summary.get('code_prefix_library', {}).get('sources', {})
        actor_summary = summary.get('actor_library', {}).get('sources', {})

        self.video_avfan_card.set_summary(video_summary.get('avfan', {}), show_terminal_details=False)
        self.video_javtxt_card.set_summary(video_summary.get('javtxt', {}), show_terminal_details=False)
        self.code_prefix_avfan_card.set_summary(code_prefix_summary.get('avfan', {}))
        self.code_prefix_javtxt_card.set_summary(code_prefix_summary.get('javtxt', {}))
        self.actor_avfan_card.set_summary(actor_summary.get('avfan', {}))
        self.actor_javtxt_card.set_summary(actor_summary.get('javtxt', {}))

    def closeEvent(self, event):
        if self.block_close_while_async_running(event, '加载进行中', '请等待当前加载完成后再关闭窗口。'):
            return
        super().closeEvent(event)
