import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.queen_library import standard_reference_browser


class StandardReferenceBrowserTest(unittest.TestCase):
    def test_forum_login_url_uses_requested_forum_display_style(self):
        self.assertEqual(
            standard_reference_browser.STANDARD_REFERENCE_URL,
            'http://www.aicaiaicai.com/forum.php?mod=forumdisplay&fid=109&forumdefstyle=yes',
        )

    def test_login_opens_google_chrome_with_dedicated_persistent_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / 'browser_profiles' / 'aicai_standard_reference'
            chrome_path = Path(temp_dir) / 'chrome.exe'
            with (
                patch.object(standard_reference_browser, 'STANDARD_REFERENCE_PROFILE_DIR', profile_dir),
                patch.object(standard_reference_browser, 'find_google_chrome', return_value=chrome_path),
                patch.object(standard_reference_browser.subprocess, 'Popen') as popen,
            ):
                result = standard_reference_browser.open_standard_reference_login()
                self.assertEqual(result, profile_dir)
                popen.assert_called_once_with(
                    [
                        str(chrome_path),
                        f'--user-data-dir={profile_dir}',
                        '--new-window',
                        standard_reference_browser.STANDARD_REFERENCE_URL,
                    ],
                    close_fds=True,
                )
                self.assertTrue(profile_dir.is_dir())

    def test_login_reports_missing_chrome_without_starting_process(self):
        with (
            patch.object(standard_reference_browser, 'find_google_chrome', return_value=None),
            patch.object(standard_reference_browser.subprocess, 'Popen') as popen,
        ):
            with self.assertRaises(FileNotFoundError):
                standard_reference_browser.open_standard_reference_login()

        popen.assert_not_called()

    def test_detects_active_profile_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / 'profile'
            profile_dir.mkdir()
            lock_path = profile_dir / 'SingletonLock'
            lock_path.touch()
            with patch.object(standard_reference_browser, 'STANDARD_REFERENCE_PROFILE_DIR', profile_dir):
                self.assertTrue(standard_reference_browser.is_standard_reference_browser_open())

    def test_missing_profile_lock_means_browser_is_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                standard_reference_browser,
                'STANDARD_REFERENCE_PROFILE_DIR',
                Path(temp_dir) / 'missing-profile',
            ):
                self.assertFalse(standard_reference_browser.is_standard_reference_browser_open())


if __name__ == '__main__':
    unittest.main()
