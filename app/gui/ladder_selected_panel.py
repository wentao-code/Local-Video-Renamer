from html import escape

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHeaderView, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from app.core.ladder_board import split_ladder_medals
from app.gui.i18n import tr
from app.gui.medal_catalog_viewer import MedalSelectionSidebar, build_medal_text


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
        self.active_entity_name = ''
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(tr('ladder.selected.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().sectionResized.connect(self._refresh_row_heights)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.medal_sidebar = MedalSelectionSidebar(
            title='勋章侧栏',
            inactive_hint='点击左侧添加后即可选择或取消勋章。',
        )
        self.medal_sidebar.setFixedWidth(220)
        layout.addWidget(self.medal_sidebar)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self._medal_widgets = {}
        self.active_entity_name = ''
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

        self.medal_sidebar.end_edit()
        self.table.setColumnWidth(0, 170)
        self._refresh_row_heights()

    def set_global_medals(self, medals):
        self.global_medals = [dict(row or {}) for row in (medals or [])]
        self.medal_sidebar.set_medals(self.global_medals)

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
        button = QPushButton(self._action_label_for(entity_name))
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

        normalized_name = str(entity_name or '').strip()
        if self.active_entity_name != normalized_name:
            self._begin_medal_edit(normalized_name, state)
            return

        medal_text = build_medal_text(new_medals=self.medal_sidebar.selected_medal_names())
        if medal_text == str(state.get('medal_text', '') or ''):
            self._cancel_medal_edit()
            return
        self.medal_save_requested.emit(entity_name, medal_text)

    def _begin_medal_edit(self, entity_name, state):
        self.active_entity_name = str(entity_name or '').strip()
        current_medals = list(split_ladder_medals(state.get('medal_text', '')))
        self.medal_sidebar.begin_edit(self.active_entity_name, current_medals)
        self._refresh_action_buttons()

    def _cancel_medal_edit(self):
        self.active_entity_name = ''
        self.medal_sidebar.end_edit()
        self._refresh_action_buttons()

    def _refresh_action_buttons(self):
        for entity_name, state in self._medal_widgets.items():
            button = (state or {}).get('button')
            if button is not None:
                button.setText(self._action_label_for(entity_name))

    def _action_label_for(self, entity_name):
        if str(entity_name or '').strip() == self.active_entity_name:
            return tr('ladder.selected.confirm_medal')
        return tr('ladder.selected.add_medal')

    def _build_medal_html(self, medals):
        if not medals:
            return ''

        palette = dict(self._MEDAL_CHIP_STYLE)
        chips = []
        for index, medal in enumerate(medals):
            if index:
                chips.append(
                    (
                        '<span style="display:inline-block; margin:0 8px 8px 0; '
                        'color:#b88a1d; font-size:14px; font-weight:700; vertical-align:middle;">'
                        '🥇'
                        '</span>'
                    )
                )
            chips.append(
                (
                    '<span style="display:inline-block; margin:0 8px 8px 0; '
                    f'width:96px; padding:6px 10px; border:1px solid {palette["border"]}; border-radius:12px; '
                    f'background-color:{palette["background"]}; color:{palette["text"]}; '
                    'font-weight:700; text-align:center; box-sizing:border-box; '
                    'box-shadow:0 2px 6px rgba(107, 77, 18, 0.12); '
                    'vertical-align:middle;">'
                    f'{escape(str(medal or ""))}'
                    '</span>'
                )
            )
        return ''.join(chips)

    def _refresh_row_heights(self, *_args):
        self.table.resizeRowsToContents()
