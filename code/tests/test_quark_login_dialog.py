import os
from io import BytesIO

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import qrcode
from PyQt5.QtWidgets import QApplication, QDialog

from app.gui.quark_login_dialog import QuarkLoginDialog, QuarkLoginWorker


_APP = QApplication.instance() or QApplication([])


class FakeAuthService:
    def __init__(self, result=None):
        self.result = result or {'status': 'connected'}

    def login(self, cancel_event, qr_callback, status_callback):
        if cancel_event.is_set():
            return {'status': 'cancelled'}
        qr_callback(_qr_png())
        status_callback('waiting_scan')
        return dict(self.result)


def _qr_png():
    image = qrcode.make('https://example.invalid/qr')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def test_dialog_renders_qr_and_accepts_only_validated_success():
    dialog = QuarkLoginDialog(FakeAuthService(), auto_start=False)

    dialog._on_qr_ready(_qr_png())
    dialog._on_status_changed('waiting_scan')

    assert dialog.qr_label.pixmap() is not None
    assert not dialog.qr_label.pixmap().isNull()
    assert '扫描' in dialog.status_label.text()
    assert dialog.result() != QDialog.Accepted

    dialog._on_login_finished({'status': 'connected'})

    assert dialog.result() == QDialog.Accepted


def test_expired_login_keeps_dialog_open_and_enables_retry():
    dialog = QuarkLoginDialog(FakeAuthService(), auto_start=False)

    dialog._on_login_finished({'status': 'expired'})

    assert dialog.result() != QDialog.Accepted
    assert dialog.retry_button.isEnabled()
    assert '过期' in dialog.status_label.text()


def test_worker_cancel_sets_the_shared_cancellation_event():
    worker = QuarkLoginWorker(FakeAuthService())

    worker.cancel()

    assert worker.cancel_event.is_set()
