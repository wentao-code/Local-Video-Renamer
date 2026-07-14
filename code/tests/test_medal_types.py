import unittest

from app.core.medal_types import sort_medal_names, sort_medal_rows


class MedalTypeSortingTest(unittest.TestCase):
    def test_sorts_medals_by_configured_type_then_name(self):
        rows = [
            {'name': 'Special', 'medal_type': 'special'},
            {'name': 'Hair', 'medal_type': 'hairstyle'},
            {'name': 'Skin', 'medal_type': 'skin_tone'},
            {'name': 'Body', 'medal_type': 'body'},
            {'name': 'Age', 'medal_type': 'age'},
        ]

        self.assertEqual(
            [row['name'] for row in sort_medal_rows(rows)],
            ['Age', 'Body', 'Skin', 'Hair', 'Special'],
        )
        self.assertEqual(
            sort_medal_names(
                ['Special', 'Hair', 'Skin', 'Body', 'Age'],
                {row['name']: row['medal_type'] for row in rows},
            ),
            ['Age', 'Body', 'Skin', 'Hair', 'Special'],
        )

