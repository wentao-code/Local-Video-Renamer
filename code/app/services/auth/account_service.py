from pathlib import Path
import uuid
from datetime import datetime
import time

from app.core.project_paths import BROWSER_PROFILES_DIR


ACCOUNT_STATUS_UNKNOWN = '未检测'
ACCOUNT_STATUS_LOGGED_IN = '已登录'
ACCOUNT_STATUS_LOGGED_OUT = '未登录'
ACCOUNT_STATUS_BLOCKED = '需人工验证'
ACCOUNT_STATUS_ERROR = '检测失败'
MANUAL_VERIFICATION_COOLDOWN_SECONDS = 3 * 60


def build_account_profile_dir(account_id):
    normalized = int(account_id or 0)
    if normalized <= 0:
        raise ValueError('账号 ID 无效')
    return BROWSER_PROFILES_DIR / 'accounts' / str(normalized)


class AccountService:
    def __init__(self, database):
        self.database = database

    def list_accounts(self, enabled_only=False):
        return self.database.list_scraper_accounts(enabled_only=enabled_only)

    def create_account(self, account_name, username='', password=''):
        name = str(account_name or '').strip()
        if not name:
            raise ValueError('账号名称不能为空')
        # The row is created first so its ID becomes the stable profile directory name.
        account = self.database.create_scraper_account(
            name,
            str(BROWSER_PROFILES_DIR / 'accounts' / f'pending-{uuid.uuid4().hex}'),
            username=username,
            password=password,
        )
        profile_dir = build_account_profile_dir(account['account_id'])
        return self.database.update_scraper_account(
            account['account_id'],
            profile_dir=str(profile_dir),
        )

    def update_account(self, account_id, **changes):
        return self.database.update_scraper_account(account_id, **changes)

    def get_account(self, account_id):
        return self.database.get_scraper_account(account_id)

    def close_validation_session(self, account_id):
        return AccountValidationService.close_session(account_id)

    def start_manual_verification_cooldown(self, account_id, now=None):
        timestamp = time.time() if now is None else float(now)
        return self.database.set_scraper_account_manual_verification_cooldown(
            account_id,
            timestamp + MANUAL_VERIFICATION_COOLDOWN_SECONDS,
        )

    @staticmethod
    def manual_verification_cooldown_remaining(account, now=None):
        timestamp = time.time() if now is None else float(now)
        cooldown_until = float((account or {}).get('manual_verification_until') or 0)
        return max(0, int(cooldown_until - timestamp))

    def require_usable_account(self, account_id):
        account = self.get_account(account_id)
        if account is None:
            raise ValueError('未找到绑定的抓取账号')
        if not bool(account.get('enabled')):
            raise ValueError('绑定的抓取账号已禁用')
        status = str(account.get('login_status') or ACCOUNT_STATUS_UNKNOWN)
        if status != ACCOUNT_STATUS_LOGGED_IN:
            raise ValueError(f"账号当前不可抓取：{status}")
        return account

    def validate_accounts(self):
        results = []
        accounts = self.database.list_scraper_accounts(enabled_only=False)
        for account in accounts:
            started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            remaining_seconds = self.manual_verification_cooldown_remaining(account)
            if remaining_seconds:
                status = ACCOUNT_STATUS_BLOCKED
                message = f'人工验证冷却中，剩余约 {remaining_seconds} 秒，期间不会刷新或访问该账号页面。'
                updated = self.database.record_scraper_account_check(
                    account['account_id'],
                    status,
                    message=message,
                    started_at=started_at,
                )
                results.append({
                    'account_id': account['account_id'],
                    'account_name': account.get('account_name', ''),
                    'status': status,
                    'message': message,
                    'current_url': '',
                    'account': updated,
                })
                continue
            try:
                result = AccountValidationService(self.database).check_account(account)
                status = self._normalize_check_status(result.get('status'))
                message = result.get('message', '')
                current_url = result.get('current_url', '')
            except Exception as exc:
                status = ACCOUNT_STATUS_BLOCKED if self._is_manual_verification_error(exc) else ACCOUNT_STATUS_ERROR
                message = str(exc)
                current_url = ''
            if status == ACCOUNT_STATUS_BLOCKED:
                self.start_manual_verification_cooldown(account['account_id'])
            finished_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            updated = self.database.record_scraper_account_check(
                account['account_id'],
                status,
                message=message,
                current_url=current_url,
                started_at=started_at,
                finished_at=finished_at,
            )
            results.append({
                'account_id': account['account_id'],
                'account_name': account.get('account_name', ''),
                'status': status,
                'message': message,
                'current_url': current_url,
                'account': updated,
            })
        return results

    @staticmethod
    def _normalize_check_status(status):
        normalized = str(status or '').strip()
        if normalized in {'logged_in', ACCOUNT_STATUS_LOGGED_IN}:
            return ACCOUNT_STATUS_LOGGED_IN
        if normalized in {'verification_required', ACCOUNT_STATUS_BLOCKED}:
            return ACCOUNT_STATUS_BLOCKED
        if normalized in {'logged_out', ACCOUNT_STATUS_LOGGED_OUT}:
            return ACCOUNT_STATUS_LOGGED_OUT
        return ACCOUNT_STATUS_ERROR

    @staticmethod
    def _is_manual_verification_error(error):
        message = str(error or '').lower()
        return any(marker in message for marker in ('真人', '验证码', 'captcha', 'cloudflare', 'verification'))


class AccountValidationService:
    _active_sessions = {}

    def __init__(self, database):
        self.database = database

    @classmethod
    def close_session(cls, account_id):
        account_key = int(account_id or 0)
        scraper = cls._active_sessions.pop(account_key, None)
        if scraper is not None:
            scraper.close_session()
        return scraper is not None

    def check_account(self, account):
        from app.scraper.avfan_scraper import AvfanScraper
        from app.scraper.login_status_service import (
            LOGIN_STATUS_VERIFICATION_REQUIRED,
            detect_home_login_status,
        )

        account_id = int(account.get('account_id') or 0)
        scraper = self._active_sessions.get(account_id)
        if scraper is None:
            scraper = AvfanScraper(headless=False, profile_dir=account.get('profile_dir'))
            self._active_sessions[account_id] = scraper
        page = scraper.open_session()
        keep_open = False
        try:
            status = detect_home_login_status(
                page,
                scraper.home_url,
                headless=False,
                wait_for_verification=False,
            )
            keep_open = status == LOGIN_STATUS_VERIFICATION_REQUIRED
            return {
                'status': status,
                'message': {
                    'logged_in': '检测到当前已经登录。',
                    'logged_out': '检测到当前未登录。',
                    'unknown': '无法确认当前登录状态。',
                    LOGIN_STATUS_VERIFICATION_REQUIRED: '检测到当前账号需要人工验证，浏览器窗口已保留。',
                }.get(status, '已完成账号状态检测。'),
                'current_url': page.url,
            }
        finally:
            if not keep_open:
                scraper.close_session()
                self._active_sessions.pop(account_id, None)
