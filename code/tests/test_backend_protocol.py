import tempfile
import unittest
from pathlib import Path

from app.core.backend_protocol import build_backend_code_fingerprint


class BackendProtocolTest(unittest.TestCase):
    def test_queen_library_backend_changes_invalidate_reusable_backend_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scraper_path = Path(temp_dir) / 'app' / 'queen_library' / 'scraper.py'
            scraper_path.parent.mkdir(parents=True)
            scraper_path.write_text('VERSION = 1\n', encoding='utf-8')

            original_fingerprint = build_backend_code_fingerprint(temp_dir)
            scraper_path.write_text('VERSION = 2\n', encoding='utf-8')

            updated_fingerprint = build_backend_code_fingerprint(temp_dir)

        self.assertNotEqual(original_fingerprint, updated_fingerprint)


if __name__ == '__main__':
    unittest.main()
