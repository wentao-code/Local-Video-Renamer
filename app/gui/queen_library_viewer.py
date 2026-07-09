from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.i18n import tr
from app.gui.queen_library_sorting import sort_queen_rows


BUTTONS_PER_ROW = 9
KEYWORDS_PER_ROW = 6
QUEEN_VIDEO_CONTENT_TYPE_OPTIONS = ('\u8fb1\u9a82', '\u804a\u5929', '\u8c03\u6559')
QUEEN_VIDEO_CONTENT_LEVEL_OPTIONS = ('S', 'A', 'B', 'C')
QUEEN_PROFILE_FIELD_OPTIONS = {
    'body_type': ('身材', ('苗条', '肥胖')),
    'style': ('风格', ('温和', '粗暴')),
    'face': ('露脸', ('是', '否')),
    'age_group': ('年龄', ('萝莉', '少妇', '熟女')),
    'like_level': ('喜欢等级', ('A', 'B', 'C', 'D')),
}


class KeywordLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.keywords = []
        self._keyword_buttons = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('关键词库')
        self.resize(980, 520)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.info_label = QLabel('已保存关键词')
        self.btn_delete_selected = QPushButton('删除选中')
        self.btn_delete_selected.clicked.connect(self.delete_selected_keywords)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.info_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_delete_selected)
        top_layout.addWidget(self.btn_refresh)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setHorizontalSpacing(10)
        self.grid_layout.setVerticalSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.scroll_widget)

        layout.addLayout(top_layout)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_delete_selected, self.btn_refresh])

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.list_queen_keywords_snapshot(force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.keywords = list(payload.get('keywords', []) or [])
        self.info_label.setText(f'已保存关键词 {len(self.keywords)} 个')
        self._render_keyword_buttons()

    def _render_keyword_buttons(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._keyword_buttons.clear()
        for index, row in enumerate(self.keywords):
            keyword = str((row or {}).get('keyword', '') or '').strip()
            button = QPushButton(keyword)
            button.setCheckable(True)
            button.setMinimumWidth(140)
            button.setStyleSheet(
                'QPushButton { text-align: center; padding: 8px 10px; }'
                'QPushButton:checked { background-color: #0078d4; color: white; }'
            )
            self._keyword_buttons.append(button)
            self.grid_layout.addWidget(button, index // KEYWORDS_PER_ROW, index % KEYWORDS_PER_ROW)

    def delete_selected_keywords(self):
        selected = [btn for btn in self._keyword_buttons if btn.isChecked()]
        if not selected:
            QMessageBox.information(self, '提示', '请先勾选要删除的关键词')
            return
        names = [btn.text() for btn in selected]
        answer = QMessageBox.question(
            self, '确认删除',
            f'确定删除 {len(names)} 个关键词吗？\n\n{chr(10).join(names[:10])}'
            + (f'\n...等共{len(names)}个' if len(names) > 10 else ''),
        )
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self._delete_keywords(names),
            self._on_delete_finished,
            '删除关键词失败',
        )

    def _delete_keywords(self, names):
        deleted = 0
        for name in names:
            count = self.backend_client.delete_queen_keyword(name)
            deleted += int(count or 0)
        return {'deleted': deleted}

    def _on_delete_finished(self, result):
        payload = dict(result or {})
        deleted = int(payload.get('deleted', 0) or 0)
        self.info_label.setText(f'已删除 {deleted} 个关键词，正在刷新...')
        self.load_data(force_refresh=True)


class QueenDetailWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, queen_name, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.queen_name = str(queen_name or '').strip()
        self.rows = []
        self.profile = {}
        self.profile_fields = {}
        self.video_metadata_fields = {}
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle(f'女王详情 - {self.queen_name}')
        self.resize(1040, 620)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.info_label = QLabel(self.queen_name)
        self.btn_delete_queen = QPushButton('删除整位女王')
        self.btn_delete_queen.clicked.connect(self.delete_queen)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))
        top_layout.addWidget(self.info_label)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_delete_queen)
        top_layout.addWidget(self.btn_refresh)

        profile_layout = QHBoxLayout()
        profile_layout.addWidget(QLabel('基础栏'))
        for field_key, (label_text, options) in QUEEN_PROFILE_FIELD_OPTIONS.items():
            profile_layout.addWidget(QLabel(label_text))
            combo = QComboBox()
            combo.addItem('')
            combo.addItems(list(options))
            combo.setFixedWidth(86)
            self.profile_fields[field_key] = combo
            profile_layout.addWidget(combo)
        self.btn_confirm_profile = QPushButton('确认')
        self.btn_confirm_profile.clicked.connect(self.confirm_profile)
        self.btn_modify_profile = QPushButton('修改')
        self.btn_modify_profile.clicked.connect(self.modify_profile)
        profile_layout.addWidget(self.btn_confirm_profile)
        profile_layout.addWidget(self.btn_modify_profile)
        profile_layout.addStretch()

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['视频标题', '原始记录', '内容', '等级', '操作'])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, self.table.horizontalHeader().ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addLayout(top_layout)
        layout.addLayout(profile_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)
        self.set_async_busy_widgets([self.btn_delete_queen, self.btn_refresh, self.table])

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: self.backend_client.get_queen_detail_snapshot(self.queen_name, force_refresh=force_refresh),
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.rows = list(payload.get('videos', []) or [])
        self.profile = dict(payload.get('profile', {}) or {})
        self.info_label.setText(f'{self.queen_name} | {len(self.rows)} 条视频')
        self._apply_profile_to_fields(self.profile)
        self._render_rows()

    def _apply_profile_to_fields(self, profile):
        payload = dict(profile or {})
        for field_key, combo in self.profile_fields.items():
            value = str(payload.get(field_key, '') or '').strip()
            index = combo.findText(value)
            combo.setCurrentIndex(index if index >= 0 else 0)
        self._set_profile_editable(not bool(payload.get('profile_confirmed')))

    def _set_profile_editable(self, editable):
        editable = bool(editable)
        for combo in self.profile_fields.values():
            combo.setEnabled(editable)
        self.btn_confirm_profile.setEnabled(editable)
        self.btn_modify_profile.setEnabled(not editable)

    def _collect_profile_payload(self):
        return {
            field_key: combo.currentText().strip()
            for field_key, combo in self.profile_fields.items()
        }

    def confirm_profile(self):
        profile = self._collect_profile_payload()
        missing_labels = [
            label
            for field_key, (label, _options) in QUEEN_PROFILE_FIELD_OPTIONS.items()
            if not profile.get(field_key)
        ]
        if missing_labels:
            QMessageBox.information(self, '提示', f'请先选择：{"、".join(missing_labels)}')
            return
        self.start_async_task(
            lambda: self.backend_client.update_queen_profile(self.queen_name, profile),
            self._on_profile_saved,
            '保存女王基础信息失败',
        )

    def _on_profile_saved(self, result):
        payload = dict(result or {})
        self.profile = dict(payload.get('profile', {}) or {})
        self._apply_profile_to_fields(self.profile)

    def modify_profile(self):
        self._set_profile_editable(True)

    def _render_rows(self):
        self.table.setRowCount(0)
        self.video_metadata_fields.clear()
        for row_index, row_data in enumerate(self.rows):
            self.table.insertRow(row_index)
            values = (
                row_data.get('video_title', ''),
                row_data.get('raw_title', ''),
            )
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, column_index, item)
            record_id = int(row_data.get('id', 0) or 0)
            content_combo = self._build_metadata_combo(
                row_data.get('content_type', ''),
                QUEEN_VIDEO_CONTENT_TYPE_OPTIONS,
            )
            level_combo = self._build_metadata_combo(
                row_data.get('content_level', ''),
                QUEEN_VIDEO_CONTENT_LEVEL_OPTIONS,
            )
            self.video_metadata_fields[record_id] = {
                'content_type': content_combo,
                'content_level': level_combo,
            }
            content_combo.currentTextChanged.connect(
                lambda _text, value=record_id: self.save_video_metadata(value)
            )
            level_combo.currentTextChanged.connect(
                lambda _text, value=record_id: self.save_video_metadata(value)
            )
            self.table.setCellWidget(row_index, 2, content_combo)
            self.table.setCellWidget(row_index, 3, level_combo)
            self.table.setCellWidget(row_index, 4, self._build_delete_button(record_id))

    def _build_metadata_combo(self, current_value, options):
        combo = QComboBox()
        combo.addItem('')
        combo.addItems(list(options))
        value = str(current_value or '').strip()
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.setFixedWidth(86)
        return combo

    def save_video_metadata(self, record_id):
        fields = self.video_metadata_fields.get(int(record_id or 0))
        if not fields:
            return
        content_type = fields['content_type'].currentText().strip()
        content_level = fields['content_level'].currentText().strip()
        self.start_async_task(
            lambda: self.backend_client.update_queen_video_metadata(record_id, content_type, content_level),
            self._on_video_metadata_saved,
            tr('common.operation_failed'),
        )

    def _on_video_metadata_saved(self, result):
        payload = dict(result or {})
        video = dict(payload.get('video', payload) or {})
        record_id = int(video.get('id', 0) or 0)
        for row in self.rows:
            if int((row or {}).get('id', 0) or 0) == record_id:
                row.update({
                    'content_type': str(video.get('content_type', '') or ''),
                    'content_level': str(video.get('content_level', '') or ''),
                })
                break

    def _build_delete_button(self, record_id):
        button = QPushButton(tr('path.viewer.delete'))
        button.clicked.connect(lambda _checked=False, value=record_id: self.delete_video(value))
        return button

    def delete_video(self, record_id):
        answer = QMessageBox.question(self, '确认删除', '确定删除这条视频标题吗？')
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self._reload_after(lambda: self.backend_client.delete_queen_video(record_id)),
            self._on_load_data_finished,
            tr('common.operation_failed'),
        )

    def delete_queen(self):
        answer = QMessageBox.question(self, '确认删除', f'确定删除女王 {self.queen_name} 的全部标题吗？')
        if answer != QMessageBox.Yes:
            return
        self.start_async_task(
            lambda: self.backend_client.delete_queen(self.queen_name),
            self._on_delete_queen_finished,
            tr('common.operation_failed'),
        )

    def _reload_after(self, operation):
        operation()
        return self.backend_client.get_queen_detail_snapshot(self.queen_name, force_refresh=True)

    def _on_delete_queen_finished(self, _result):
        self.accept()


class QueenLibraryWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.queens = []
        self.keywords = []
        self.keyword_window = None
        self.crawl_progress_timer = None
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle('女王库')
        self.resize(1120, 680)
        self.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText('输入关键词后搜索')
        self.btn_search = QPushButton('搜索')
        self.btn_search.clicked.connect(self.search_keyword)
        self.btn_keyword_library = QPushButton('关键词库')
        self.btn_keyword_library.clicked.connect(self.show_keyword_library)
        self.btn_start_crawl = QPushButton('启动抓取')
        self.btn_start_crawl.clicked.connect(self.start_crawl)
        self.btn_refresh = QPushButton(tr('common.refresh'))
        self.btn_refresh.clicked.connect(lambda: self.load_data(force_refresh=True))

        top_layout.addWidget(QLabel('关键词'))
        top_layout.addWidget(self.keyword_input, 1)
        top_layout.addWidget(self.btn_search)
        top_layout.addWidget(self.btn_keyword_library)
        top_layout.addWidget(self.btn_start_crawl)
        top_layout.addWidget(self.btn_refresh)

        self.status_label = QLabel('输入关键词开始搜索')
        self.crawl_progress_timer = QTimer(self)
        self.crawl_progress_timer.setInterval(2000)
        self.crawl_progress_timer.timeout.connect(self.poll_crawl_progress)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setHorizontalSpacing(10)
        self.grid_layout.setVerticalSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.scroll_widget)

        layout.addLayout(top_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
        self.set_async_busy_widgets(
            [self.keyword_input, self.btn_search, self.btn_keyword_library, self.btn_start_crawl, self.btn_refresh]
        )

    def load_data(self, force_refresh=False):
        self.start_async_task(
            lambda: {
                'queens': self.backend_client.list_queen_library_snapshot(force_refresh=force_refresh).get('queens', []),
                'keywords': self.backend_client.list_queen_keywords_snapshot(force_refresh=force_refresh).get('keywords', []),
            },
            self._on_load_data_finished,
            tr('common.read_failed'),
        )

    def _on_load_data_finished(self, result):
        payload = dict(result or {})
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        self.status_label.setText(f'已收录 {len(self.queens)} 位女王，已保存 {len(self.keywords)} 个关键词')
        self._render_queen_buttons()
        if self.keyword_window is not None and self.keyword_window.isVisible():
            self.keyword_window.keywords = list(self.keywords)
            self.keyword_window._render_keyword_buttons()
            self.keyword_window.info_label.setText(f'已保存关键词 {len(self.keywords)} 个')

    def _render_queen_buttons(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, row in enumerate(self.queens):
            queen_name = str((row or {}).get('queen_name', '') or '').strip()
            button = QPushButton(queen_name)
            button.setFixedSize(104, 36)
            if bool((row or {}).get('profile_confirmed', False)):
                button.setStyleSheet('QPushButton { background-color: #238636; color: white; }')
            button.clicked.connect(lambda _checked=False, value=queen_name: self.show_queen_detail(value))
            self.grid_layout.addWidget(button, index // BUTTONS_PER_ROW, index % BUTTONS_PER_ROW)

    def search_keyword(self):
        keyword = self.keyword_input.text().strip()
        if not keyword:
            QMessageBox.information(self, tr('common.prompt'), '请输入关键词')
            return
        existing_keywords = {
            str((row or {}).get('keyword', '') or '').strip()
            for row in self.keywords
            if str((row or {}).get('keyword', '') or '').strip()
        }
        if keyword in existing_keywords:
            QMessageBox.information(self, tr('common.prompt'), '关键词已存在')
            return
        self.start_async_task(
            lambda: self.backend_client.search_queen_keyword(keyword, show_browser=True),
            self._on_search_finished,
            '女王库搜索失败',
        )

    def _on_search_finished(self, result):
        payload = dict(result or {})
        self.keyword_input.clear()
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        self.status_label.setText(
            f'搜索完成：扫描 {int(payload.get("scanned_count", 0) or 0)} 条，'
            f'导入 {int(payload.get("imported_count", 0) or 0)} 条，'
            f'跳过 {int(payload.get("skipped_count", 0) or 0)} 条'
        )
        self._render_queen_buttons()
        if self.keyword_window is not None and self.keyword_window.isVisible():
            self.keyword_window.keywords = list(self.keywords)
            self.keyword_window._render_keyword_buttons()
            self.keyword_window.info_label.setText(f'已保存关键词 {len(self.keywords)} 个')

    def start_crawl(self):
        self.status_label.setText('正在启动批量抓取...')
        self.start_async_task(
            lambda: self.backend_client.refresh_queen_library(show_browser=True),
            self._on_crawl_finished,
            '女王库批量抓取失败',
            block_ui=False,
        )

    def _on_crawl_finished(self, result):
        payload = dict(result or {})
        if 'progress' in payload:
            self._apply_crawl_progress(dict(payload.get('progress', {}) or {}))
            return
        self.queens = sort_queen_rows(payload.get('queens', []) or [])
        self.keywords = list(payload.get('keywords', []) or [])
        log_path = str(payload.get('log_path', '') or '').strip()
        log_text = f'，日志 {log_path}' if log_path else ''
        self.status_label.setText(
            f'批量抓取完成：处理 {int(payload.get("query_count", 0) or 0)} 个搜索词，'
            f'扫描 {int(payload.get("scanned_count", 0) or 0)} 条，'
            f'新增 {int(payload.get("imported_count", 0) or 0)} 条，'
            f'跳过 {int(payload.get("skipped_count", 0) or 0)} 条{log_text}'
        )
        self._render_queen_buttons()
        if self.keyword_window is not None and self.keyword_window.isVisible():
            self.keyword_window.keywords = list(self.keywords)
            self.keyword_window._render_keyword_buttons()
            self.keyword_window.info_label.setText(f'已保存关键词 {len(self.keywords)} 个')

    def poll_crawl_progress(self):
        if self.is_async_task_running():
            return
        self.start_async_task(
            lambda: {'progress': self.backend_client.get_queen_refresh_progress()},
            self._on_crawl_progress_loaded,
            tr('common.read_failed'),
            block_ui=False,
        )

    def _on_crawl_progress_loaded(self, result):
        payload = dict(result or {})
        self._apply_crawl_progress(dict(payload.get('progress', {}) or {}))

    def _apply_crawl_progress(self, progress):
        payload = dict(progress or {})
        if not payload:
            return
        if bool(payload.get('is_running')):
            if self.crawl_progress_timer is not None and not self.crawl_progress_timer.isActive():
                self.crawl_progress_timer.start()
            processed_count = int(payload.get('processed_count', 0) or 0)
            total_count = int(payload.get('total_count', payload.get('query_count', 0)) or 0)
            imported_count = int(payload.get('imported_count', 0) or 0)
            skipped_count = int(payload.get('skipped_count', 0) or 0)
            self.status_label.setText(
                f'批量抓取中：已处理 {processed_count}/{total_count} 个搜索词，'
                f'新增 {imported_count} 条，跳过 {skipped_count} 条'
            )
            return

        if self.crawl_progress_timer is not None and self.crawl_progress_timer.isActive():
            self.crawl_progress_timer.stop()
        if bool(payload.get('failed')):
            self.status_label.setText(str(payload.get('message', '') or payload.get('error', '') or '女王库批量抓取失败'))
            return
        if bool(payload.get('completed')):
            self.queens = sort_queen_rows(payload.get('queens', []) or [])
            self.keywords = list(payload.get('keywords', []) or [])
            processed_count = int(payload.get('processed_count', payload.get('query_count', 0)) or 0)
            total_count = int(payload.get('total_count', payload.get('query_count', 0)) or 0)
            imported_count = int(payload.get('imported_count', 0) or 0)
            skipped_count = int(payload.get('skipped_count', 0) or 0)
            log_path = str(payload.get('log_path', '') or '').strip()
            log_text = f'，日志 {log_path}' if log_path else ''
            self.status_label.setText(
                f'批量抓取完成：处理 {processed_count}/{total_count} 个搜索词，'
                f'新增 {imported_count} 条，跳过 {skipped_count} 条{log_text}'
            )
            self._render_queen_buttons()
            if self.keyword_window is not None and self.keyword_window.isVisible():
                self.keyword_window.keywords = list(self.keywords)
                self.keyword_window._render_keyword_buttons()
                self.keyword_window.info_label.setText(f'已保存关键词 {len(self.keywords)} 个')

    def show_keyword_library(self):
        self.keyword_window = KeywordLibraryWindow(self.backend_client, self)
        self.keyword_window.exec_()

    def show_queen_detail(self, queen_name):
        viewer = QueenDetailWindow(self.backend_client, queen_name, self)
        viewer.exec_()
        self.load_data(force_refresh=True)
