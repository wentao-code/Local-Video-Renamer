# Data Center Persisted Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist data center snapshots across full app restarts, then auto-refresh the summary and analysis windows after showing the last saved snapshot.

**Architecture:** Extend `DataCenterService` with a disk-backed snapshot file that hydrates the existing in-memory caches on startup and rewrites them after successful rebuilds. Update the summary and analysis windows so their first load shows the cached snapshot and automatically triggers a second forced refresh in the background.

**Tech Stack:** Python, PyQt5, unittest, JSON file persistence, existing backend HTTP layer

---

### Task 1: Add failing persistence tests for `DataCenterService`

**Files:**
- Modify: `tests/test_data_center_summary.py`
- Modify: `app/services/library/data_center_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_summary_snapshot_persists_across_service_restarts(self):
    temp_dir = tempfile.mkdtemp()
    try:
        snapshot_file = Path(temp_dir) / "data_center_snapshot.json"
        first_service = DataCenterService(database=None, snapshot_file=snapshot_file)

        with patch.object(first_service, "_load_filter_settings", return_value=None), patch.object(
            first_service,
            "_build_summary",
            return_value={"version": 1},
        ), patch.object(
            first_service,
            "_current_cache_timestamp",
            return_value="2026-06-30 09:00:00",
        ):
            first = first_service.get_summary_snapshot(force_refresh=True)

        second_service = DataCenterService(database=None, snapshot_file=snapshot_file)
        with patch.object(second_service, "_load_filter_settings", return_value=None), patch.object(
            second_service,
            "_build_summary",
            side_effect=AssertionError("should reuse persisted snapshot"),
        ):
            second = second_service.get_summary_snapshot()

        self.assertEqual(first, second)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_data_center_summary.DataCenterSummarySplitCountsTest.test_summary_snapshot_persists_across_service_restarts`
Expected: FAIL because `DataCenterService` does not accept `snapshot_file` or cannot reload persisted snapshots yet.

- [ ] **Step 3: Write minimal implementation**

```python
class DataCenterService:
    def __init__(self, database, video_filter_service=None, snapshot_file=None):
        self.snapshot_file = Path(snapshot_file or DATA_CENTER_SNAPSHOT_FILE)
        ...
        self._load_persisted_snapshots()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_data_center_summary.DataCenterSummarySplitCountsTest.test_summary_snapshot_persists_across_service_restarts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_data_center_summary.py app/services/library/data_center_service.py app/core/project_paths.py
git commit -m "feat: persist data center snapshots"
```

### Task 2: Add failing UI startup refresh test for the summary window

**Files:**
- Modify: `tests/test_data_center_viewer.py`
- Modify: `app/gui/data_center_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
def test_startup_load_uses_snapshot_then_background_refresh(self):
    backend = _BackendStub()

    with patch.object(AsyncTaskHostMixin, "start_async_task", _run_sync_async_task):
        window = DataCenterWindow(backend)
        try:
            self.assertEqual(backend.summary_refresh_flags, [False, True])
            self.assertIn("2026-06-21 12:35:56", window.last_refreshed_label.text())
        finally:
            window.hide()
            window.deleteLater()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_data_center_viewer.DataCenterViewerTest.test_startup_load_uses_snapshot_then_background_refresh`
Expected: FAIL because the window only issues one startup request today.

- [ ] **Step 3: Write minimal implementation**

```python
self._startup_refresh_pending = True
self.load_data()

def _on_load_data_finished(self, result):
    ...
    if self._startup_refresh_pending:
        self._startup_refresh_pending = False
        self.load_data(force_refresh=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_data_center_viewer.DataCenterViewerTest.test_startup_load_uses_snapshot_then_background_refresh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_data_center_viewer.py app/gui/data_center_viewer.py
git commit -m "feat: auto-refresh data center after cached startup load"
```

### Task 3: Add failing startup refresh test for metric analysis windows

**Files:**
- Modify: `tests/test_data_center_analysis_viewer.py`
- Modify: `app/gui/data_center_analysis_viewer.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_data_center_analysis_viewer.DataCenterAnalysisViewerTest.test_metric_window_uses_snapshot_then_background_refresh`
Expected: FAIL because `MetricAnalysisWindow` only loads once on startup.

- [ ] **Step 3: Write minimal implementation**

```python
self._startup_refresh_pending = True
self.load_data()

def _on_load_data_finished(self, result):
    ...
    if self._startup_refresh_pending:
        self._startup_refresh_pending = False
        self.load_data(force_refresh=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_data_center_analysis_viewer.DataCenterAnalysisViewerTest.test_metric_window_uses_snapshot_then_background_refresh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_data_center_analysis_viewer.py app/gui/data_center_analysis_viewer.py
git commit -m "feat: auto-refresh analysis windows after cached startup load"
```

### Task 4: Run the focused regression suite

**Files:**
- Test: `tests/test_data_center_summary.py`
- Test: `tests/test_data_center_viewer.py`
- Test: `tests/test_data_center_analysis_viewer.py`

- [ ] **Step 1: Run the focused suite**

Run: `python -m unittest tests.test_data_center_summary tests.test_data_center_viewer tests.test_data_center_analysis_viewer`
Expected: PASS

- [ ] **Step 2: Verify persisted snapshot file behavior manually in code review**

```python
assert DATA_CENTER_SNAPSHOT_FILE.name == ".data_center_snapshot.json"
assert second_service.get_summary_snapshot()["refreshed_at"] == "2026-06-30 09:00:00"
```

- [ ] **Step 3: Commit the final integration pass**

```bash
git add app/core/project_paths.py app/services/library/data_center_service.py app/gui/data_center_viewer.py app/gui/data_center_analysis_viewer.py tests/test_data_center_summary.py tests/test_data_center_viewer.py tests/test_data_center_analysis_viewer.py docs/superpowers/specs/2026-06-30-data-center-persisted-snapshot-design.md docs/superpowers/plans/2026-06-30-data-center-persisted-snapshot-implementation.md
git commit -m "feat: restore data center snapshots across restarts"
```
