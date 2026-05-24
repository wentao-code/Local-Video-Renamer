from PyQt5.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout


class SummaryCard(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName('summaryCard')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.count_label = QLabel('已补全 0 / 0')
        self.detail_label = QLabel('待补全 0 | 失败 0 | 无结果 0')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.progress_bar)

    def set_summary(self, summary, show_terminal_details=True):
        total_count = int(summary.get('total_count', 0) or 0)
        enriched_count = int(summary.get('enriched_count', 0) or 0)
        pending_count = int(summary.get('pending_count', 0) or 0)
        failed_count = int(summary.get('failed_count', 0) or 0)
        no_search_count = int(summary.get('no_search_count', 0) or 0)
        progress_percent = float(summary.get('progress_percent', 0) or 0)
        count_label = str(summary.get('count_label', '') or '已补全')
        pending_label = str(summary.get('pending_label', '') or '待补全')

        self.title_label.setText(str(summary.get('label', '')))
        self.count_label.setText(f'{count_label} {enriched_count} / {total_count}')
        if show_terminal_details:
            self.detail_label.setText(
                f'{pending_label} {pending_count} | 失败 {failed_count} | 无结果 {no_search_count}'
            )
        else:
            self.detail_label.setText(f'{pending_label} {pending_count}')
        self.progress_bar.setFormat(f'{progress_percent:.1f}%')
        self.progress_bar.setValue(int(progress_percent * 10))
