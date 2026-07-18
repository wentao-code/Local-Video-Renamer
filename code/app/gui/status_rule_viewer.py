from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from app.core.status_rule_catalog import LIBRARY_STATUS_RULES, PROFILE_STATUS_RULES
from app.gui.i18n import tr


class StatusRuleViewerWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('status_rules.title'))
        self.resize(980, 680)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(
            self._build_table(LIBRARY_STATUS_RULES, include_sources=True),
            tr('status_rules.library_tab'),
        )
        tabs.addTab(
            self._build_table(PROFILE_STATUS_RULES),
            tr('status_rules.profile_tab'),
        )
        layout.addWidget(tabs)

    @staticmethod
    def _build_table(rules, include_sources=False):
        headers = ['状态', '名称', '描述']
        if include_sources:
            headers.append('适用来源')
        table = QTableWidget(len(rules), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        if include_sources:
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)

        for row_index, rule in enumerate(rules):
            for column_index, value in enumerate(rule):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column_index, item)
            table.resizeRowToContents(row_index)
        return table
