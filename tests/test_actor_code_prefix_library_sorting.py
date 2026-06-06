import unittest

from app.gui.actor_library_sorting import normalize_actor_sort_settings, sort_actor_rows
from app.gui.code_prefix_library_sorting import (
    normalize_code_prefix_sort_settings,
    sort_code_prefix_rows,
)


class ActorLibrarySortingTest(unittest.TestCase):
    def test_sorts_age_as_number(self):
        rows = [
            {'name': '演员A', 'age': '9'},
            {'name': '演员B', 'age': '21'},
            {'name': '演员C', 'age': ''},
        ]

        sorted_rows = sort_actor_rows(rows, 'age', 'desc')

        self.assertEqual([row['name'] for row in sorted_rows], ['演员B', '演员A', '演员C'])

    def test_normalizes_unknown_settings(self):
        self.assertEqual(
            normalize_actor_sort_settings({'sort_field': 'unknown', 'sort_order': 'bad'}),
            {'sort_field': 'name', 'sort_order': 'asc'},
        )


class CodePrefixLibrarySortingTest(unittest.TestCase):
    def test_sorts_counts_as_numbers(self):
        rows = [
            {'prefix': 'ABC', 'video_count': '9'},
            {'prefix': 'DEF', 'video_count': '21'},
            {'prefix': 'GHI', 'video_count': ''},
        ]

        sorted_rows = sort_code_prefix_rows(rows, 'video_count', 'desc')

        self.assertEqual([row['prefix'] for row in sorted_rows], ['DEF', 'ABC', 'GHI'])

    def test_normalizes_unknown_settings(self):
        self.assertEqual(
            normalize_code_prefix_sort_settings({'sort_field': 'unknown', 'sort_order': 'bad'}),
            {'sort_field': 'prefix', 'sort_order': 'asc'},
        )


if __name__ == '__main__':
    unittest.main()
