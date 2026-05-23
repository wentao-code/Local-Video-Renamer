from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QGroupBox, QVBoxLayout

from app.gui.enrichment_summary_widgets import SummaryCard


class DataCenterWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('数据库')
        self.resize(1240, 360)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        summary_group = QGroupBox('补全进度')
        summary_layout = QGridLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(10)

        self.video_avfan_card = SummaryCard('天陨阁')
        self.video_javtxt_card = SummaryCard('辛聚谷')
        self.code_prefix_card = SummaryCard('番号库')
        self.actor_card = SummaryCard('作者库')

        summary_layout.addWidget(self.video_avfan_card, 0, 0)
        summary_layout.addWidget(self.video_javtxt_card, 0, 1)
        summary_layout.addWidget(self.code_prefix_card, 1, 0)
        summary_layout.addWidget(self.actor_card, 1, 1)

        layout.addWidget(summary_group)
        self.setLayout(layout)

    def load_data(self):
        try:
            summary = self.backend_client.get_data_center_summary() or {}
        except Exception as exc:
            print(f'读取数据库进度失败: {exc}')
            return

        video_summary = summary.get('video_library', {}).get('sources', {})
        self.video_avfan_card.set_summary(video_summary.get('avfan', {}), show_terminal_details=False)
        self.video_javtxt_card.set_summary(video_summary.get('javtxt', {}), show_terminal_details=False)
        self.code_prefix_card.set_summary(summary.get('code_prefix_library', {}))
        self.actor_card.set_summary(summary.get('actor_library', {}))
