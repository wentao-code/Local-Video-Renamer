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
from app.gui.actor_detail_viewer import ActorDetailViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin


class ActorViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self.editing_actor_name = None
        self.editing_row = None
        self.action_buttons = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('演员库')
        self.resize(1220, 540)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('输入演员、作者ID、生日、年龄或补全状态实时筛选...')
        self.search_input.textChanged.connect(self.filter_data)

        self.btn_reset_avfan = QPushButton('天陨重置')
        self.btn_reset_avfan.clicked.connect(lambda: self.reset_selected_rows(AVFAN_VIDEO_SOURCE))

        self.btn_reset_javtxt = QPushButton('辛聚重置')
        self.btn_reset_javtxt.clicked.connect(lambda: self.reset_selected_rows(JAVTXT_VIDEO_SOURCE))

        self.btn_refresh = QPushButton('刷新数据')
        self.btn_refresh.clicked.connect(self.load_data)

        top_layout.addWidget(QLabel('实时筛选：'))
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.btn_reset_avfan)
        top_layout.addWidget(self.btn_reset_javtxt)
        top_layout.addWidget(self.btn_refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['演员', '作者 ID', '生日', '年龄', '补全状态', '详情', '操作'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 7):
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
            lambda: {'rows': self.backend_client.list_actors(search_text)},
            self._on_load_data_finished,
            '读取失败',
        )

    def render_rows(self, rows):
        self.action_buttons = {}
        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(rows):
            self.table.insertRow(row_idx)
            values = (
                row_data.get('name', ''),
                row_data.get('actor_id', ''),
                row_data.get('birthday', ''),
                row_data.get('age', ''),
                row_data.get('enrichment_status', ''),
            )
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_idx in (1, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

            actor_name = row_data.get('name', '')
            self.table.setCellWidget(row_idx, 5, self.build_detail_button(actor_name))
            self.table.setCellWidget(row_idx, 6, self.build_action_buttons(actor_name))

    def build_detail_button(self, actor_name):
        button = QPushButton('查看详情')
        button.clicked.connect(lambda _checked=False, name=actor_name: self.show_actor_detail(name))
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def build_action_buttons(self, actor_name):
        edit_button = QPushButton('修改')
        edit_button.clicked.connect(lambda _checked=False, value=actor_name: self.handle_edit_button(value))
        delete_button = QPushButton('删除')
        delete_button.clicked.connect(lambda _checked=False, value=actor_name: self.delete_actor(value))
        self.action_buttons[actor_name] = {'edit': edit_button, 'delete': delete_button}

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(edit_button)
        layout.addWidget(delete_button)
        layout.setAlignment(Qt.AlignCenter)
        return container

    def show_actor_detail(self, actor_name):
        if not actor_name:
            return
        viewer = ActorDetailViewerWindow(self.backend_client, actor_name, self)
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
            self.rows = self.backend_client.list_actors(search_text)
            self.render_rows(self.rows)
        except Exception as exc:
            print(f'筛选演员库失败: {exc}')

    def clear_edit_state(self):
        self.editing_actor_name = None
        self.editing_row = None

    def handle_edit_button(self, actor_name):
        if self.editing_actor_name is None:
            self.start_actor_edit(actor_name)
            return
        if self.editing_actor_name != actor_name:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的演员行。')
            return
        self.confirm_actor_edit()

    def start_actor_edit(self, actor_name):
        row = self.find_row_by_actor_name(actor_name)
        if row < 0:
            QMessageBox.warning(self, '提示', f'未找到演员：{actor_name}')
            return
        self.editing_actor_name = actor_name
        self.editing_row = row
        self.set_actor_cell_editable(row, True)
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText('确认')
        item = self.table.item(row, 0)
        if item is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(item)

    def confirm_actor_edit(self):
        if self.editing_actor_name is None or self.editing_row is None:
            return
        item = self.table.item(self.editing_row, 0)
        old_name = self.editing_actor_name
        if item is None:
            self.clear_edit_state()
            return

        new_name = item.text().strip()
        self.set_actor_cell_editable(self.editing_row, False)
        if not new_name:
            item.setText(old_name)
            self.reset_row_button_text(old_name)
            self.clear_edit_state()
            QMessageBox.warning(self, '提示', '演员名称不能为空')
            return

        self.clear_edit_state()
        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.rename_actor(old_name, new_name),
                lambda: self.backend_client.list_actors(search_text),
                old_name=old_name,
                new_name=new_name,
            ),
            self._on_rename_finished,
            '修改失败',
        )

    def _on_rename_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(
            self,
            '修改完成',
            f"已将演员 {result.get('old_name', '')} 修改为 {result.get('new_name', '')}。",
        )

    def reset_row_button_text(self, actor_name):
        button = self.action_buttons.get(actor_name, {}).get('edit')
        if button is not None:
            button.setText('修改')

    def set_actor_cell_editable(self, row, editable):
        item = self.table.item(row, 0)
        if item is None:
            return
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def find_row_by_actor_name(self, actor_name):
        target = str(actor_name or '').strip()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip() == target:
                return row
        return -1

    def delete_actor(self, actor_name):
        if self.editing_actor_name is not None:
            QMessageBox.information(self, '正在编辑', '请先确认当前正在修改的演员行。')
            return
        answer = QMessageBox.question(
            self,
            '确认删除',
            f'确定删除演员 {actor_name} 吗？\n这会从演员库移除该演员，并清除对应的网页补全数据。',
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: self.reload_rows_after(
                lambda: self.backend_client.delete_actor(actor_name),
                lambda: self.backend_client.list_actors(search_text),
                actor_name=actor_name,
            ),
            self._on_delete_finished,
            '删除失败',
        )

    def _on_delete_finished(self, result):
        self._on_load_data_finished(result)
        QMessageBox.information(self, '删除完成', f"已删除演员 {result.get('actor_name', '')}。")

    def reset_selected_rows(self, source_key):
        actor_names = self.selected_actor_names()
        if not actor_names:
            QMessageBox.information(self, '未选择', '请先选中要重置的演员行。')
            return
        source_label = get_video_enrichment_source_label(source_key)
        answer = QMessageBox.question(
            self,
            '确认重置',
            f'确定要重置选中的 {len(actor_names)} 个演员的{source_label}补全状态吗？',
        )
        if answer != QMessageBox.Yes:
            return

        search_text = self.search_input.text().strip()
        self.start_async_task(
            lambda: {
                'reset_count': self.backend_client.reset_actor_enrichments(actor_names, source_key=source_key),
                'rows': self.backend_client.list_actors(search_text),
                'source_label': source_label,
            },
            self._on_reset_finished,
            '重置失败',
        )

    def selected_actor_names(self):
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        actor_names = []
        for row in selected_rows:
            item = self.table.item(row, 0)
            if item and item.text().strip():
                actor_names.append(item.text().strip())
        return actor_names

    def _on_load_data_finished(self, result):
        self.clear_edit_state()
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)

    def _on_reset_finished(self, result):
        self._on_load_data_finished(result)
        reset_count = int((result or {}).get('reset_count', 0) or 0)
        source_label = str((result or {}).get('source_label', '') or '所选来源')
        QMessageBox.information(self, '重置完成', f'已重置 {reset_count} 个演员的{source_label}补全状态。')
