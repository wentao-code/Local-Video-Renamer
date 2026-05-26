from PyQt5.QtWidgets import QDialog, QVBoxLayout

from app.gui.video_detail_table import VideoDetailTableWidget


class VideoListDetailWindow(QDialog):
    def __init__(self, title, table_title, rows=None, parent=None):
        super().__init__(parent)
        self.rows = list(rows or [])
        self.table_title = str(table_title or '').strip()
        self.setWindowTitle(str(title or '视频详情'))
        self.resize(1320, 760)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.video_table = VideoDetailTableWidget(title=self.table_title, parent=self)
        self.video_table.set_rows(self.rows)
        layout.addWidget(self.video_table)
