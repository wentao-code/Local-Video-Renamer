import unittest
from unittest.mock import Mock, patch

from app.scraper.avfan_scraper import AvfanScraper


class AvfanScraperLoginStateTest(unittest.TestCase):
    def test_search_checks_dedicated_profile_login_state_before_query(self):
        page = Mock()
        scraper = AvfanScraper(headless=False)

        with patch('app.scraper.avfan_scraper.ensure_logged_in_on_home') as ensure_login, \
                patch('app.scraper.avfan_scraper.is_login_page', return_value=False), \
                patch('app.scraper.avfan_scraper.is_security_verification_page', return_value=False), \
                patch('app.scraper.avfan_scraper.can_search_from_current_page', return_value=True), \
                patch('app.scraper.avfan_scraper.accept_age_gate_if_needed'), \
                patch('app.scraper.avfan_scraper.wait_for_security_verification_if_needed'), \
                patch('app.scraper.avfan_scraper.wait_for_manual_login_if_needed'), \
                patch('app.scraper.avfan_scraper.wait_for_page_ready'), \
                patch('app.scraper.avfan_scraper.fill_search_box'), \
                patch('app.scraper.avfan_scraper.click_search_button'), \
                patch('app.scraper.avfan_scraper.collect_search_results', return_value=[]):
            scraper.search_movie_url(page, 'ROE-420')

        ensure_login.assert_called_once_with(page, False)


if __name__ == '__main__':
    unittest.main()
