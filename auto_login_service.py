from avfan_scraper import AvfanScraper
from login_status_service import ensure_logged_in_on_home


class AutoLoginService:
    def __init__(self, scraper=None):
        self.scraper = scraper or AvfanScraper(headless=False)

    def run(self):
        with self.scraper.session() as page:
            result = ensure_logged_in_on_home(page, headless=False)
            return {
                'success': True,
                'message': result.get('message', '已完成登录状态检查。'),
                'status': result.get('status', ''),
                'auto_login_triggered': bool(result.get('auto_login_triggered')),
                'current_url': page.url,
            }
