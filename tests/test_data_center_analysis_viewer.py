import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_analysis_viewer import ActorMetricBucketWindow, MetricAnalysisWindow


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.metric_refresh_flags = []
        self.bucket_refresh_flags = []

    def get_metric_analysis(self, analysis_type, metric_key, force_refresh=False):
        self.metric_refresh_flags.append(bool(force_refresh))
        if metric_key == "cup":
            return {
                "analysis": {
                    "distribution_rows": [
                        {"label": "F", "count": 3, "bucket_value": "F"},
                        {"label": "C", "count": 1, "bucket_value": "C"},
                        {"label": "无数据", "count": 2},
                    ],
                    "ranking_rows": [],
                    "distribution_items_per_line": 10,
                    "ranking_items_per_line": 6,
                },
                "refreshed_at": "2026-06-29 22:05:00" if force_refresh else "2026-06-29 22:00:00",
            }
        return {
            "analysis": {
                "distribution_rows": [
                    {"label": f"{70 - index}\u5c81", "count": index + 1, "bucket_value": 70 - index}
                    for index in range(12)
                ],
                "ranking_rows": [
                    {
                        "actor_name": f"Actor {index + 1}",
                        "display_value": f"{70 - index}\u5c81",
                        "numeric_value": 70 - index,
                    }
                    for index in range(7)
                ],
                "distribution_items_per_line": 10,
                "ranking_items_per_line": 6,
            },
            "refreshed_at": "2026-06-29 22:05:00" if force_refresh else "2026-06-29 22:00:00",
        }

    def get_actor_metric_bucket(self, metric_key, bucket_value, force_refresh=False):
        self.bucket_refresh_flags.append(bool(force_refresh))
        return {
            "metric_key": metric_key,
            "bucket_value": bucket_value,
            "actors": [
                {"actor_name": "Actor A", "display_value": "70\u5c81", "numeric_value": 70},
                {"actor_name": "Actor D", "display_value": "70\u5c81", "numeric_value": 70},
            ],
            "refreshed_at": "2026-06-29 22:05:01" if force_refresh else "2026-06-29 22:00:01",
        }


class DataCenterAnalysisViewerTest(unittest.TestCase):
    def test_metric_window_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()
        metric_config = {"key": "age", "label_key": "data_center.analysis.age"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                self.assertEqual(backend.metric_refresh_flags, [False, True])
                self.assertIn("2026-06-29 22:05:00", window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_metric_distribution_renders_clickable_bucket_buttons_in_ten_columns(self):
        backend = _BackendStub()
        metric_config = {"key": "age", "label_key": "data_center.analysis.age"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                button_texts = [button.text() for button in window.distribution_buttons]
                self.assertEqual(len(button_texts), 12)
                self.assertEqual(button_texts[0], "70\u5c81: 1")
                self.assertEqual(button_texts[10], "60\u5c81: 11")
                self.assertIsNotNone(window.distribution_button_layout.itemAtPosition(0, 9))
                self.assertIsNotNone(window.distribution_button_layout.itemAtPosition(1, 0))
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_metric_ranking_renders_six_columns_with_aligned_cells(self):
        backend = _BackendStub()
        metric_config = {"key": "age", "label_key": "data_center.analysis.age"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                self.assertEqual(len(window.ranking_item_widgets), 7)
                self.assertIsNotNone(window.ranking_grid_layout.itemAtPosition(0, 5))
                self.assertIsNotNone(window.ranking_grid_layout.itemAtPosition(1, 0))

                widths = [widget.minimumWidth() for widget in window.ranking_item_widgets]
                self.assertTrue(all(width == widths[0] for width in widths))
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_metric_bucket_window_uses_snapshot_then_background_refresh(self):
        backend = _BackendStub()

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = ActorMetricBucketWindow(
                backend,
                {"key": "age", "label_key": "data_center.analysis.age"},
                70,
                "70\u5c81",
            )
            try:
                self.assertEqual(backend.bucket_refresh_flags, [False, True])
                self.assertIn("2026-06-29 22:05:01", window.last_refreshed_label.text())
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_metric_bucket_window_opens_actor_detail_for_selected_row(self):
        backend = _BackendStub()

        created = {}

        class FakeActorDetailViewerWindow:
            def __init__(self, backend_client, actor_name, parent=None):
                created["backend_client"] = backend_client
                created["actor_name"] = actor_name
                created["parent"] = parent

            def show(self):
                created["opened"] = True

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            with patch(
                "app.gui.data_center_analysis_viewer.ActorDetailViewerWindow",
                FakeActorDetailViewerWindow,
            ):
                window = ActorMetricBucketWindow(
                    backend,
                    {"key": "age", "label_key": "data_center.analysis.age"},
                    70,
                    "70\u5c81",
                )
                try:
                    window.show_actor_detail("Actor D")
                finally:
                    window.hide()
                    window.deleteLater()

        self.assertIs(created.get("backend_client"), backend)
        self.assertEqual(created.get("actor_name"), "Actor D")
        self.assertIs(created.get("parent"), window)
        self.assertTrue(created.get("opened"))

    def test_cup_metric_hides_ranking_and_keeps_clickable_distribution(self):
        backend = _BackendStub()
        metric_config = {"key": "cup", "label_key": "data_center.analysis.cup"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                self.assertFalse(window.ranking_group.isVisible())
                self.assertEqual([button.text() for button in window.distribution_buttons], ["F: 3", "C: 1"])
                self.assertEqual(window.distribution_label.text(), "无数据: 2")
            finally:
                window.hide()
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
