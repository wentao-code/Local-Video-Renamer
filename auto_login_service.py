from app_config import get_setting
from avfan_scraper import (
    AvfanScraper,
    accept_age_gate_if_needed,
    wait_for_manual_login_if_needed,
    wait_for_page_ready,
    wait_for_security_verification_if_needed,
)


class AutoLoginService:
    def __init__(self, scraper=None):
        self.login_url = get_setting('SCRAPER_LOGIN_URL', required=True)
        self.username = get_setting('SCRAPER_USERNAME', required=True)
        self.password = get_setting('SCRAPER_PASSWORD', required=True)
        self.scraper = scraper or AvfanScraper(headless=False)

    def run(self):
        with self.scraper.session() as page:
            page.goto(self.login_url, wait_until='domcontentloaded', timeout=60000)
            wait_for_security_verification_if_needed(page, headless=False)
            accept_age_gate_if_needed(page)
            wait_for_security_verification_if_needed(page, headless=False)
            wait_for_page_ready(page)
            fill_login_form(page, self.username, self.password)
            wait_for_manual_login_if_needed(page, headless=False)
            wait_for_page_ready(page)
            return {
                'success': True,
                'message': '已自动填入账号密码，并检测到登录成功。',
                'current_url': page.url,
            }


def fill_login_form(page, username, password):
    username_selectors = (
        'input[name="email"]',
        'input[name="login"]',
        'input[type="email"]',
        'input[placeholder*="邮箱"]',
        'input[placeholder*="用户名"]',
        'input[placeholder*="example@example.com"]',
        'input[type="text"]',
    )
    password_selectors = (
        'input[type="password"]',
        'input[name="password"]',
    )

    fill_first_visible(page, username_selectors, username, '未找到邮箱或用户名输入框')
    fill_first_visible(page, password_selectors, password, '未找到密码输入框')


def fill_first_visible(page, selectors, value, error_message):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1500):
                locator.click()
                locator.fill(value)
                return
        except Exception:
            continue
    raise RuntimeError(error_message)
