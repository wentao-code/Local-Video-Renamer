from PyQt5.QtCore import QThread, Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QGroupBox, QMessageBox, QVBoxLayout

from app.gui.backend_task_worker import BackendTaskWorker
from app.gui.enrichment_summary_widgets import SummaryCard


class DataCenterWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.task_thread = None
        self.task_worker = None
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
        if self.task_thread is not None:
            return

        self.setCursor(Qt.WaitCursor)
        self.task_thread = QThread(self)
        self.task_worker = BackendTaskWorker(lambda: self.backend_client.get_data_center_summary() or {})
        self.task_worker.moveToThread(self.task_thread)
        self.task_thread.started.connect(self.task_worker.run)
        self.task_worker.finished.connect(self._on_load_data_finished)
        self.task_worker.failed.connect(self._on_load_data_failed)
        self.task_worker.finished.connect(self.task_thread.quit)
        self.task_worker.failed.connect(self.task_thread.quit)
        self.task_thread.finished.connect(self._cleanup_task_thread)
        self.task_thread.start()

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

    def _on_load_data_failed(self, message):
        QMessageBox.critical(self, '读取失败', str(message or '读取数据中心失败。'))
        self.reject()

    def _cleanup_task_thread(self):
        if self.task_worker is not None:
            self.task_worker.deleteLater()
        if self.task_thread is not None:
            self.task_thread.deleteLater()
        self.task_worker = None
        self.task_thread = None
        self.setCursor(Qt.ArrowCursor)

    def closeEvent(self, event):
        if self.task_thread and self.task_thread.isRunning():
            QMessageBox.information(self, '加载进行中', '请等待当前加载完成后再关闭窗口。')
            event.ignore()
            return
        super().closeEvent(event)
