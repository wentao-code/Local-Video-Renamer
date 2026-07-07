from html import escape

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.core.ladder_board import split_ladder_medals
from app.gui.i18n import tr
from app.gui.medal_catalog_viewer import GlobalMedalPickerDialog, build_medal_text


class LadderSelectedPanel(QWidget):
    medal_save_requested = pyqtSignal(str, str)
    detail_requested = pyqtSignal(str)
    _MEDAL_CHIP_STYLE = {
        'border': '#c7a55a',
        'background': '#f8edd0',
        'text': '#6b4d12',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._medal_widgets = {}
        self.global_medals = []
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
        self.table.horizontalHeader().sectionResized.connect(self._refresh_row_heights)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self._medal_widgets = {}
        self.table.setRowCount(0)

        for row_index, row in enumerate(self.rows):
            entity_name = str((row or {}).get('display_name', '') or '').strip()
            tier = str((row or {}).get('tier', '') or '').strip().upper()
            medal_text = str((row or {}).get('medal', '') or '').strip()
            medals = list((row or {}).get('medals') or split_ladder_medals(medal_text))
            self.table.insertRow(row_index)

            name_item = QTableWidgetItem(entity_name)
            tier_item = QTableWidgetItem(tier)
            tier_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_index, 0, name_item)
            self.table.setItem(row_index, 1, tier_item)
            self.table.setCellWidget(row_index, 2, self._build_medal_widget(entity_name, medal_text, medals))
            self.table.setCellWidget(row_index, 3, self._build_action_widget(entity_name))
            self.table.setCellWidget(row_index, 4, self._build_detail_button(entity_name))

        self._refresh_row_heights()

    def set_global_medals(self, medals):
        self.global_medals = [dict(row or {}) for row in (medals or [])]

    def _build_medal_widget(self, entity_name, medal_text, medals):
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        label.setMargin(4)
        label.setText(self._build_medal_html(medals))
        self._medal_widgets[entity_name] = {
            'label': label,
            'medal_text': medal_text,
            'button': None,
        }
        return label

    def _build_action_widget(self, entity_name):
        state = self._medal_widgets.get(entity_name) or {}
        button = QPushButton(tr('ladder.selected.add_medal'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self._handle_action_clicked(name))
        if state is not None:
            state['button'] = button
            self._medal_widgets[entity_name] = state
        return button

    def _build_detail_button(self, entity_name):
        button = QPushButton(tr('ladder.detail'))
        button.clicked.connect(lambda _checked=False, name=entity_name: self.detail_requested.emit(name))
        return button

    def _handle_action_clicked(self, entity_name):
        state = self._medal_widgets.get(str(entity_name or '').strip())
        if not state:
            return

        current_medals = list(split_ladder_medals(state.get('medal_text', '')))
        dialog = GlobalMedalPickerDialog(self.global_medals, owned_medals=current_medals, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return

        medal_text = build_medal_text(current_medals, dialog.selected_medal_names())
        if medal_text == str(state.get('medal_text', '') or ''):
            return
        self.medal_save_requested.emit(entity_name, medal_text)

    def _build_medal_html(self, medals):
        if not medals:
            return ''

        palette = dict(self._MEDAL_CHIP_STYLE)
        chips = []
        for medal in medals:
            chips.append(
                (
                    '<span style="display:inline-block; margin:0 8px 8px 0; '
                    f'padding:4px 12px; border:1px solid {palette["border"]}; border-radius:999px; '
                    f'background-color:{palette["background"]}; color:{palette["text"]}; '
                    'font-weight:600;">'
                    f'{escape(str(medal or ""))}'
                    '</span>'
                )
            )
        return ''.join(chips)

    def _refresh_row_heights(self, *_args):
        self.table.resizeRowsToContents()
