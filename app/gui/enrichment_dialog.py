import json

from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
)
from app.core.enrichment_targets import (
    ACTOR_LIBRARY_TARGET,
    CODE_PREFIX_LIBRARY_TARGET,
    VIDEO_LIBRARY_TARGET,
)
from app.core.project_paths import ENRICHMENT_SETTINGS_FILE


DEFAULT_SETTINGS = {
    'limit': 5,
    'show_browser': False,
    'cooldown_before_search': False,
    'batch_limit': 5,
    'batch_interval_minutes': 30,
    'target_type': VIDEO_LIBRARY_TARGET,
    'source_key': DEFAULT_VIDEO_ENRICHMENT_SOURCE,
}


def load_saved_settings():
    settings = dict(DEFAULT_SETTINGS)
    if ENRICHMENT_SETTINGS_FILE.exists():
        try:
            loaded = json.loads(ENRICHMENT_SETTINGS_FILE.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                settings.update(loaded)
        except Exception:
            pass
    return settings


def save_saved_settings(settings):
    current = load_saved_settings()
    current.update(settings)
    ENRICHMENT_SETTINGS_FILE.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


class EnrichmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.action_mode = 'single'
        self.setWindowTitle('补全信息')
        self.init_ui()
        self.apply_settings(load_saved_settings())

    def init_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        target_group = QGroupBox('抓取目标')
        target_layout = QHBoxLayout()
        self.target_button_group = QButtonGroup(self)
        self.target_button_group.setExclusive(True)

        self.video_target_button = QRadioButton('视频库')
        self.code_prefix_target_button = QRadioButton('番号库')
        self.actor_target_button = QRadioButton('演员库')

        self.target_button_group.addButton(self.video_target_button)
        self.target_button_group.addButton(self.code_prefix_target_button)
        self.target_button_group.addButton(self.actor_target_button)

        target_layout.addWidget(self.video_target_button)
        target_layout.addWidget(self.code_prefix_target_button)
        target_layout.addWidget(self.actor_target_button)
        target_layout.addStretch()
        target_group.setLayout(target_layout)

        source_group = QGroupBox('视频库补全来源')
        source_layout = QHBoxLayout()
        self.source_button_group = QButtonGroup(self)
        self.source_button_group.setExclusive(True)
        self.avfan_source_button = QRadioButton('天陨阁')
        self.javtxt_source_button = QRadioButton('辛聚谷')
        self.javtxt_source_button.setToolTip('辛聚谷用于补全视频标题、演员与第二套视频 ID。')
        self.source_button_group.addButton(self.avfan_source_button)
        self.source_button_group.addButton(self.javtxt_source_button)
        source_layout.addWidget(self.avfan_source_button)
        source_layout.addWidget(self.javtxt_source_button)
        source_layout.addStretch()
        source_group.setLayout(source_layout)
        self.source_group = source_group

        self.video_target_button.toggled.connect(self.update_source_controls)
        self.code_prefix_target_button.toggled.connect(self.update_source_controls)
        self.actor_target_button.toggled.connect(self.update_source_controls)

        self.limit_input = QSpinBox()
        self.limit_input.setRange(1, 999999)
        self.limit_input.setValue(DEFAULT_SETTINGS['limit'])

        self.batch_limit_input = QSpinBox()
        self.batch_limit_input.setRange(1, 999999)
        self.batch_limit_input.setValue(DEFAULT_SETTINGS['batch_limit'])

        self.interval_minutes_input = QSpinBox()
        self.interval_minutes_input.setRange(1, 1440)
        self.interval_minutes_input.setValue(DEFAULT_SETTINGS['batch_interval_minutes'])
        self.interval_minutes_input.setSuffix(' 分钟')

        self.show_browser_checkbox = QCheckBox('显示浏览器窗口')
        self.show_browser_checkbox.setChecked(DEFAULT_SETTINGS['show_browser'])

        self.cooldown_checkbox = QCheckBox('冷却 3 分钟后再搜索')
        self.cooldown_checkbox.setChecked(DEFAULT_SETTINGS['cooldown_before_search'])

        form_layout.addRow('本次补全数量:', self.limit_input)
        form_layout.addRow('每批补全数量:', self.batch_limit_input)
        form_layout.addRow('批次间隔:', self.interval_minutes_input)
        form_layout.addRow('', self.show_browser_checkbox)
        form_layout.addRow('', self.cooldown_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.batch_button = buttons.addButton('分批补全', QDialogButtonBox.ActionRole)
        self.save_button = buttons.addButton('保存配置', QDialogButtonBox.ActionRole)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setText('开始补全')

        buttons.accepted.connect(self.accept_single)
        buttons.rejected.connect(self.reject)
        self.batch_button.clicked.connect(self.accept_batch)
        self.save_button.clicked.connect(self.save_settings)

        layout.addWidget(target_group)
        layout.addWidget(source_group)
        layout.addLayout(form_layout)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def selected_target_type(self):
        if self.code_prefix_target_button.isChecked():
            return CODE_PREFIX_LIBRARY_TARGET
        if self.actor_target_button.isChecked():
            return ACTOR_LIBRARY_TARGET
        return VIDEO_LIBRARY_TARGET

    def selected_source_key(self):
        if self.selected_target_type() != VIDEO_LIBRARY_TARGET:
            return AVFAN_VIDEO_SOURCE
        if self.javtxt_source_button.isChecked():
            return JAVTXT_VIDEO_SOURCE
        return AVFAN_VIDEO_SOURCE

    def values(self):
        return {
            'limit': self.limit_input.value(),
            'batch_limit': self.batch_limit_input.value(),
            'batch_interval_minutes': self.interval_minutes_input.value(),
            'show_browser': self.show_browser_checkbox.isChecked(),
            'cooldown_before_search': self.cooldown_checkbox.isChecked(),
            'target_type': self.selected_target_type(),
            'source_key': self.selected_source_key(),
        }

    def apply_settings(self, settings):
        limit = self._to_bounded_int(
            settings.get('limit', DEFAULT_SETTINGS['limit']),
            DEFAULT_SETTINGS['limit'],
            self.limit_input.minimum(),
            self.limit_input.maximum(),
        )
        batch_limit = self._to_bounded_int(
            settings.get('batch_limit', DEFAULT_SETTINGS['batch_limit']),
            DEFAULT_SETTINGS['batch_limit'],
            self.batch_limit_input.minimum(),
            self.batch_limit_input.maximum(),
        )
        interval = self._to_bounded_int(
            settings.get('batch_interval_minutes', DEFAULT_SETTINGS['batch_interval_minutes']),
            DEFAULT_SETTINGS['batch_interval_minutes'],
            self.interval_minutes_input.minimum(),
            self.interval_minutes_input.maximum(),
        )
        target_type = settings.get('target_type', VIDEO_LIBRARY_TARGET)
        source_key = settings.get('source_key', DEFAULT_VIDEO_ENRICHMENT_SOURCE)

        self.limit_input.setValue(limit)
        self.batch_limit_input.setValue(batch_limit)
        self.interval_minutes_input.setValue(interval)
        self.show_browser_checkbox.setChecked(bool(settings.get('show_browser', DEFAULT_SETTINGS['show_browser'])))
        self.cooldown_checkbox.setChecked(
            bool(settings.get('cooldown_before_search', DEFAULT_SETTINGS['cooldown_before_search']))
        )

        self.video_target_button.setChecked(target_type == VIDEO_LIBRARY_TARGET)
        self.code_prefix_target_button.setChecked(target_type == CODE_PREFIX_LIBRARY_TARGET)
        self.actor_target_button.setChecked(target_type == ACTOR_LIBRARY_TARGET)
        if not any(button.isChecked() for button in (
            self.video_target_button,
            self.code_prefix_target_button,
            self.actor_target_button,
        )):
            self.video_target_button.setChecked(True)

        self.avfan_source_button.setChecked(source_key != JAVTXT_VIDEO_SOURCE)
        self.javtxt_source_button.setChecked(source_key == JAVTXT_VIDEO_SOURCE)
        self.update_source_controls()

    def update_source_controls(self):
        is_video_target = self.selected_target_type() == VIDEO_LIBRARY_TARGET
        self.source_group.setEnabled(is_video_target)
        if not is_video_target:
            self.avfan_source_button.setChecked(True)

    def accept_single(self):
        self.action_mode = 'single'
        self.accept()

    def accept_batch(self):
        self.action_mode = 'batch'
        self.accept()

    def save_settings(self):
        try:
            save_saved_settings(self.values())
        except Exception as exc:
            QMessageBox.critical(self, '保存失败', f'无法保存补全配置：\n{exc}')
            return

        QMessageBox.information(
            self,
            '保存成功',
            f'补全配置已保存到：\n{ENRICHMENT_SETTINGS_FILE}',
        )

    @staticmethod
    def _to_bounded_int(value, fallback, minimum, maximum):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = fallback
        return max(minimum, min(parsed, maximum))
