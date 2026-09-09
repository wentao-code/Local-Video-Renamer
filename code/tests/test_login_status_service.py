import unittest

from app.scraper.login_status_service import (
    LOGIN_STATUS_VERIFICATION_REQUIRED,
    detect_home_login_status,
    is_security_verification_page,
)


class _Locator:
    def __init__(self, text=''):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text

    def count(self):
        return 0


class _VerificationPage:
    url = 'https://avfan.com/zh-CN/user/settings'

    def __init__(self, text):
        self.text = text

    def title(self):
        return 'avfan.com'

    def locator(self, selector):
        return _Locator(self.text)

    def goto(self, *args, **kwargs):
        return None


class LoginStatusServiceTest(unittest.TestCase):
    def test_chinese_cloudflare_verification_page_is_detected(self):
        page = _VerificationPage(
            '正在进行安全验证\n本网站使用安全服务防护恶意自动程序。'
            '在验证您不是自动程序期间，将显示此页面。\nCloudflare'
        )

        self.assertTrue(is_security_verification_page(page))
        self.assertEqual(
            detect_home_login_status(
                page,
                'https://avfan.com/zh-CN',
                headless=False,
                wait_for_verification=False,
            ),
            LOGIN_STATUS_VERIFICATION_REQUIRED,
        )


if __name__ == '__main__':
    unittest.main()
