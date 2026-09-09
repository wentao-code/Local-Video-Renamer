import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.data.database_handler import VideoDatabase
from app.gui.account_viewer import AccountBatchOperationWorker, AccountManagerDialog
from app.services.auth.account_service import AccountService, AccountValidationService


_APP = QApplication.instance() or QApplication([])


class ScraperAccountTest(unittest.TestCase):
    def test_accounts_have_isolated_profiles_and_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            accounts = database.list_scraper_accounts()
            self.assertEqual(len(accounts), 1)
            default = accounts[0]
            created = AccountService(database).create_account('账号二')

            self.assertNotEqual(default['profile_dir'], created['profile_dir'])
            self.assertTrue(created['profile_dir'].endswith(str(created['account_id'])))

            updated = database.set_scraper_account_status(created['account_id'], '已登录')
            self.assertEqual(updated['login_status'], '已登录')
            self.assertTrue(updated['last_checked_at'])

    def test_account_stores_individual_login_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            account = AccountService(database).create_account(
                '账号二', username='account-two@example.com', password='secret-two'
            )

            self.assertEqual(account['username'], 'account-two@example.com')
            self.assertEqual(account['password'], 'secret-two')

    def test_auto_login_passes_selected_account_credentials(self):
        from app.services.auth.auto_login_service import AutoLoginService

        scraper = Mock()
        scraper._context = object()
        scraper.get_page.return_value = Mock(url='https://example.test/user/settings')
        account = {
            'account_id': 1,
            'profile_dir': 'profile-1',
            'username': 'account-one@example.com',
            'password': 'secret-one',
        }
        with patch('app.services.auth.auto_login_service.ensure_logged_in_on_home', return_value={
            'status': 'logged_in', 'message': '已登录', 'auto_login_triggered': False,
        }) as ensure_login:
            AutoLoginService(scraper=scraper, account=account).run()

        ensure_login.assert_called_once_with(
            scraper.get_page.return_value,
            headless=False,
            username='account-one@example.com',
            password='secret-one',
        )

    def test_disabled_or_not_logged_in_account_is_not_usable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            service = AccountService(database)
            account = database.list_scraper_accounts()[0]

            with self.assertRaisesRegex(ValueError, '不可抓取'):
                service.require_usable_account(account['account_id'])

            database.update_scraper_account(account['account_id'], enabled=0)
            with self.assertRaisesRegex(ValueError, '已禁用'):
                service.require_usable_account(account['account_id'])

    def test_account_check_history_is_recorded_without_changing_other_domains(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            account = database.list_scraper_accounts()[0]

            updated = database.record_scraper_account_check(
                account['account_id'],
                '已登录',
                message='检测到当前已经登录。',
                current_url='https://example.test/user/settings',
                started_at='2026-09-07 10:00:00',
                finished_at='2026-09-07 10:00:02',
            )

            self.assertEqual(updated['login_status'], '已登录')
            self.assertEqual(updated['last_error'], '')
            history = database.list_scraper_account_check_history(account['account_id'])
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]['status'], '已登录')
            self.assertEqual(history[0]['current_url'], 'https://example.test/user/settings')

    def test_validate_accounts_checks_all_enabled_accounts_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            second = AccountService(database).create_account('账号二')
            database.update_scraper_account(second['account_id'], enabled=1)

            results = [
                {'status': '已登录', 'message': '已登录', 'current_url': 'https://example.test/user/settings'},
                RuntimeError('检测超时'),
            ]

            def fake_check(account):
                result = results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            with patch('app.services.auth.account_service.AccountValidationService.check_account', side_effect=fake_check):
                checked = AccountService(database).validate_accounts()

            self.assertEqual([item['account_id'] for item in checked], [1, second['account_id']])
            self.assertEqual(checked[0]['status'], '已登录')
            self.assertEqual(checked[1]['status'], '检测失败')
            self.assertEqual(database.get_scraper_account(second['account_id'])['login_status'], '检测失败')

    def test_validate_accounts_includes_disabled_accounts_in_account_pool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            second = AccountService(database).create_account('禁用账号')
            database.update_scraper_account(second['account_id'], enabled=0)

            with patch(
                'app.services.auth.account_service.AccountValidationService.check_account',
                return_value={'status': 'logged_out', 'message': '未登录', 'current_url': 'https://example.test/login'},
            ):
                checked = AccountService(database).validate_accounts()

            self.assertEqual(len(checked), 2)
            self.assertEqual(database.get_scraper_account(second['account_id'])['login_status'], '未登录')

    def test_account_manager_uses_checkboxes_for_selected_account_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            second = AccountService(database).create_account('账号二')
            dialog = AccountManagerDialog(database)
            dialog.table.cellWidget(0, 0).setChecked(True)
            dialog.table.cellWidget(1, 0).setChecked(True)

            self.assertEqual(dialog.checked_account_ids(), [1, second['account_id']])
            self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), '选择')
            dialog.close()

    def test_account_manager_adds_account_with_individual_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            dialog = AccountManagerDialog(database)
            with patch.object(dialog, '_account_credentials_dialog', return_value={
                'account_name': '账号二',
                'username': 'account-two@example.com',
                'password': 'secret-two',
            }):
                dialog.add_account()

            account = database.list_scraper_accounts()[1]
            self.assertEqual(account['username'], 'account-two@example.com')
            self.assertEqual(account['password'], 'secret-two')
            self.assertEqual(dialog.table.columnCount(), 8)
            self.assertEqual(dialog.table.horizontalHeaderItem(2).text(), '用户名')
            dialog.close()

    def test_batch_login_continues_after_a_selected_account_fails(self):
        calls = []

        class Client:
            def auto_login(self, account_id):
                calls.append(account_id)
                if account_id == 2:
                    raise RuntimeError('验证码超时')
                return {'status': 'logged_in'}

        worker = AccountBatchOperationWorker(Client(), [1, 2, 3], 'login')
        payloads = []
        worker.finished.connect(payloads.append)
        worker.run()

        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual([row['success'] for row in payloads[0]['results']], [True, False, True])

    def test_reset_closes_retained_manual_verification_session_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            account = database.list_scraper_accounts()[0]
            scraper = type('Scraper', (), {'close_session': Mock()})()
            AccountValidationService._active_sessions[account['account_id']] = scraper

            service = AccountService(database)
            service.close_validation_session(account['account_id'])

            scraper.close_session.assert_called_once_with()
            self.assertNotIn(account['account_id'], AccountValidationService._active_sessions)

    def test_manual_verification_cooldown_blocks_refresh_for_three_minutes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            account = database.list_scraper_accounts()[0]
            database.set_scraper_account_manual_verification_cooldown(
                account['account_id'],
                cooldown_until=2000,
            )

            with patch('app.services.auth.account_service.time.time', return_value=1900), \
                    patch('app.services.auth.account_service.AccountValidationService.check_account') as check_account:
                result = AccountService(database).validate_accounts()

            check_account.assert_not_called()
            self.assertEqual(result[0]['status'], '需人工验证')
            self.assertIn('冷却', result[0]['message'])

    def test_auto_login_does_not_open_browser_during_manual_verification_cooldown(self):
        from app.services.auth.auto_login_service import AutoLoginService

        with tempfile.TemporaryDirectory() as temp_dir:
            database = VideoDatabase(Path(temp_dir) / 'accounts.db')
            account = database.list_scraper_accounts()[0]
            database.set_scraper_account_manual_verification_cooldown(
                account['account_id'],
                cooldown_until=2000,
            )
            current_account = database.get_scraper_account(account['account_id'])
            scraper = Mock()

            with patch('app.services.auth.account_service.time.time', return_value=1900):
                result = AutoLoginService(scraper=scraper, account=current_account, database=database).run()

            self.assertFalse(result['success'])
            self.assertEqual(result['status'], 'verification_required')
            self.assertIn('冷却', result['message'])
            scraper.open_session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
