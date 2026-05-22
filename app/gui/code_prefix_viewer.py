from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow


class CodePrefixViewerWindow(QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('番号库')
        self.resize(980, 560)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入番号前缀实时筛选，例如 AARM、IPX...')
        self.search_input.textChanged.connect(self.filter_data)

        btn_reset = QPushButton('选中重置')
        btn_reset.clicked.connect(self.reset_selected_rows)

        btn_refresh = QPushButton('刷新数据')
        btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选：'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(btn_reset)
        top_layout.addWidget(btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            '番号',
            '本地视频数',
            '补全状态',
            'AVFan作品数',
            '最早发布时间',
            '最新发布时间',
            '详情',
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

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
                row_data.get('enrichment_status', ''),
                row_data.get('avfan_total_videos', 0),
                row_data.get('earliest_release_date', ''),
                row_data.get('latest_release_date', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

            self.table.setCellWidget(row_idx, 6, self.build_detail_button(row_data.get('prefix', '')))

    def build_detail_button(self, prefix):
        button = QPushButton('查看详情')
        button.clicked.connect(lambda _checked=False, value=prefix: self.show_prefix_detail(value))

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_prefix_detail(self, prefix):
        if not prefix:
            return
        viewer = CodePrefixDetailViewerWindow(
            backend_client=self.backend_client,
            prefix=prefix,
            parent=self,
        )
        viewer.exec_()

    def filter_data(self, text):
        try:
            self.rows = self.backend_client.list_code_prefixes(text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选番号库失败: {exc}')

    def reset_selected_rows(self):
        prefixes = self.selected_prefixes()
        if not prefixes:
            QMessageBox.information(self, '未选择', '请先选中要重置的番号行。')
            return

        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(prefixes)} 个番号补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        try:
            reset_count = self.backend_client.reset_code_prefix_enrichments(prefixes)
        except Exception as exc:
            QMessageBox.critical(self, '重置失败', f'重置番号补全状态失败：\n{exc}')
            return

        self.load_data()
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个番号的补全状态。')

    def selected_prefixes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        prefixes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                prefixes.append(item.text().strip())
        return prefixes
