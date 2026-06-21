import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.enrichment_summary_widgets import SummaryCard, SummaryIssueDialog


_APP = QApplication.instance() or QApplication([])


class EnrichmentSummaryWidgetsTest(unittest.TestCase):
    def test_binghuo_summary_card_uses_split_missing_labels_and_enables_list_button(self):
        card = SummaryCard('演员库 · 并火')
        try:
            card.set_summary(
                {
                    'label': '演员库 · 并火',
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
                        {'key': 'no_search', 'label': '无结果', 'items': [{'name': 'Actor A'}]},
                        {'key': 'missing_age', 'label': '无年龄', 'items': [{'name': 'Actor B'}]},
                    ],
                    'list_kind': 'actor',
                }
            )

            self.assertIn('无年龄 1', card.detail_label.text())
            self.assertIn('无三围 2', card.detail_label.text())
            self.assertIn('无身高 1', card.detail_label.text())
            self.assertNotIn('无详情', card.detail_label.text())
            self.assertTrue(card.list_button.isEnabled())
        finally:
            card.deleteLater()

    def test_summary_issue_dialog_builds_tabs_and_columns_from_issue_groups(self):
        dialog = SummaryIssueDialog(
            '视频库 · 辛聚谷',
            'video',
            [
                {
                    'key': 'no_search',
                    'label': '无结果',
                    'items': [{'code': 'ROE-001', 'title': 'Title A', 'author': 'Actor A'}],
                },
                {
                    'key': 'no_detail',
                    'label': '无详情',
                    'items': [{'code': 'ROE-002', 'title': 'Title B', 'author': 'Actor B'}],
                },
            ],
        )
        try:
            self.assertEqual(dialog.windowTitle(), '视频库 · 辛聚谷 · 列表展示')
            self.assertEqual(dialog.tab_widget.count(), 2)
            self.assertEqual(dialog.tab_widget.tabText(0), '无结果')
            first_table = dialog.tables_by_key['no_search']
            self.assertEqual(first_table.columnCount(), 3)
            self.assertEqual(first_table.horizontalHeaderItem(0).text(), '视频编号')
            self.assertEqual(first_table.horizontalHeaderItem(1).text(), '视频标题')
            self.assertEqual(first_table.horizontalHeaderItem(2).text(), '出演演员')
            self.assertEqual(first_table.item(0, 0).text(), 'ROE-001')
        finally:
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
