import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from app.gui.backend_task_worker import AsyncTaskHostMixin
from app.gui.data_center_analysis_viewer import (
    ActorDataAnalysisWindow,
    ActorMetricBucketWindow,
    CodePrefixDataAnalysisWindow,
    CodePrefixMetricBucketWindow,
    MetricAnalysisWindow,
)


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class _BackendStub:
    def __init__(self):
        self.metric_refresh_flags = []
        self.bucket_refresh_flags = []
        self.prefix_bucket_refresh_flags = []

    def get_metric_analysis(self, analysis_type, metric_key, force_refresh=False):
        self.metric_refresh_flags.append(bool(force_refresh))
        if metric_key == "video_count":
            entity_key = "actor_name" if analysis_type == "actor" else "prefix"
            return {
                "analysis": {
                    "distribution_rows": [
                        {"label": "50~99\u4e2a", "count": 2, "bucket_value": "50_99"},
                    ],
                    "ranking_rows": [
                        {entity_key: "AAA", "display_value": "55\u4e2a", "numeric_value": 55},
                    ],
                    "distribution_items_per_line": 5,
                    "ranking_items_per_line": 7,
                },
                "refreshed_at": "2026-06-29 22:05:00" if force_refresh else "2026-06-29 22:00:00",
            }
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

    def get_code_prefix_metric_bucket(self, metric_key, bucket_value, force_refresh=False):
        self.prefix_bucket_refresh_flags.append(bool(force_refresh))
        return {
            "metric_key": metric_key,
            "bucket_value": bucket_value,
            "prefixes": [
                {"prefix": "AAA", "display_value": "55\u4e2a", "numeric_value": 55},
                {"prefix": "BBB", "display_value": "50\u4e2a", "numeric_value": 50},
            ],
            "refreshed_at": "2026-06-29 22:05:02" if force_refresh else "2026-06-29 22:00:02",
        }


class DataCenterAnalysisViewerTest(unittest.TestCase):
    def test_actor_and_code_prefix_analysis_include_video_count_metric(self):
        actor_window = ActorDataAnalysisWindow(_BackendStub())
        prefix_window = CodePrefixDataAnalysisWindow(_BackendStub())
        try:
            self.assertIn("video_count", [item["key"] for item in actor_window.metric_configs])
            self.assertIn("video_count", [item["key"] for item in prefix_window.metric_configs])
        finally:
            actor_window.hide()
            actor_window.deleteLater()
            prefix_window.hide()
            prefix_window.deleteLater()

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

    def test_actor_metric_distribution_renders_smaller_clickable_bucket_buttons(self):
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
                self.assertEqual(window.distribution_buttons[0].minimumWidth(), 76)
                self.assertEqual(window.distribution_buttons[0].maximumWidth(), 76)
            finally:
                window.hide()
                window.deleteLater()

    def test_actor_metric_ranking_renders_seven_columns_with_aligned_cells(self):
        backend = _BackendStub()
        metric_config = {"key": "age", "label_key": "data_center.analysis.age"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                self.assertEqual(len(window.ranking_item_widgets), 7)
                self.assertIsNotNone(window.ranking_grid_layout.itemAtPosition(0, 6))
                self.assertIsNone(window.ranking_grid_layout.itemAtPosition(1, 0))

                widths = [widget.minimumWidth() for widget in window.ranking_item_widgets]
                self.assertTrue(all(width == widths[0] for width in widths))
            finally:
                window.hide()
                window.deleteLater()

    def test_other_actor_metric_pages_use_same_layout_as_age(self):
        backend = _BackendStub()
        metric_config = {"key": "height", "label_key": "data_center.analysis.height"}

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            window = MetricAnalysisWindow(backend, "actor", metric_config)
            try:
                self.assertEqual(window.distribution_buttons[0].minimumWidth(), 76)
                self.assertEqual(window.distribution_buttons[0].maximumWidth(), 76)
                self.assertIsNotNone(window.distribution_button_layout.itemAtPosition(0, 9))
                self.assertIsNotNone(window.distribution_button_layout.itemAtPosition(1, 0))
                self.assertIsNotNone(window.ranking_grid_layout.itemAtPosition(0, 6))
                self.assertIsNone(window.ranking_grid_layout.itemAtPosition(1, 0))
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

    def test_code_prefix_video_count_distribution_opens_prefix_bucket_window(self):
        backend = _BackendStub()
        metric_config = {"key": "video_count", "label_key": "data_center.analysis.video_count"}
        created = {}

        class FakeCodePrefixMetricBucketWindow:
            def __init__(self, backend_client, current_metric_config, bucket_value, bucket_label, parent=None, coordinator=None):
                created["backend_client"] = backend_client
                created["metric_config"] = current_metric_config
                created["bucket_value"] = bucket_value
                created["bucket_label"] = bucket_label
                created["parent"] = parent
                self.finished = type("Signal", (), {"connect": lambda self, callback: None})()

            def show(self):
                created["opened"] = True

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            with patch(
                "app.gui.data_center_analysis_viewer.CodePrefixMetricBucketWindow",
                FakeCodePrefixMetricBucketWindow,
            ):
                window = MetricAnalysisWindow(backend, "code_prefix", metric_config)
                try:
                    window.distribution_buttons[0].click()
                finally:
                    window.hide()
                    window.deleteLater()

        self.assertIs(created.get("backend_client"), backend)
        self.assertEqual(created.get("bucket_value"), "50_99")
        self.assertEqual(created.get("bucket_label"), "50~99\u4e2a")
        self.assertTrue(created.get("opened"))

    def test_code_prefix_metric_bucket_window_loads_rows_and_opens_detail(self):
        backend = _BackendStub()
        created = {}

        class FakeCodePrefixDetailViewerWindow:
            def __init__(self, backend_client, prefix, parent=None):
                created["backend_client"] = backend_client
                created["prefix"] = prefix
                created["parent"] = parent

            def show(self):
                created["opened"] = True

        with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
            with patch(
                "app.gui.code_prefix_detail_viewer.CodePrefixDetailViewerWindow",
                FakeCodePrefixDetailViewerWindow,
            ):
                window = CodePrefixMetricBucketWindow(
                    backend,
                    {"key": "video_count", "label_key": "data_center.analysis.video_count"},
                    "50_99",
                    "50~99\u4e2a",
                )
                try:
                    self.assertEqual(backend.prefix_bucket_refresh_flags, [False, True])
                    self.assertEqual([row["prefix"] for row in window.prefix_rows], ["AAA", "BBB"])
                    self.assertEqual(window.select_prefix_row("bbb"), "BBB")
                    window.show_code_prefix_detail("BBB")
                finally:
                    window.hide()
                    window.deleteLater()

        self.assertIs(created.get("backend_client"), backend)
        self.assertEqual(created.get("prefix"), "BBB")
        self.assertIs(created.get("parent"), window)
        self.assertTrue(created.get("opened"))


if __name__ == "__main__":
    unittest.main()
