import unittest
from unittest.mock import MagicMock, patch

from app.queen_library import standard_reference_scraper


class StandardReferenceScraperTest(unittest.TestCase):
    def test_builds_page_urls_preserving_forum_style_query(self):
        self.assertEqual(
            standard_reference_scraper.build_forum_page_url(1),
            'http://www.aicaiaicai.com/forum.php?mod=forumdisplay&fid=109&forumdefstyle=yes&page=1',
        )
        self.assertEqual(
            standard_reference_scraper.build_forum_page_url(5),
            'http://www.aicaiaicai.com/forum.php?mod=forumdisplay&fid=109&forumdefstyle=yes&page=5',
        )

    def test_parse_forum_rows_keeps_author_title_and_absolute_thread_link(self):
        records = standard_reference_scraper.parse_forum_rows(
            [{
                'title': '【调教视频】【双子】旁站主页预览 - [售价 3 彩币]',
                'href': 'forum.php?mod=viewthread&tid=123',
            }],
            2,
        )

        self.assertEqual(records[0]['author_name'], '双子')
        self.assertEqual(records[0]['video_title'], '旁站主页预览')
        self.assertEqual(records[0]['thread_url'], 'http://www.aicaiaicai.com/forum.php?mod=viewthread&tid=123')
        self.assertEqual(records[0]['page_number'], 2)

    def test_uses_saved_chrome_profile_for_visible_persistent_context(self):
        scraper = standard_reference_scraper.StandardReferenceScraper(profile_dir='saved-profile')
        context = MagicMock()
        page = MagicMock()
        context.pages = [page]
        playwright = MagicMock()
        playwright.chromium.launch_persistent_context.return_value = context
        manager = MagicMock()
        manager.start.return_value = playwright
        manager.__exit__.side_effect = lambda *_args: context.close()
        factory = MagicMock(return_value=manager)

        with (
            patch.object(standard_reference_scraper, 'get_scraper_locale', return_value='zh-CN'),
            patch.object(scraper, 'playwright_factory', factory),
        ):
            with scraper.session() as opened_page:
                self.assertIs(opened_page, page)

        playwright.chromium.launch_persistent_context.assert_called_once_with(
            'saved-profile',
            channel='chrome',
            headless=False,
            locale='zh-CN',
            viewport={'width': 1440, 'height': 1000},
        )
        context.close.assert_called_once()
        manager.__exit__.assert_called_once_with(None, None, None)

    def test_default_playwright_factory_starts_sync_playwright_manager(self):
        scraper = standard_reference_scraper.StandardReferenceScraper(profile_dir='saved-profile')
        context = MagicMock()
        page = MagicMock()
        context.pages = [page]
        playwright = MagicMock()
        playwright.chromium.launch_persistent_context.return_value = context
        manager = MagicMock()
        manager.start.return_value = playwright
        manager.__exit__.side_effect = lambda *_args: context.close()
        sync_playwright = MagicMock(return_value=manager)

        with (
            patch.object(standard_reference_scraper, 'get_scraper_locale', return_value='zh-CN'),
            patch.object(standard_reference_scraper, 'import_sync_playwright', return_value=sync_playwright),
        ):
            with scraper.session() as opened_page:
                self.assertIs(opened_page, page)

        sync_playwright.assert_called_once_with()
        manager.start.assert_called_once_with()
        manager.__exit__.assert_called_once_with(None, None, None)


if __name__ == '__main__':
    unittest.main()
