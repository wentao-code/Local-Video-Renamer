from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)


class EnrichmentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('补全信息')
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.limit_input = QSpinBox()
        self.limit_input.setRange(1, 100)
        self.limit_input.setValue(5)
        self.limit_input.setToolTip('首次建议 1-3 个，网页抓取会比较慢。')

        self.show_browser_checkbox = QCheckBox('显示浏览器窗口')
        self.show_browser_checkbox.setChecked(False)

        form_layout.addRow('本次补全数量:', self.limit_input)
        form_layout.addRow('', self.show_browser_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form_layout)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def values(self):
        return {
            'limit': self.limit_input.value(),
            'show_browser': self.show_browser_checkbox.isChecked(),
        }
