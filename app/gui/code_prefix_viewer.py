from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class CodePrefixViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('番号库')
        self.resize(640, 480)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入番号前缀实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        btn_refresh = QPushButton('刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选:'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['番号', '视频数量', '最早更新时间', '最近更新时间'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load_data(self):
        self.table.setRowCount(0)
        try:
            self.rows = self.backend_client.list_code_prefixes()
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'读取番号库失败: {exc}')

    def render_rows(self, rows):
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('prefix', ''),
                row_data.get('video_count', 0),
                row_data.get('first_updated_at', ''),
                row_data.get('last_updated_at', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def filter_data(self, text):
        try:
            self.rows = self.backend_client.list_code_prefixes(text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选番号库失败: {exc}')
