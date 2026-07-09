import unittest

from app.gui.queen_library_sorting import sort_queen_rows


class QueenLibrarySortingTest(unittest.TestCase):
    def test_sorts_queen_rows_by_normalized_initial(self):
        rows = [
            {'queen_name': '小鱼'},
            {'queen_name': 'AIU'},
            {'queen_name': 'baby敏儿'},
            {'queen_name': '白一晗'},
            {'queen_name': '一茶'},
            {'queen_name': 'ccs'},
            {'queen_name': '【安霖瑶】 第一视角'},
        ]

        sorted_rows = sort_queen_rows(rows)

        self.assertEqual(
            [row['queen_name'] for row in sorted_rows],
            ['AIU', 'baby敏儿', 'ccs', '【安霖瑶】 第一视角', '白一晗', '小鱼', '一茶'],
        )


if __name__ == '__main__':
    unittest.main()
