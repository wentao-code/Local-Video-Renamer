from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from app.services.auth.account_service import AccountService


class AccountValidationWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend_client):
        super().__init__()
        self.backend_client = backend_client

    def run(self):
        try:
            self.finished.emit(self.backend_client.validate_scraper_accounts())
        except Exception as exc:
            self.failed.emit(str(exc))


class AccountBatchOperationWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend_client, account_ids, operation):
        super().__init__()
        self.backend_client = backend_client
        self.account_ids = [int(account_id) for account_id in account_ids]
        self.operation = operation

    def run(self):
        results = []
        for account_id in self.account_ids:
            try:
                if self.operation == 'login':
                    result = self.backend_client.auto_login(account_id)
                else:
                    result = self.backend_client.reset_browser_profile(account_id)
                results.append({'account_id': account_id, 'success': True, 'result': result})
            except Exception as exc:
                results.append({'account_id': account_id, 'success': False, 'error': str(exc)})
        self.finished.emit({'operation': self.operation, 'results': results})


class AccountManagerDialog(QDialog):
    def __init__(self, database, backend_client=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.backend_client = backend_client
        self.validation_thread = None
        self.validation_worker = None
        self._active_button = None
        self._operation = ''
        self.setWindowTitle('抓取账号管理')
        self.resize(760, 360)
        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['选择', '账号', '用户名', '登录状态', '最近检测', '异常原因', '启用', 'profile'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        actions = QHBoxLayout()
        add_button = QPushButton('新增账号')
        add_button.clicked.connect(self.add_account)
        toggle_button = QPushButton('启用/禁用')
        toggle_button.clicked.connect(self.toggle_account)
        validate_button = QPushButton('校验账号池')
        validate_button.clicked.connect(self.validate_accounts)
        login_button = QPushButton('自动登录')
        login_button.clicked.connect(self.login_selected_accounts)
        reset_button = QPushButton('重置网页登录')
        reset_button.clicked.connect(self.reset_selected_accounts)
        edit_button = QPushButton('编辑账号')
        edit_button.clicked.connect(self.edit_account)
        actions.addWidget(add_button)
        actions.addWidget(edit_button)
        actions.addWidget(toggle_button)
        actions.addWidget(validate_button)
        actions.addWidget(login_button)
        actions.addWidget(reset_button)
        actions.addStretch()
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        layout.addWidget(close_buttons)
        self.reload()

    def validate_accounts(self):
        if self.backend_client is None:
            return
        if self.validation_thread is not None:
            return
        self._start_operation(self.sender(), 'validate', AccountValidationWorker(self.backend_client))

    def login_selected_accounts(self):
        account_ids = self.checked_account_ids()
        if not account_ids:
            QMessageBox.information(self, '自动登录', '请先勾选要登录的账号。')
            return
        self._start_operation(
            self.sender(),
            'login',
            AccountBatchOperationWorker(self.backend_client, account_ids, 'login'),
        )

    def reset_selected_accounts(self):
        account_ids = self.checked_account_ids()
        if not account_ids:
            QMessageBox.information(self, '重置网页登录', '请先勾选要重置的账号。')
            return
        answer = QMessageBox.question(
            self,
            '重置网页登录',
            f'将重置 {len(account_ids)} 个账号的专用浏览器登录状态，是否继续？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._start_operation(
            self.sender(),
            'reset',
            AccountBatchOperationWorker(self.backend_client, account_ids, 'reset'),
        )

    def _start_operation(self, button, operation, worker):
        if self.backend_client is None or self.validation_thread is not None:
            return
        self._active_button = button
        self._operation = operation
        self._active_button.setEnabled(False)
        self._active_button.setText('正在处理…')
        self.validation_thread = QThread(self)
        self.validation_worker = worker
        self.validation_worker.moveToThread(self.validation_thread)
        self.validation_thread.started.connect(self.validation_worker.run)
        if operation == 'validate':
            self.validation_worker.finished.connect(self._validation_finished)
        else:
            self.validation_worker.finished.connect(self._batch_operation_finished)
        self.validation_worker.failed.connect(self._operation_failed)
        self.validation_worker.finished.connect(self.validation_thread.quit)
        self.validation_worker.failed.connect(self.validation_thread.quit)
        self.validation_thread.finished.connect(self._cleanup_validation)
        self.validation_thread.start()

    def _validation_finished(self, payload):
        self.reload()
        results = (payload or {}).get('results', [])
        blocked = [row for row in results if row.get('status') == '需人工验证']
        failed = [row for row in results if row.get('status') == '检测失败']
        summary = f'已完成 {len(results)} 个账号校验。'
        if blocked:
            summary += f'\n需人工验证：{len(blocked)} 个。'
        if failed:
            summary += f'\n检测失败：{len(failed)} 个。'
        QMessageBox.information(self, '账号校验完成', summary)

    def _batch_operation_finished(self, payload):
        self.reload()
        results = (payload or {}).get('results', [])
        failed = [row for row in results if not row.get('success')]
        operation_name = '自动登录' if payload.get('operation') == 'login' else '重置网页登录'
        summary = f'{operation_name}已处理 {len(results)} 个账号。成功 {len(results) - len(failed)} 个，失败 {len(failed)} 个。'
        if failed:
            summary += '\n' + '\n'.join(
                f"账号 {row['account_id']}：{row.get('error', '操作失败')}" for row in failed
            )
        QMessageBox.information(self, f'{operation_name}完成', summary)

    def _operation_failed(self, message):
        QMessageBox.critical(self, '账号操作失败', message)

    def _cleanup_validation(self):
        if self._active_button is not None:
            self._active_button.setEnabled(True)
            self._active_button.setText({
                'validate': '校验账号池',
                'login': '自动登录',
                'reset': '重置网页登录',
            }.get(self._operation, '处理'))
        if self.validation_worker is not None:
            self.validation_worker.deleteLater()
        if self.validation_thread is not None:
            self.validation_thread.deleteLater()
        self.validation_worker = None
        self.validation_thread = None
        self._active_button = None
        self._operation = ''

    def reload(self):
        rows = self.database.list_scraper_accounts()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get('account_name', ''),
                row.get('username', ''),
                row.get('login_status', '未检测'),
                row.get('last_checked_at', ''),
                row.get('last_error', ''),
                '是' if row.get('enabled') else '否',
                row.get('profile_dir', ''),
            ]
            checkbox = QCheckBox()
            checkbox.setProperty('account_id', int(row.get('account_id') or 0))
            checkbox.setStyleSheet('QCheckBox { margin-left: 8px; }')
            self.table.setCellWidget(row_index, 0, checkbox)
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value or ''))
                item.setData(32, row.get('account_id'))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()

    def selected_account_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 1) is None:
            return 0
        return int(self.table.item(row, 1).data(32) or 0)

    def checked_account_ids(self):
        account_ids = []
        for row_index in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row_index, 0)
            if checkbox is not None and checkbox.isChecked():
                account_ids.append(int(checkbox.property('account_id') or 0))
        return [account_id for account_id in account_ids if account_id > 0]

    def add_account(self):
        values = self._account_credentials_dialog('新增账号')
        if values:
            AccountService(self.database).create_account(**values)
            self.reload()

    def _account_credentials_dialog(self, title, account=None):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        name_edit = QLineEdit(str((account or {}).get('account_name') or ''))
        username_edit = QLineEdit(str((account or {}).get('username') or ''))
        password_edit = QLineEdit(str((account or {}).get('password') or ''))
        password_edit.setEchoMode(QLineEdit.Password)
        form.addRow('账号名称', name_edit)
        form.addRow('用户名/邮箱', username_edit)
        form.addRow('密码', password_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return None
        values = {
            'account_name': str(name_edit.text() or '').strip(),
            'username': str(username_edit.text() or '').strip(),
            'password': str(password_edit.text() or ''),
        }
        if not values['account_name'] or not values['username'] or not values['password']:
            QMessageBox.warning(self, title, '账号名称、用户名和密码都不能为空。')
            return None
        return values

    def toggle_account(self):
        account_id = self.selected_account_id()
        account = self.database.get_scraper_account(account_id) if account_id else None
        if account:
            self.database.update_scraper_account(account_id, enabled=0 if account.get('enabled') else 1)
            self.reload()

    def edit_account(self):
        account_id = self.selected_account_id()
        account = self.database.get_scraper_account(account_id) if account_id else None
        if not account:
            return
        values = self._account_credentials_dialog('编辑账号', account)
        if values:
            self.database.update_scraper_account(account_id, **values)
            self.reload()
