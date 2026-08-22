from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.gui.task_log_resolver import TaskLogResolver


class TaskLogViewerWindow(QDialog):
    def __init__(self, record, parent=None, resolver=None):
        super().__init__(parent)
        self.record = record
        self.resolver = resolver or TaskLogResolver()
        self.setWindowTitle('任务日志')
        self.resize(980, 620)

        self.summary_label = QLabel('')
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        self.log_text.setFont(QFont('Consolas', 9))
        self.btn_refresh = QPushButton('刷新')
        self.btn_close = QPushButton('关闭')
        self.btn_refresh.clicked.connect(self.load_logs)
        self.btn_close.clicked.connect(self.close)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_refresh)
        actions.addStretch(1)
        actions.addWidget(self.btn_close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.log_text)
        layout.addLayout(actions)
        self.load_logs()

    @staticmethod
    def _record_value(record, key, default=''):
        if isinstance(record, dict):
            return record.get(key, default)
        return getattr(record, key, default)

    def load_logs(self):
        trace_task_id = str(self._record_value(self.record, 'trace_task_id') or '').strip()
        title = str(self._record_value(self.record, 'title') or '任务').strip()
        explicit_path = self._record_value(self.record, 'log_path')
        result = self.resolver.resolve(trace_task_id, explicit_path)
        self.summary_label.setText(f'{title} | 追踪ID: {trace_task_id or "未设置"}')

        sections = []
        if result['explicit_paths']:
            sections.append('显式日志路径:\n' + '\n'.join(result['explicit_paths']))
        if result['matched_files']:
            sections.append('命中日志文件:\n' + '\n'.join(result['matched_files']))
        if result['lines']:
            sections.append('日志内容:\n' + '\n'.join(
                f"[{item['path']}:{item['line']}] {item['text']}"
                for item in result['lines']
            ))
        else:
            sections.append('未找到包含该追踪 ID 的日志内容。')
        if result['truncated']:
            sections.append('日志内容已达到显示上限，仅显示前 1000 行。')
        if result['errors']:
            sections.append('读取提示:\n' + '\n'.join(result['errors']))
        self.log_text.setPlainText('\n\n'.join(sections))
