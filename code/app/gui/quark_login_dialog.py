"""Quark Pan QR login dialog."""

from __future__ import annotations

import threading

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.services.system.quark_auth_service import QuarkAuthService


STATUS_TEXT = {
    'starting': '正在生成登录二维码...',
    'waiting_scan': '请使用夸克 APP 扫描二维码并确认登录',
    'connected': '夸克网盘登录成功',
    'expired': '二维码已过期，请重新获取',
    'cancelled': '已取消登录',
    'failed': '登录失败，请检查网络后重试',
}


class QuarkLoginWorker(QObject):
    qr_ready = pyqtSignal(bytes)
    status_changed = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, auth_service):
        super().__init__()
        self.auth_service = auth_service
        self.cancel_event = threading.Event()

    @pyqtSlot()
    def run(self):
        result = self.auth_service.login(
            self.cancel_event,
            self.qr_ready.emit,
            self.status_changed.emit,
        )
        self.finished.emit(dict(result or {}))

    def cancel(self):
        self.cancel_event.set()


class QuarkLoginDialog(QDialog):
    def __init__(self, auth_service=None, parent=None, *, auto_start=True):
        super().__init__(parent)
        self.auth_service = auth_service or QuarkAuthService()
        self._thread = None
        self._worker = None
        self._pending_accept = False
        self._pending_close = False
        self._last_result = {}
        self._build_ui()
        if auto_start:
            self.start_login()

    def _build_ui(self):
        self.setWindowTitle('登录夸克网盘')
        self.setModal(True)
        self.setMinimumSize(420, 470)
        self.resize(420, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel('扫码登录夸克网盘')
        title.setAlignment(Qt.AlignCenter)
        font = title.font()
        font.setPointSize(15)
        font.setBold(True)
        title.setFont(font)

        self.qr_label = QLabel('正在生成二维码...')
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(320, 320)
        self.qr_label.setStyleSheet('QLabel { background: white; border: 1px solid #c8c8c8; }')

        self.status_label = QLabel(STATUS_TEXT['starting'])
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(40)

        button_layout = QHBoxLayout()
        self.retry_button = QPushButton('重新获取')
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self.start_login)
        self.cancel_button = QPushButton('取消')
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.cancel_button)

        layout.addWidget(title)
        layout.addWidget(self.qr_label, 0, Qt.AlignHCenter)
        layout.addWidget(self.status_label)
        layout.addLayout(button_layout)

    def start_login(self):
        if self._thread is not None and self._thread.isRunning():
            return False
        self._pending_accept = False
        self._pending_close = False
        self._last_result = {}
        self.retry_button.setEnabled(False)
        self.qr_label.setPixmap(QPixmap())
        self.qr_label.setText('正在生成二维码...')
        self._on_status_changed('starting')

        thread = QThread(self)
        worker = QuarkLoginWorker(self.auth_service)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.qr_ready.connect(self._on_qr_ready)
        worker.status_changed.connect(self._on_status_changed)
        worker.finished.connect(self._on_login_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._on_thread_finished(thread))
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    @pyqtSlot(bytes)
    def _on_qr_ready(self, payload):
        pixmap = QPixmap()
        if not pixmap.loadFromData(bytes(payload or b''), 'PNG'):
            self._on_status_changed('failed')
            self.retry_button.setEnabled(True)
            return
        self.qr_label.setText('')
        self.qr_label.setPixmap(
            pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    @pyqtSlot(str)
    def _on_status_changed(self, status):
        normalized = str(status or 'failed').strip().lower()
        self.status_label.setText(STATUS_TEXT.get(normalized, STATUS_TEXT['failed']))

    @pyqtSlot(dict)
    def _on_login_finished(self, result):
        self._last_result = dict(result or {})
        status = str(self._last_result.get('status', 'failed') or 'failed').strip().lower()
        self._on_status_changed(status)
        if status == 'connected':
            self._pending_accept = True
            if self._thread is None or not self._thread.isRunning():
                self.accept()
            return
        if status != 'cancelled':
            self.retry_button.setEnabled(True)

    def _on_thread_finished(self, thread):
        if self._thread is thread:
            self._thread = None
            self._worker = None
        if self._pending_accept:
            self.accept()
        elif self._pending_close:
            super().reject()
        elif str(self._last_result.get('status', '') or '') != 'cancelled':
            self.retry_button.setEnabled(True)

    def reject(self):
        if self._thread is not None and self._thread.isRunning():
            self._pending_close = True
            self._worker.cancel()
            self.status_label.setText('正在取消登录...')
            self.cancel_button.setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)
