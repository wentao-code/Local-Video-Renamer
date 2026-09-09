from app.scraper.avfan_scraper import AvfanScraper
from app.services.auth.account_service import (
    AccountService,
    ACCOUNT_STATUS_BLOCKED,
    ACCOUNT_STATUS_ERROR,
    ACCOUNT_STATUS_LOGGED_IN,
    ACCOUNT_STATUS_LOGGED_OUT,
)
from app.scraper.login_status_service import ensure_logged_in_on_home


class AutoLoginService:
    def __init__(self, scraper=None, account=None, database=None):
        self.account = dict(account or {})
        profile_dir = self.account.get('profile_dir')
        self.scraper = scraper or AvfanScraper(headless=False, profile_dir=profile_dir)
        self.database = database

    def run(self):
        if self.database and self.account.get('account_id'):
            remaining_seconds = AccountService.manual_verification_cooldown_remaining(self.account)
            if remaining_seconds:
                return {
                    'success': False,
                    'status': 'verification_required',
                    'message': f'人工验证冷却中，剩余约 {remaining_seconds} 秒，期间不会刷新或访问该账号页面。',
                    'auto_login_triggered': False,
                    'current_url': '',
                }
        self.scraper.open_session()
        page = self.scraper.get_page(self.scraper._context)
        try:
            result = ensure_logged_in_on_home(
                page,
                headless=False,
                username=self.account.get('username'),
                password=self.account.get('password'),
            )
            status = result.get('status', '')
            normalized_status = ACCOUNT_STATUS_LOGGED_IN if status in {'logged_in', '已登录'} else (
                ACCOUNT_STATUS_BLOCKED if status in {'verification_required', '需人工验证'} else ACCOUNT_STATUS_LOGGED_OUT
            )
            if self.database and self.account.get('account_id'):
                self.database.set_scraper_account_status(
                    self.account['account_id'],
                    normalized_status,
                    '' if normalized_status == ACCOUNT_STATUS_LOGGED_IN else result.get('message', ''),
                )
                if normalized_status == ACCOUNT_STATUS_BLOCKED:
                    AccountService(self.database).start_manual_verification_cooldown(self.account['account_id'])
            return {
                'success': True,
                'message': result.get('message', '已完成登录状态检查。'),
                'status': result.get('status', ''),
                'auto_login_triggered': bool(result.get('auto_login_triggered')),
                'current_url': page.url,
            }
        except Exception as exc:
            if self.database and self.account.get('account_id'):
                is_manual_verification = AccountService._is_manual_verification_error(exc)
                self.database.set_scraper_account_status(
                    self.account['account_id'],
                    ACCOUNT_STATUS_BLOCKED if is_manual_verification else ACCOUNT_STATUS_ERROR,
                    str(exc),
                )
                if is_manual_verification:
                    AccountService(self.database).start_manual_verification_cooldown(self.account['account_id'])
            raise
        finally:
            self.scraper.close_session()
