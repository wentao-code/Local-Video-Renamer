import unittest

from app.gui.queen_library_sorting import sort_queen_rows


class QueenLibrarySortingTest(unittest.TestCase):
    def test_sorts_queen_rows_by_normalized_initial(self):
        rows = [
            {'queen_name': 'Xiaoyu'},
            {'queen_name': 'AIU'},
            {'queen_name': 'babyMin'},
            {'queen_name': 'Yicha'},
            {'queen_name': 'ccs'},
            {'queen_name': '[Annie] first view'},
        ]

        sorted_rows = sort_queen_rows(rows)

        self.assertEqual(
            [row['queen_name'] for row in sorted_rows],
            ['AIU', '[Annie] first view', 'babyMin', 'ccs', 'Xiaoyu', 'Yicha'],
        )

    def test_sorts_empty_like_level_first_then_by_rank_then_name(self):
        rows = [
            {'queen_name': 'Delta', 'like_level': 'B'},
            {'queen_name': 'Alpha', 'like_level': ''},
            {'queen_name': 'Charlie', 'like_level': 'A'},
            {'queen_name': 'Beta', 'like_level': ''},
            {'queen_name': 'Echo', 'like_level': 'D'},
            {'queen_name': 'Bravo', 'like_level': 'A'},
            {'queen_name': 'Foxtrot', 'like_level': 'C'},
        ]

        sorted_rows = sort_queen_rows(rows)

        self.assertEqual(
            [row['queen_name'] for row in sorted_rows],
            ['Alpha', 'Beta', 'Bravo', 'Charlie', 'Delta', 'Foxtrot', 'Echo'],
        )


if __name__ == '__main__':
    unittest.main()
