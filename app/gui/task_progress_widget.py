from PyQt5.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from app.gui.i18n import tr


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
        count_unit=None,
        current_item='',
        message='',
    ):
        count_unit = str(count_unit or tr('task_progress.count_unit_default')).strip() or tr('task_progress.count_unit_default')
        title_text = str(title or '').strip() or tr('common.subtask')
        detail_segments = []
        if current_item:
            detail_segments.append(tr('common.current', value=current_item))
        if message:
            detail_segments.append(str(message))

        self.title_label.setText(title_text)
        self.detail_label.setText(' | '.join(detail_segments))
        self.progress_bar.setValue(int(float(progress_percent or 0) * 10))
        if int(total_count or 0) > 0:
            self.progress_bar.setFormat(
                tr(
                    'task_progress.progress_format',
                    processed_count=int(processed_count or 0),
                    total_count=int(total_count or 0),
                    count_unit=count_unit,
                    success_count=int(success_count or 0),
                    failed_count=int(failed_count or 0),
                    progress_percent=float(progress_percent or 0),
                )
            )
        else:
            self.progress_bar.setFormat(message or tr('common.preparing'))
        self.show()
