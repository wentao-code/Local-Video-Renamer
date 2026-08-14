import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.subtitle_candidate_dialog import SubtitleCandidateDialog


_APP = QApplication.instance() or QApplication([])


class SubtitleCandidateDialogTest(unittest.TestCase):
    def test_select_all_and_clear_selection_toggle_all_candidates(self):
        dialog = SubtitleCandidateDialog([
            {'video_code': 'RCTD-001', 'video_path': 'first.mp4'},
            {'video_code': 'RCTD-002', 'video_path': 'second.mp4'},
        ])

        self.assertEqual(dialog.selected_codes(), ['RCTD-001', 'RCTD-002'])

        dialog.clear_selection()
        self.assertEqual(dialog.selected_codes(), [])

        dialog.select_all()
        self.assertEqual(dialog.selected_codes(), ['RCTD-001', 'RCTD-002'])


if __name__ == '__main__':
    unittest.main()
