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
        try:
            summary = self.backend_client.get_data_center_summary() or {}
        except Exception as exc:
            print(f'读取数据中心进度失败: {exc}')
            return

        video_summary = summary.get('video_library', {}).get('sources', {})
        code_prefix_summary = summary.get('code_prefix_library', {}).get('sources', {})
        actor_summary = summary.get('actor_library', {}).get('sources', {})

        self.video_avfan_card.set_summary(video_summary.get('avfan', {}), show_terminal_details=False)
        self.video_javtxt_card.set_summary(video_summary.get('javtxt', {}), show_terminal_details=False)
        self.code_prefix_avfan_card.set_summary(code_prefix_summary.get('avfan', {}))
        self.code_prefix_javtxt_card.set_summary(code_prefix_summary.get('javtxt', {}))
        self.actor_avfan_card.set_summary(actor_summary.get('avfan', {}))
        self.actor_javtxt_card.set_summary(actor_summary.get('javtxt', {}))
