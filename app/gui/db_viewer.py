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
)

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.core.enrichment_status import ENRICHED_STATUS
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


class DatabaseViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('db.viewer.title'))
        self.resize(1440, 720)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('db.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset_avfan = QPushButton(tr('db.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('db.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel(tr('common.filter_realtime')))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_refresh)

        self.summary_label = QLabel(tr('db.viewer.summary', enriched_count=0, unenriched_count=0, total_count=0))
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels(tr('db.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [self.search_input, self.btn_reset_avfan, self.btn_reset_javtxt, self.btn_refresh, self.table]
        )

    def load_data(self):
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'rows': self.backend_client.list_videos(search_text),
            },
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def render_rows(self, rows):
        self.table.setRowCount(0)
        fields = (
            'code',
            'title',
            'author',
            'video_category',
            'duration',
            'size',
            'storage_location',
            'avfan_movie_id',
            'javtxt_movie_id',
            'release_date',
            'maker',
            'publisher',
            'enrichment_status',
        )
        centered_columns = {0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}

        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            for col_idx, field in enumerate(fields):
                item = QTableWidgetItem(str(row_data.get(field, '')))
                if col_idx in centered_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)

    def refresh_summary(self):
        total_count = len(self.rows)
        enriched_count = sum(1 for row in self.rows if ENRICHED_STATUS in str(row.get('enrichment_status', '') or ''))
        unenriched_count = max(total_count - enriched_count, 0)
        self.summary_label.setText(
            tr(
                'db.viewer.summary',
                enriched_count=enriched_count,
                unenriched_count=unenriched_count,
                total_count=total_count,
            )
        )

    def filter_data(self, text):
        if self.is_async_task_running():
            return
        if not str(text or '').strip():
            self.load_data()
            return

        try:
            self.rows = self.backend_client.list_videos(str(text or '').strip())
            self.render_rows(self.rows)
            self.refresh_summary()
        except Exception as exc:
            print(tr('db.viewer.filter_failed', error=exc))

    def reset_selected_rows(self, source_key):
        codes = self.selected_codes()
        if not codes:
            QMessageBox.information(self, tr('common.no_selection'), tr('db.viewer.select_reset_rows'))
            return

        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            tr('db.viewer.confirm_reset_title'),
            tr('db.viewer.confirm_reset_message', count=len(codes), source_label=source_label),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_video_enrichments(codes, source_key=source_key),
                'rows': self.backend_client.list_videos(search_text),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_codes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        codes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                codes.append(item.text().strip())
        return codes

    def _on_load_data_finished(self, result):
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)
        self.refresh_summary()

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or tr('common.reset_source_fallback'))
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr('db.viewer.reset_completed_message', count=reset_count, source_label=source_label),
        )
