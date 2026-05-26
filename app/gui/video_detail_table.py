from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class VideoDetailTableWidget(QWidget):
    def __init__(self, title='', parent=None):
        super().__init__(parent)
        self._rows = []
        self._title = str(title or '').strip()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        self.title_label = QLabel(self._title)
        self.summary_label = QLabel('共 0 条')
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入编号、标题、演员、日期或分类实时筛选...')
        self.search_input.textChanged.connect(self._apply_filter)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        top_layout.addWidget(QLabel('筛选:'))
        top_layout.addWidget(self.search_input, 1)
        top_layout.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ['视频编号', '视频标题', '作者/演员', '视频分类', '发布日期']
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)

    def set_title(self, title):
        self._title = str(title or '').strip()
        self.title_label.setText(self._title)

    def set_rows(self, rows):
        self._rows = [dict(row or {}) for row in (rows or [])]
        self._apply_filter()

    def _apply_filter(self):
        search_text = str(self.search_input.text() or '').strip().lower()
        if not search_text:
            rows = list(self._rows)
        else:
            rows = [row for row in self._rows if self._matches_search(row, search_text)]
        self._render_rows(rows)

    def _render_rows(self, rows):
        self.table.setRowCount(0)
        centered_columns = {0, 2, 3, 4}
        fields = ('code', 'title', 'author', 'video_category', 'release_date')

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                value = str(row_data.get(field, '') or '')
                item = QTableWidgetItem(value)
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

        self.summary_label.setText(f'共 {len(rows)} 条')

    @staticmethod
    def _matches_search(row, search_text):
        haystack = ' '.join(
            str((row or {}).get(field, '') or '')
            for field in ('code', 'title', 'author', 'video_category', 'release_date')
        ).lower()
        return search_text in haystack
