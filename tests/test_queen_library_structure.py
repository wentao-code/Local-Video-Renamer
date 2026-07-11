import importlib
import unittest


class QueenLibraryStructureTest(unittest.TestCase):
    def test_queen_library_modules_live_in_dedicated_package(self):
        expected_modules = (
            'app.queen_library.domain',
            'app.queen_library.scraper',
            'app.queen_library.service',
            'app.queen_library.sorting',
            'app.queen_library.viewer',
        )

        for module_name in expected_modules:
            with self.subTest(module_name=module_name):
                module = importlib.import_module(module_name)
                self.assertEqual(module.__name__, module_name)


if __name__ == '__main__':
    unittest.main()
