from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
)

from app.gui.i18n import tr


class SubtitleCandidateDialog(QDialog):
    """Let the user confirm the videos selected for the subtitle pipeline."""

    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('main.subtitle_candidates_title'))
        self.resize(900, 500)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels([
            tr('main.subtitle_candidate_select'),
            tr('main.subtitle_candidate_code'),
            tr('main.subtitle_candidate_path'),
            tr('main.subtitle_candidate_reason'),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().Stretch)
        for candidate in candidates or []:
            row = self.table.rowCount()
            self.table.insertRow(row)
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            checkbox.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, checkbox)
            self.table.setItem(row, 1, QTableWidgetItem(str(candidate.get('video_code', '') or '')))
            self.table.setItem(row, 2, QTableWidgetItem(str(candidate.get('video_path', '') or '')))
            self.table.setItem(row, 3, QTableWidgetItem(str(candidate.get('reason', '') or '')))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr('main.subtitle_candidates_message')))
        layout.addWidget(self.table)
        action_layout = QHBoxLayout()
        select_all_button = QPushButton(tr('main.subtitle_candidates_select_all'), self)
        select_all_button.clicked.connect(self.select_all)
        action_layout.addWidget(select_all_button)
        clear_selection_button = QPushButton(tr('main.subtitle_candidates_clear_selection'), self)
        clear_selection_button.clicked.connect(self.clear_selection)
        action_layout.addWidget(clear_selection_button)
        action_layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        action_layout.addWidget(buttons)
        layout.addLayout(action_layout)

    def select_all(self):
        self._set_all_check_states(Qt.Checked)

    def clear_selection(self):
        self._set_all_check_states(Qt.Unchecked)

    def _set_all_check_states(self, check_state):
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox is not None:
                checkbox.setCheckState(check_state)

    def selected_codes(self):
        selected = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.item(row, 0)
            if checkbox is not None and checkbox.checkState() == Qt.Checked:
                code_item = self.table.item(row, 1)
                if code_item is not None and code_item.text().strip():
                    selected.append(code_item.text().strip())
        return selected
