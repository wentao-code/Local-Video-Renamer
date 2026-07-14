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

from app.gui.i18n import tr


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
        self.summary_label = QLabel(tr('video.detail.summary', count=0))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('video.detail.search_placeholder'))
        self.search_input.textChanged.connect(self._apply_filter)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        top_layout.addWidget(QLabel(tr('common.filter')))
        top_layout.addWidget(self.search_input, 1)
        top_layout.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(tr('video.detail.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
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
        centered_columns = {0, 3, 4}
        fields = ('code', 'title', 'author', 'video_category', 'release_date', 'javtxt_tags')

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                value = str(row_data.get(field, '') or '')
                item = QTableWidgetItem(value)
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

        self.summary_label.setText(tr('video.detail.summary', count=len(rows)))

    @staticmethod
    def _matches_search(row, search_text):
        haystack = ' '.join(
            str((row or {}).get(field, '') or '')
            for field in ('code', 'title', 'author', 'video_category', 'release_date', 'javtxt_tags')
        ).lower()
        return search_text in haystack
