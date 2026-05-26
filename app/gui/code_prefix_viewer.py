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
    QWidget,
)

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    get_video_enrichment_source_label,
)
from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.code_prefix_detail_viewer import CodePrefixDetailViewerWindow
from app.gui.i18n import tr


class CodePrefixViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.editing_prefix = None
        self.editing_row = None
        self.action_buttons = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(tr('code_prefix.viewer.title'))
        self.resize(1160, 560)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr('code_prefix.viewer.search_placeholder'))
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset_avfan = QPushButton(tr('code_prefix.viewer.reset_avfan'))
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton(tr('code_prefix.viewer.reset_javtxt'))
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel(tr('common.filter_realtime')))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(tr('code_prefix.viewer.headers'))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 8):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)

        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [self.search_input, self.btn_reset_avfan, self.btn_reset_javtxt, self.btn_refresh, self.table]
        )

    def load_data(self):
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {'rows': self.backend_client.list_code_prefixes(search_text)},
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('prefix', ''),
                row_data.get('video_count', 0),
                row_data.get('enrichment_status', ''),
                row_data.get('avfan_total_videos', 0),
                row_data.get('earliest_release_date', ''),
                row_data.get('latest_release_date', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            prefix = row_data.get('prefix', '')
            self.table.setCellWidget(row_idx, 6, self.build_detail_button(prefix))
            self.table.setCellWidget(row_idx, 7, self.build_action_buttons(prefix))

    def build_detail_button(self, prefix):
        button = QPushButton(tr('code_prefix.viewer.detail'))
        button.clicked.connect(lambda _checked=False, value=prefix: self.show_prefix_detail(value))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, prefix):
        edit_button = QPushButton(tr('code_prefix.viewer.edit'))
        edit_button.clicked.connect(lambda _checked=False, value=prefix: self.handle_edit_button(value))
        delete_button = QPushButton(tr('code_prefix.viewer.delete'))
        delete_button.clicked.connect(lambda _checked=False, value=prefix: self.delete_prefix(value))
        self.action_buttons[prefix] = {'edit': edit_button, 'delete': delete_button}

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_prefix_detail(self, prefix):
        if not prefix:
            return
        viewer = CodePrefixDetailViewerWindow(self.backend_client, prefix, self)
        viewer.exec_()

    def filter_data(self, text):
        if self.is_async_task_running():
            return
        self.clear_edit_state()
        search_text = str(text or '').strip()
        if not search_text:
            self.load_data()
            return
        try:
            self.rows = self.backend_client.list_code_prefixes(search_text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(tr('code_prefix.viewer.filter_failed', error=exc))

    def clear_edit_state(self):
        self.editing_prefix = None
        self.editing_row = None

    def handle_edit_button(self, prefix):
        if self.editing_prefix is None:
            self.start_prefix_edit(prefix)
            return
        if self.editing_prefix != prefix:
            QMessageBox.information(self, tr('code_prefix.viewer.editing_title'), tr('code_prefix.viewer.editing_message'))
            return
        self.confirm_prefix_edit()

    def start_prefix_edit(self, prefix):
        row = self.find_row_by_prefix(prefix)
        if row < 0:
            QMessageBox.warning(self, tr('common.prompt'), tr('code_prefix.viewer.not_found', prefix=prefix))
            return
        self.editing_prefix = prefix
        self.editing_row = row
        self.set_prefix_cell_editable(row, True)
        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText(tr('common.ok'))
        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_prefix_edit(self):
        if self.editing_prefix is None or self.editing_row is None:
            return
        item = self.table.item(self.editing_row, 0)
        old_prefix = self.editing_prefix
        if item is None:
            self.clear_edit_state()
            return

        new_prefix = item.text().strip().upper()
        self.set_prefix_cell_editable(self.editing_row, False)
        if not new_prefix:
            item.setText(old_prefix)
            self.reset_row_button_text(old_prefix)
            self.clear_edit_state()
            QMessageBox.warning(self, tr('common.prompt'), tr('code_prefix.viewer.prefix_required'))
            return

        self.clear_edit_state()
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.rename_code_prefix(old_prefix, new_prefix),
                lambda: self.backend_client.list_code_prefixes(search_text),
                old_prefix=old_prefix,
                new_prefix=new_prefix,
            ),
            self._on_rename_finished,
            tr('code_prefix.viewer.rename_failed'),
        )

    def _on_rename_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('code_prefix.viewer.rename_completed'),
            tr(
                'code_prefix.viewer.rename_completed_message',
                old_prefix=result.get('old_prefix', ''),
                new_prefix=result.get('new_prefix', ''),
            ),
        )

    def reset_row_button_text(self, prefix):
        button = self.action_buttons.get(prefix, {}).get('edit')
        if button is not None:
            button.setText(tr('code_prefix.viewer.edit'))

    def set_prefix_cell_editable(self, row, editable):
        item = self.table.item(row, 0)
        if item is None:
            return
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def find_row_by_prefix(self, prefix):
        target = str(prefix or '').strip().upper()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip().upper() == target:
                return row
        return -1

    def delete_prefix(self, prefix):
        if self.editing_prefix is not None:
            QMessageBox.information(self, tr('code_prefix.viewer.editing_title'), tr('code_prefix.viewer.editing_message'))
            return
        answer = QMessageBox.question(
            self,
            tr('code_prefix.viewer.confirm_delete_title'),
            tr('code_prefix.viewer.confirm_delete_message', prefix=prefix),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.delete_code_prefix(prefix),
                lambda: self.backend_client.list_code_prefixes(search_text),
                prefix=prefix,
            ),
            self._on_delete_finished,
            tr('code_prefix.viewer.delete_failed'),
        )

    def _on_delete_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            tr('code_prefix.viewer.delete_completed'),
            tr('code_prefix.viewer.delete_completed_message', prefix=result.get('prefix', '')),
        )

    def reset_selected_rows(self, source_key):
        prefixes = self.selected_prefixes()
        if not prefixes:
            QMessageBox.information(self, tr('common.no_selection'), tr('code_prefix.viewer.select_reset_rows'))
            return
        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            tr('code_prefix.viewer.confirm_reset_title'),
            tr('code_prefix.viewer.confirm_reset_message', count=len(prefixes), source_label=source_label),
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_code_prefix_enrichments(prefixes, source_key=source_key),
                'rows': self.backend_client.list_code_prefixes(search_text),
                'source_label': source_label,
            },
            self._on_reset_finished,
            tr('common.reset_failed'),
        )

    def selected_prefixes(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        prefixes = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                prefixes.append(item.text().strip())
        return prefixes

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or tr('common.reset_source_fallback'))
        QMessageBox.information(
            self,
            tr('common.reset_completed'),
            tr('code_prefix.viewer.reset_completed_message', count=reset_count, source_label=source_label),
        )
