import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.scraper.avfan_scraper import reset_avfan_browser_profile


class AvfanProfileResetTest(unittest.TestCase):
    def test_default_avfan_profile_directory_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            configured = root / 'browser_profiles' / 'avfan'
            configured.mkdir(parents=True)
            (configured / 'Cookies').write_text('test', encoding='utf-8')

            with patch('app.scraper.avfan_scraper.get_browser_profiles_dir', return_value=root / 'browser_profiles'), \
                    patch('app.scraper.avfan_scraper.get_avfan_profile_dir', return_value=configured):
                result = reset_avfan_browser_profile(configured)

            self.assertTrue(result['reset'])
            self.assertFalse(configured.exists())

    def test_account_profile_directory_is_allowed_but_external_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles = root / 'browser_profiles'
            account_profile = profiles / 'accounts' / '1'
            external = root / 'unrelated'
            account_profile.mkdir(parents=True)
            external.mkdir()

            with patch('app.scraper.avfan_scraper.get_browser_profiles_dir', return_value=profiles), \
                    patch('app.scraper.avfan_scraper.get_avfan_profile_dir', return_value=profiles / 'avfan'):
                result = reset_avfan_browser_profile(account_profile)
                self.assertTrue(result['reset'])
                self.assertFalse(account_profile.exists())
                with self.assertRaisesRegex(ValueError, '拒绝清理'):
                    reset_avfan_browser_profile(external)


if __name__ == '__main__':
    unittest.main()
