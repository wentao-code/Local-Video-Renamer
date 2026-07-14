import unittest

from app.gui.video_library_sorting import normalize_video_sort_settings, sort_video_rows


class VideoLibrarySortingTest(unittest.TestCase):
    def test_sorts_duration_as_time_value(self):
        rows = [
            {'code': 'A-001', 'duration': '2:00:00'},
            {'code': 'A-002', 'duration': '1:30:00'},
            {'code': 'A-003', 'duration': ''},
        ]

        sorted_rows = sort_video_rows(rows, 'duration', 'asc')

        self.assertEqual([row['code'] for row in sorted_rows], ['A-002', 'A-001', 'A-003'])

    def test_sorts_size_as_number_descending(self):
        rows = [
            {'code': 'A-001', 'size': '0.9'},
            {'code': 'A-002', 'size': '10.2'},
            {'code': 'A-003', 'size': ''},
        ]

        sorted_rows = sort_video_rows(rows, 'size', 'desc')

        self.assertEqual([row['code'] for row in sorted_rows], ['A-002', 'A-001', 'A-003'])

    def test_normalizes_unknown_settings(self):
        self.assertEqual(
            normalize_video_sort_settings({'sort_field': 'unknown', 'sort_order': 'sideways'}),
            {'sort_field': 'code', 'sort_order': 'asc'},
        )


if __name__ == '__main__':
    unittest.main()
