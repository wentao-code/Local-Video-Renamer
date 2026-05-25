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
        self.live_label = QLabel('')
        self.live_label.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.live_label)
        layout.addWidget(self.progress_bar)

    def set_summary(self, summary, show_terminal_details=True, live_progress=None):
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
            self.detail_label.setText(f'{pending_label} {pending_count} | 失败 {failed_count} | 无结果 {no_search_count}')
        else:
            self.detail_label.setText(f'{pending_label} {pending_count}')

        display_percent = progress_percent
        if live_progress:
            live_total_count = int(live_progress.get('total_count', 0) or 0)
            live_processed_count = int(live_progress.get('processed_count', 0) or 0)
            live_success_count = int(live_progress.get('success_count', 0) or 0)
            live_failed_count = int(live_progress.get('failed_count', 0) or 0)
            live_count_unit = str(live_progress.get('count_unit', '') or '项')
            live_message = str(live_progress.get('message', '') or '')
            current_item = str(live_progress.get('current_item', '') or '')

            progress_delta = min(max(live_processed_count, 0), max(pending_count, 0))
            if total_count > 0:
                display_percent = round(((enriched_count + progress_delta) / total_count) * 100.0, 1)

            segments = [f'当前任务 {live_processed_count}/{live_total_count} {live_count_unit}']
            segments.append(f'成功 {live_success_count}')
            segments.append(f'失败 {live_failed_count}')
            if current_item:
                segments.append(f'当前: {current_item}')
            elif live_message:
                segments.append(live_message)
            self.live_label.setText(' | '.join(segments))
            self.live_label.show()
        else:
            self.live_label.hide()
            self.live_label.setText('')

        self.progress_bar.setFormat(f'{display_percent:.1f}%')
        self.progress_bar.setValue(int(display_percent * 10))
