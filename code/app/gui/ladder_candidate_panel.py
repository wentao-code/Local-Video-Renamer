from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMessageBox,
    QHeaderView,
    QRadioButton,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.ladder_board import LADDER_TIERS
from app.gui.i18n import tr


class LadderCandidatePanel(QWidget):
    admit_requested = pyqtSignal(str, str)
    detail_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._tier_groups = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(tr('ladder.candidate.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self._tier_groups = {}
        self.table.setRowCount(0)

        for row_index, row in enumerate(self.rows):
            entity_name = str((row or {}).get('display_name', '') or '').strip()
            local_video_count = int((row or {}).get('local_video_count', 0) or 0)
            self.table.insertRow(row_index)

            name_item = QTableWidgetItem(entity_name)
            count_item = QTableWidgetItem(str(local_video_count))
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, count_item)
            self.table.setCellWidget(row_index, 2, self._build_tier_widget(entity_name))
            self.table.setCellWidget(row_index, 3, self._build_admit_button(entity_name))
            self.table.setCellWidget(row_index, 4, self._build_detail_button(entity_name))

    def _build_tier_widget(self, entity_name):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        group = QButtonGroup(container)
        for tier in LADDER_TIERS:
            button = QRadioButton(tier)
            group.addButton(button)
            group.setId(button, len(group.buttons()))
            layout.addWidget(button)
        layout.addStretch()
        self._tier_groups[entity_name] = group
        return container

    def _build_admit_button(self, entity_name):
        button = QPushButton(tr('ladder.candidate.admit'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self._handle_admit_clicked(name))
        return button

    def _build_detail_button(self, entity_name):
        button = QPushButton(tr('ladder.detail'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self.detail_requested.emit(name))
        return button

    def _handle_admit_clicked(self, entity_name):
        tier = self.selected_tier(entity_name)
        if not tier:
            QMessageBox.warning(self, tr('common.prompt'), tr('ladder.candidate.select_tier_first'))
            return
        self.admit_requested.emit(entity_name, tier)

    def selected_tier(self, entity_name):
        group = self._tier_groups.get(str(entity_name or '').strip())
        if group is None:
            return ''
        for button in group.buttons():
            if button.isChecked():
                return str(button.text() or '').strip().upper()
        return ''
