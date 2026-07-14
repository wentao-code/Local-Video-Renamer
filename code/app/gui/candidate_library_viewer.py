from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr


CANDIDATE_ACTOR_MODE = 'actor'
CANDIDATE_CODE_PREFIX_MODE = 'code_prefix'


class CandidateLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.mode = CANDIDATE_ACTOR_MODE
        self.rows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('candidate_library.title'))
        self.resize(760, 620)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.btn_actors = QPushButton(tr('candidate_library.actors'))
        self.btn_actors.setCheckable(True)
        self.btn_actors.clicked.connect(lambda: self.set_mode(CANDIDATE_ACTOR_MODE))
        self.btn_code_prefixes = QPushButton(tr('candidate_library.code_prefixes'))
        self.btn_code_prefixes.setCheckable(True)
        self.btn_code_prefixes.clicked.connect(lambda: self.set_mode(CANDIDATE_CODE_PREFIX_MODE))
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.refresh_candidates)
        self.summary_label = QLabel()

        toolbar.addWidget(self.btn_actors)
        toolbar.addWidget(self.btn_code_prefixes)
        toolbar.addWidget(self.summary_label)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addLayout(toolbar)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_actors, self.btn_code_prefixes, self.btn_refresh, self.table])
        self._update_mode_controls()

    def set_mode(self, mode):
        if mode not in (CANDIDATE_ACTOR_MODE, CANDIDATE_CODE_PREFIX_MODE):
            return
        if self.mode == mode and self.rows:
            return
        self.mode = mode
        self.rows = []
        self._update_mode_controls()
        self.load_data()

    def load_data(self):
        if self.mode == CANDIDATE_ACTOR_MODE:
            task = self.backend_client.list_candidate_actors
        else:
            task = self.backend_client.list_candidate_code_prefixes
        self.start_async_task(task, self._on_load_finished, tr('common.read_failed'), max_attempts=1)

    def refresh_candidates(self):
        self.start_async_task(
            self.backend_client.refresh_candidate_library,
            self._on_refresh_finished,
            tr('common.read_failed'),
            max_attempts=1,
        )

    def _on_refresh_finished(self, _result):
        QTimer.singleShot(50, self.load_data)

    def _on_load_finished(self, rows):
        self.rows = [dict(row or {}) for row in rows or []]
        self.render_rows()

    def render_rows(self):
        entity_header = tr('candidate_library.actor_header')
        if self.mode == CANDIDATE_CODE_PREFIX_MODE:
            entity_header = tr('candidate_library.code_prefix_header')
        self.table.setHorizontalHeaderLabels(
            [tr('candidate_library.rank_header'), entity_header, tr('candidate_library.video_count_header'), tr('candidate_library.action_header')]
        )
        self.summary_label.setText(tr('candidate_library.summary', count=len(self.rows)))
        self.table.setRowCount(0)
        entity_key = 'actor_name' if self.mode == CANDIDATE_ACTOR_MODE else 'prefix'
        for row_index, row_data in enumerate(self.rows):
            self.table.insertRow(row_index)
            values = (row_index + 1, row_data.get(entity_key, ''), row_data.get('video_count', 0))
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if column_index != 1:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)
            self.table.setCellWidget(row_index, 3, self._build_admit_button(str(row_data.get(entity_key, '') or '').strip()))

    def _build_admit_button(self, entity_key):
        button = QPushButton(tr('candidate_library.admit'))
        if self.mode == CANDIDATE_ACTOR_MODE:
            button.clicked.connect(lambda _checked=False, value=entity_key: self.admit_actor(value))
        else:
            button.clicked.connect(lambda _checked=False, value=entity_key: self.admit_code_prefix(value))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def admit_actor(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            return
        self.start_async_task(
            lambda: self.backend_client.admit_candidate_actor(normalized_name),
            lambda result: self._on_admit_finished(normalized_name, int(result or 0)),
            tr('candidate_library.admit_failed'),
        )

    def admit_code_prefix(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            return
        self.start_async_task(
            lambda: self.backend_client.admit_candidate_code_prefix(normalized_prefix),
            lambda result: self._on_admit_finished(normalized_prefix, int(result or 0)),
            tr('candidate_library.admit_failed'),
        )

    def _on_admit_finished(self, entity_key, created_count):
        field_name = 'actor_name' if self.mode == CANDIDATE_ACTOR_MODE else 'prefix'
        self.rows = [
            row for row in self.rows if str((row or {}).get(field_name, '') or '').strip() != str(entity_key or '').strip()
        ]
        self.render_rows()
        QMessageBox.information(
            self,
            tr('candidate_library.admit_completed'),
            tr('candidate_library.admit_completed_message', count=created_count),
        )

    def _update_mode_controls(self):
        self.btn_actors.setChecked(self.mode == CANDIDATE_ACTOR_MODE)
        self.btn_code_prefixes.setChecked(self.mode == CANDIDATE_CODE_PREFIX_MODE)
