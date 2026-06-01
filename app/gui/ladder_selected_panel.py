from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.i18n import tr


class LadderSelectedPanel(QWidget):
    medal_save_requested = pyqtSignal(str, str)
    detail_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._medal_widgets = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(tr('ladder.selected.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self._medal_widgets = {}
        self.table.setRowCount(0)

        for row_index, row in enumerate(self.rows):
            entity_name = str((row or {}).get('display_name', '') or '').strip()
            tier = str((row or {}).get('tier', '') or '').strip().upper()
            medal = str((row or {}).get('medal', '') or '').strip()
            self.table.insertRow(row_index)

            name_item = QTableWidgetItem(entity_name)
            tier_item = QTableWidgetItem(tier)
            tier_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, tier_item)
            self.table.setCellWidget(row_index, 2, self._build_medal_widget(entity_name, medal))
            self.table.setCellWidget(row_index, 3, self._build_action_widget(entity_name))
            self.table.setCellWidget(row_index, 4, self._build_detail_button(entity_name))

    def _build_medal_widget(self, entity_name, medal):
        editor = QLineEdit()
        editor.setText(medal)
        editor.setReadOnly(True)
        self._medal_widgets[entity_name] = {'editor': editor, 'editing': False, 'button': None}
        return editor

    def _build_action_widget(self, entity_name):
        button = QPushButton(tr('ladder.selected.add_medal'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self._handle_action_clicked(name))
        state = self._medal_widgets.get(entity_name)
        if state is not None:
            state['button'] = button
        return button

    def _build_detail_button(self, entity_name):
        button = QPushButton(tr('ladder.detail'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self.detail_requested.emit(name))
        return button

    def _handle_action_clicked(self, entity_name):
        state = self._medal_widgets.get(str(entity_name or '').strip())
        if not state:
            return

        editor = state['editor']
        button = state['button']
        if not state['editing']:
            state['editing'] = True
            editor.setReadOnly(False)
            editor.setFocus()
            editor.selectAll()
            if button is not None:
                button.setText(tr('ladder.selected.confirm_medal'))
            return

        state['editing'] = False
        editor.setReadOnly(True)
        if button is not None:
            button.setText(tr('ladder.selected.add_medal'))
        self.medal_save_requested.emit(entity_name, editor.text().strip())
