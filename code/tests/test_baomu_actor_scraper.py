import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.scraper.baomu_actor_scraper import BaomuActorScraper
from app.scraper.browser_window import minimize_browser_window_if_needed


class BaomuActorScraperParseProfileTest(unittest.TestCase):
    def test_open_session_times_out_when_playwright_runtime_start_hangs(self):
        manager = MagicMock()
        playwright = MagicMock()

        def delayed_start():
            time.sleep(0.2)
            return playwright

        manager.start.side_effect = delayed_start
        sync_playwright = MagicMock(return_value=manager)

        with (
            patch('app.scraper.baomu_actor_scraper.import_sync_playwright', return_value=sync_playwright),
            patch('app.scraper.baomu_actor_scraper.get_operation_timeout_milliseconds', return_value=20),
        ):
            scraper = BaomuActorScraper(headless=True)
            started_at = time.perf_counter()
            with self.assertRaisesRegex(TimeoutError, '浏览器启动超时'):
                scraper.open_session()

        self.assertLess(time.perf_counter() - started_at, 0.15)

    def test_open_session_uses_configured_browser_launch_timeout(self):
        manager = MagicMock()
        playwright = manager.start.return_value
        browser = playwright.chromium.launch.return_value
        context = browser.new_context.return_value
        context.new_page.return_value = MagicMock()
        sync_playwright = MagicMock(return_value=manager)

        with (
            patch('app.scraper.baomu_actor_scraper.import_sync_playwright', return_value=sync_playwright),
            patch('app.scraper.baomu_actor_scraper.get_scraper_browser_channel', return_value='chrome'),
            patch('app.scraper.baomu_actor_scraper.get_operation_timeout_milliseconds', return_value=12000),
        ):
            scraper = BaomuActorScraper(headless=True)
            scraper.open_session()

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            channel='chrome',
            timeout=12000,
        )

    def test_open_session_creates_playwright_session_on_calling_thread(self):
        scraper = BaomuActorScraper(headless=True)
        calling_thread_id = threading.get_ident()
        session_thread_ids = []

        with patch.object(scraper, '_probe_playwright_start'):
            with patch.object(
                scraper,
                '_open_session_impl',
                side_effect=lambda: session_thread_ids.append(threading.get_ident()) or object(),
            ):
                scraper.open_session()

        self.assertEqual(session_thread_ids, [calling_thread_id])

    def test_minimize_browser_window_minimizes_visible_browser_sessions(self):
        page = MagicMock()
        cdp_session = page.context.new_cdp_session.return_value
        cdp_session.send.return_value = {'windowId': 7}

        minimize_browser_window_if_needed(page, headless=False)

        page.context.new_cdp_session.assert_called_once_with(page)
        cdp_session.send.assert_any_call('Browser.getWindowForTarget')
        cdp_session.send.assert_any_call(
            'Browser.setWindowBounds',
            {'windowId': 7, 'bounds': {'windowState': 'minimized'}},
        )

    def test_minimize_browser_window_skips_headless_sessions(self):
        page = MagicMock()

        minimize_browser_window_if_needed(page, headless=True)

        page.context.new_cdp_session.assert_not_called()

    def test_parse_profile_reads_embedded_next_data_and_normalizes_actor_fields(self):
        next_payload = {
            "props": {
                "pageProps": {
                    "actress": {
                        "name": "一松愛梨",
                        "birthday": "1984-05-20",
                        "breast": "101cm",
                        "cup": "G",
                        "height": "171cm",
                        "hip": "93cm",
                        "waist": "63cm",
                    }
                }
            }
        }
        html = (
            "<html><body>"
            f"<script id='__NEXT_DATA__' type='application/json'>{json.dumps(next_payload, ensure_ascii=False)}</script>"
            "</body></html>"
        )

        profile = BaomuActorScraper.parse_profile_html(html)

        self.assertEqual(profile["actor_name"], "一松愛梨")
        self.assertEqual(profile["birthday"], "1984-05-20")
        self.assertEqual(profile["height"], "171")
        self.assertEqual(profile["bust"], "101")
        self.assertEqual(profile["waist"], "63")
        self.assertEqual(profile["hip"], "93")
        self.assertEqual(profile["cup"], "G")
        self.assertEqual(profile["measurements_raw"], "breast=101cm; waist=63cm; hip=93cm; cup=G")

    def test_parse_profile_reads_live_style_initial_state_branch(self):
        next_payload = {
            "props": {
                "initialState": {
                    "all": {
                        "actress": {
                            "name": "一松愛梨",
                            "birthday": "1984-05-20",
                            "breast": "101cm",
                            "cup": "G",
                            "height": "171cm",
                            "hip": "93cm",
                            "waist": "63cm",
                        }
                    }
                }
            }
        }
        html = (
            "<html><body>"
            f"<script id='__NEXT_DATA__' type='application/json'>{json.dumps(next_payload, ensure_ascii=False)}</script>"
            "</body></html>"
        )

        profile = BaomuActorScraper.parse_profile_html(html)

        self.assertEqual(profile["actor_name"], "一松愛梨")
        self.assertEqual(profile["birthday"], "1984-05-20")
        self.assertEqual(profile["height"], "171")
        self.assertEqual(profile["bust"], "101")
        self.assertEqual(profile["waist"], "63")
        self.assertEqual(profile["hip"], "93")
        self.assertEqual(profile["cup"], "G")
        self.assertEqual(profile["measurements_raw"], "breast=101cm; waist=63cm; hip=93cm; cup=G")

    def test_parse_profile_allows_bust_values_with_cup_suffix(self):
        next_payload = {
            "props": {
                "pageProps": {
                    "actress": {
                        "name": "Actor Cup",
                        "birthday": "",
                        "breast": "84cm (D)",
                        "height": "",
                        "hip": "",
                        "waist": "",
                    }
                }
            }
        }
        html = (
            "<script id='__NEXT_DATA__' type='application/json'>"
            f"{json.dumps(next_payload, ensure_ascii=False)}"
            "</script>"
        )

        profile = BaomuActorScraper.parse_profile_html(html)

        self.assertEqual(profile["bust"], "84")
        self.assertEqual(profile["cup"], "D")
        self.assertEqual(profile["measurements_raw"], "breast=84cm (D)")

    def test_parse_profile_normalizes_trailing_dash_birthday(self):
        next_payload = {
            "props": {
                "initialState": {
                    "all": {
                        "actress": {
                            "name": "伊東千春",
                            "birthday": "1989-03-29-",
                            "breast": "97cm",
                            "waist": "64cm",
                            "hip": "98cm",
                        }
                    }
                }
            }
        }
        html = (
            "<script id='__NEXT_DATA__' type='application/json'>"
            f"{json.dumps(next_payload, ensure_ascii=False)}"
            "</script>"
        )

        profile = BaomuActorScraper.parse_profile_html(html)

        self.assertEqual(profile["birthday"], "1989-03-29")


if __name__ == "__main__":
    unittest.main()
