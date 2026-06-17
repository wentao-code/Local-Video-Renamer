from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from app.gui.i18n import tr
from app.services.video_category_service import (
    VIDEO_CATEGORY_COLLECTION,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_SINGLE,
)


class VideoCategoryBatchActionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._uncategorized_count = 0

        self.info_label = QLabel()
        self.combo = QComboBox()
        self.combo.addItem(tr('code_prefix.detail.category_batch_placeholder'), '')
        for category in (VIDEO_CATEGORY_CO_STAR, VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_COLLECTION):
            self.combo.addItem(category, category)

        self.apply_button = QPushButton(tr('code_prefix.detail.category_batch_apply'))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(self.info_label)
        layout.addStretch()
        layout.addWidget(self.combo)
        layout.addWidget(self.apply_button)

        self.combo.currentIndexChanged.connect(self._update_button_state)
        self._update_info_label()
        self._update_button_state()

    def selected_category(self):
        return str(self.combo.currentData() or '').strip()

    def set_uncategorized_count(self, count):
        self._uncategorized_count = max(0, int(count or 0))
        self._update_info_label()
        self._update_button_state()

    def set_busy(self, busy):
        is_busy = bool(busy)
        self.combo.setEnabled(not is_busy)
        self._update_button_state(disabled_by_busy=is_busy)

    def _update_info_label(self):
        self.info_label.setText(
            tr('code_prefix.detail.category_batch_count', count=self._uncategorized_count)
        )

    def _update_button_state(self, *_args, disabled_by_busy=False):
        self.apply_button.setEnabled(
            (not disabled_by_busy)
            and self._uncategorized_count > 0
            and bool(self.selected_category())
        )
