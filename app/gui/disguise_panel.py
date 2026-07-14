from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class NetworkAssistantDisguise(QWidget):
    exit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('networkAssistantDisguise')
        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 5, 6, 5)
        root_layout.setSpacing(4)

        title_bar = QWidget()
        title_bar.setObjectName('disguiseTitleBar')
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 3, 10, 3)
        title_layout.addWidget(QLabel('▣'))
        self.window_title_label = QLabel('网络调试助手')
        self.window_title_label.setAlignment(Qt.AlignCenter)
        title_layout.addWidget(self.window_title_label, 1)
        title_layout.addWidget(QLabel('—  □  ×'))
        root_layout.addWidget(title_bar)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(6)
        content_layout.addWidget(self._build_settings_panel(), 0)
        content_layout.addWidget(self._build_data_panel(), 1)
        root_layout.addLayout(content_layout, 1)

        status_bar = QWidget()
        status_bar.setObjectName('disguiseStatusBar')
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(8, 2, 8, 2)
        status_layout.addWidget(QLabel('☛  就绪!'), 1)
        status_layout.addWidget(QLabel('0/0'), 1, Qt.AlignCenter)
        status_layout.addWidget(QLabel('RX: 0'), 1, Qt.AlignCenter)
        status_layout.addWidget(QLabel('TX: 0'), 1, Qt.AlignCenter)
        status_layout.addWidget(QLabel('复位计数'))
        root_layout.addWidget(status_bar)

        self.setStyleSheet(
            '#networkAssistantDisguise { background: #e7e7e7; color: #161616; font-family: "Microsoft YaHei"; }'
            '#disguiseTitleBar { background: #1687be; border: 1px solid #707070; color: white; }'
            '#disguiseTitleBar QLabel { font-size: 16px; font-weight: 700; }'
            '#disguiseStatusBar { background: #eeeeee; border: 1px solid #8e8e8e; }'
            'QGroupBox { border: 1px solid #9a9a9a; margin-top: 9px; padding: 8px 6px 6px 6px; font-weight: 700; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 7px; padding: 0 3px; }'
            'QLineEdit, QComboBox, QPlainTextEdit, QSpinBox { background: white; border: 1px solid #9a9a9a; min-height: 23px; }'
            'QPushButton { background: #f1f1f1; border: 1px solid #777; min-height: 30px; padding: 2px 12px; }'
            'QPushButton:hover { background: #ffffff; }'
        )

    def _build_settings_panel(self):
        panel = QWidget()
        panel.setFixedWidth(230)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        network_box = QGroupBox('网络设置')
        network_layout = QGridLayout(network_box)
        network_layout.addWidget(QLabel('◎ 协议类型'), 0, 0, 1, 2)
        protocol = QComboBox()
        protocol.addItems(['TCP Server', 'TCP Client', 'UDP'])
        network_layout.addWidget(protocol, 1, 0, 1, 2)
        network_layout.addWidget(QLabel('◎ 本地主机地址'), 2, 0, 1, 2)
        address = QComboBox()
        address.addItem('192.168.7.1')
        network_layout.addWidget(address, 3, 0, 1, 2)
        network_layout.addWidget(QLabel('◎ 本地主机端口'), 4, 0, 1, 2)
        port = QLineEdit('1883')
        network_layout.addWidget(port, 5, 0, 1, 2)
        open_button = QPushButton('打开')
        network_layout.addWidget(QLabel('▣'), 6, 0)
        network_layout.addWidget(open_button, 6, 1)
        layout.addWidget(network_box)

        receive_box = QGroupBox('接收设置')
        receive_layout = QVBoxLayout(receive_box)
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QRadioButton('ASCII'))
        hex_radio = QRadioButton('HEX')
        hex_radio.setChecked(True)
        mode_layout.addWidget(hex_radio)
        receive_layout.addLayout(mode_layout)
        for label, checked in (
            ('按日志模式显示', True),
            ('接收区自动换行', True),
            ('接收数据不显示', False),
            ('接收保存到文件...', False),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(checked)
            receive_layout.addWidget(checkbox)
        links = QHBoxLayout()
        links.addWidget(QLabel('<a href="#">自动滚屏</a>'))
        links.addWidget(QLabel('<a href="#">清除接收</a>'))
        receive_layout.addLayout(links)
        layout.addWidget(receive_box)

        send_box = QGroupBox('发送设置')
        send_layout = QVBoxLayout(send_box)
        send_mode = QHBoxLayout()
        ascii_radio = QRadioButton('ASCII')
        ascii_radio.setChecked(True)
        send_mode.addWidget(ascii_radio)
        send_mode.addWidget(QRadioButton('HEX'))
        send_layout.addLayout(send_mode)
        send_layout.addWidget(QRadioButton('FILE #传输文件'))
        for label, checked in (('自动解析转义符', True), ('自动发送附加位', False)):
            checkbox = QCheckBox(label)
            checkbox.setChecked(checked)
            send_layout.addWidget(checkbox)
        cycle_layout = QHBoxLayout()
        cycle_layout.addWidget(QCheckBox('循环周期'))
        interval = QSpinBox()
        interval.setRange(1, 9999)
        interval.setValue(1000)
        cycle_layout.addWidget(interval)
        cycle_layout.addWidget(QLabel('ms'))
        send_layout.addLayout(cycle_layout)
        send_layout.addWidget(QLabel('<a href="#">快捷指令　 历史发送</a>'))
        layout.addWidget(send_box)
        layout.addStretch(1)
        return panel

    def _build_data_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        log_label = QLabel('数据日志')
        log_label.setStyleSheet('font-weight: 700; border: 1px solid #9a9a9a; padding: 4px 8px; background: #eeeeee;')
        layout.addWidget(log_label)
        receive_log = QPlainTextEdit()
        receive_log.setReadOnly(True)
        receive_log.setMinimumHeight(310)
        layout.addWidget(receive_log, 1)

        send_label = QLabel('数据发送:')
        send_label.setStyleSheet('font-weight: 700; border: 1px solid #9a9a9a; padding: 4px 8px; background: #eeeeee;')
        layout.addWidget(send_label)
        send_layout = QHBoxLayout()
        send_input = QPlainTextEdit('Welcome to NetAssist')
        send_input.setMaximumHeight(76)
        send_layout.addWidget(send_input, 1)
        self.send_button = QPushButton('发送')
        self.send_button.setMinimumSize(104, 76)
        self.send_button.setStyleSheet('QPushButton { color: #14882d; font-size: 18px; font-weight: 700; }')
        self.send_button.clicked.connect(self.exit_requested.emit)
        send_layout.addWidget(self.send_button)
        layout.addLayout(send_layout)
        return panel
