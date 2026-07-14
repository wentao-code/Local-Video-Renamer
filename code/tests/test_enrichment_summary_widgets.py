import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.enrichment_summary_widgets import SummaryCard, SummaryIssueDialog


_APP = QApplication.instance() or QApplication([])


class EnrichmentSummaryWidgetsTest(unittest.TestCase):
    def test_summary_card_keeps_existing_title_when_summary_label_is_missing(self):
        card = SummaryCard('Initial title')
        try:
            card.set_summary({})
            self.assertEqual(card.title_label.text(), 'Initial title')
        finally:
            card.deleteLater()

    def test_binghuo_summary_card_uses_split_missing_labels_and_enables_list_button(self):
        card = SummaryCard('Actor Library · Binghuo')
        try:
            card.set_summary(
                {
                    'label': 'Actor Library · Binghuo',
                    'total_count': 10,
                    'enriched_count': 7,
                    'success_count': 3,
                    'pending_count': 1,
                    'failed_count': 0,
                    'no_search_count': 2,
                    'missing_age_count': 1,
                    'missing_measurements_count': 2,
                    'missing_height_count': 1,
                    'issue_groups': [
                        {'key': 'no_search', 'label': 'No Search', 'items': [{'name': 'Actor A'}]},
                        {'key': 'missing_age', 'label': 'Missing Age', 'items': [{'name': 'Actor B'}]},
                    ],
                    'list_kind': 'actor',
                }
            )

            self.assertIn('1', card.detail_label.text())
            self.assertIn('2', card.detail_label.text())
            self.assertTrue(card.list_button.isEnabled())
        finally:
            card.deleteLater()

    def test_summary_issue_dialog_builds_tabs_and_columns_from_issue_groups(self):
        dialog = SummaryIssueDialog(
            'Video Library · JAVTXT',
            'video',
            [
                {
                    'key': 'no_search',
                    'label': 'No Search',
                    'items': [{'code': 'ROE-001', 'title': 'Title A', 'author': 'Actor A'}],
                },
                {
                    'key': 'no_detail',
                    'label': 'No Detail',
                    'items': [{'code': 'ROE-002', 'title': 'Title B', 'author': 'Actor B'}],
                },
            ],
        )
        try:
            self.assertEqual(dialog.tab_widget.count(), 2)
            self.assertEqual(dialog.tab_widget.tabText(0), 'No Search')
            first_table = dialog.tables_by_key['no_search']
            self.assertEqual(first_table.columnCount(), 3)
            self.assertEqual(first_table.item(0, 0).text(), 'ROE-001')
        finally:
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
