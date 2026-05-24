from PyQt5.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class TaskProgressWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.title_label = QLabel('')
        self.detail_label = QLabel('')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.progress_bar)

    def reset(self, hide_widget=False):
        self.title_label.setText('')
        self.detail_label.setText('')
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('0/0 | 0.0%')
        if hide_widget:
            self.hide()

    def set_progress(
        self,
        title,
        processed_count,
        total_count,
        success_count,
        failed_count,
        progress_percent,
        count_unit='项',
        current_item='',
        message='',
    ):
        count_unit = str(count_unit or '项').strip() or '项'
        title_text = str(title or '').strip() or '子任务'
        detail_segments = []
        if current_item:
            detail_segments.append(f'当前: {current_item}')
        if message:
            detail_segments.append(str(message))

        self.title_label.setText(title_text)
        self.detail_label.setText(' | '.join(detail_segments))
        self.progress_bar.setValue(int(float(progress_percent or 0) * 10))
        if int(total_count or 0) > 0:
            self.progress_bar.setFormat(
                f'{int(processed_count or 0)}/{int(total_count or 0)} {count_unit} | '
                f'成功 {int(success_count or 0)} | 失败 {int(failed_count or 0)} | '
                f'{float(progress_percent or 0):.1f}%'
            )
        else:
            self.progress_bar.setFormat(message or '准备中...')
        self.show()
