import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.main_window import VidNormApp


_APP = QApplication.instance() or QApplication([])


class SnapshotClientStub:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: {}


class SnapshotRefreshTaskSpecsTest(unittest.TestCase):
    def test_data_center_dashboard_is_split_by_concrete_metric(self):
        specs = VidNormApp._build_snapshot_refresh_task_specs(
            SnapshotClientStub(),
            dashboard_metric_keys=['actor_count', 'video_count'],
        )

        keys = [item['key'] for item in specs]
        self.assertIn('data_center_summary', keys)
        self.assertIn('data_center_dashboard', keys)
        self.assertIn('data_center_dashboard_metric_actor_count', keys)
        self.assertIn('data_center_dashboard_metric_video_count', keys)
        self.assertEqual(len([key for key in keys if key.startswith('data_center_dashboard_metric_')]), 2)

    def test_other_snapshot_groups_remain_one_task_per_top_level_category(self):
        specs = VidNormApp._build_snapshot_refresh_task_specs(
            SnapshotClientStub(),
            dashboard_metric_keys=[],
        )

        keys = [item['key'] for item in specs]
        self.assertIn('video_library', keys)
        self.assertIn('actor_library', keys)
        self.assertIn('code_prefix_library', keys)
        self.assertEqual(len([key for key in keys if key == 'actor_analysis']), 1)
        self.assertEqual(len([key for key in keys if key == 'code_prefix_analysis']), 1)


if __name__ == '__main__':
    unittest.main()
