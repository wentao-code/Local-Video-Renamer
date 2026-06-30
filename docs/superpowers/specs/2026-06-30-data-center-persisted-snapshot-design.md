# Data Center Persisted Snapshot Design

**Goal:** Let the desktop data center keep showing the last successful snapshot after the whole system exits and restarts, while refreshing the displayed data asynchronously in the background after the window opens.

**Scope:** This design covers the desktop data center summary window plus the actor/code-prefix analysis result windows that already expose cached snapshot behavior.

## Current State

- `DataCenterService` keeps summary and analysis results only in process memory.
- Reopening the data center within the same backend process reuses memory caches.
- Restarting the whole system creates a new `BackendService` and a new `DataCenterService`, so all cached snapshots are lost.
- The UI opens cached data with `force_refresh=False`, but today that only helps during the same process lifetime.

## Desired Behavior

1. When the system restarts, the first data center read should reuse the last successfully persisted snapshot if one exists.
2. Opening the data center summary window should immediately show that persisted snapshot, then trigger a background refresh that replaces the UI and persisted snapshot when it succeeds.
3. Opening metric analysis and actor-bucket windows should follow the same pattern: show the last persisted snapshot first, then refresh in the background.
4. If the background refresh fails, the UI should keep showing the older snapshot and only surface the refresh failure through the existing error handling path.
5. Manual refresh must continue to bypass snapshots and rebuild from live data.

## Recommended Approach

Persist the data center cache to a dedicated JSON snapshot file in the project root.

Why this approach:

- It keeps the change local to the existing data center caching layer.
- It avoids schema migrations in `video_database.db`.
- It preserves the current in-memory cache contract while adding cross-process durability.
- It supports summary and analysis snapshots with one shared storage mechanism.

## Data Model

Create a single persisted JSON payload with this shape:

```json
{
  "version": 1,
  "summary_snapshot": {
    "summary": {},
    "refreshed_at": "2026-06-30 12:00:00"
  },
  "analysis_snapshots": {
    "actor:age": {
      "analysis": {},
      "refreshed_at": "2026-06-30 12:00:00"
    },
    "actor_bucket:age:70": {
      "metric_key": "age",
      "bucket_value": 70,
      "bucket_label": "70岁",
      "actors": [],
      "refreshed_at": "2026-06-30 12:00:00"
    },
    "code_prefix:collection_ratio": {
      "analysis": {},
      "refreshed_at": "2026-06-30 12:00:00"
    }
  }
}
```

Notes:

- `summary_snapshot` mirrors the existing `get_summary_snapshot()` response.
- `analysis_snapshots` reuses the current cache keys already built by `DataCenterService`.
- The file stores only successful snapshots. Failed refresh attempts never overwrite the last good state.

## Storage Rules

- Default snapshot path: a hidden JSON file in the project root next to the other UI settings files.
- Load snapshots during `DataCenterService` initialization or before the first cache read.
- Ignore missing files, invalid JSON, or malformed payloads and fall back to rebuilding live data.
- Persist updates atomically by writing a full payload after each successful summary or analysis rebuild.

## Runtime Flow

### Summary window

1. App restart creates a fresh `BackendService` and `DataCenterService`.
2. `DataCenterService` hydrates memory caches from the persisted snapshot file if present.
3. `DataCenterWindow` opens and requests `get_data_center_summary(force_refresh=False)`.
4. The service returns the hydrated snapshot immediately.
5. After that initial load finishes, the window launches an asynchronous `force_refresh=True` request.
6. On success, the UI updates and the new snapshot is written back to disk.
7. On failure, the old snapshot stays visible.

### Analysis windows

The metric analysis and actor bucket windows follow the same sequence using their existing cache keys and `force_refresh` parameters.

## Error Handling

- Missing snapshot file: treat as cache miss and build live data.
- Invalid snapshot file contents: ignore the file and build live data.
- Snapshot write failure: do not fail the user request; keep the in-memory result and best-effort log/ignore the persistence failure.
- Background refresh failure: keep the snapshot already on screen and use the existing async error reporting path.

## Testing Strategy

1. Service persistence test:
   - Build a snapshot with one `DataCenterService` instance.
   - Create a second instance pointing at the same snapshot file.
   - Assert the second instance returns the persisted snapshot without rebuilding.

2. Summary window startup refresh test:
   - Assert startup issues `force_refresh=False` first and `force_refresh=True` second.
   - Assert the final UI shows the refreshed timestamp.

3. Analysis window startup refresh test:
   - Assert metric analysis windows follow the same two-call pattern.

4. Refresh failure regression test:
   - Keep the old snapshot visible if the forced refresh raises.

## Files Expected To Change

- `app/core/project_paths.py`
- `app/services/library/data_center_service.py`
- `app/gui/data_center_viewer.py`
- `app/gui/data_center_analysis_viewer.py`
- `tests/test_data_center_summary.py`
- `tests/test_data_center_viewer.py`
- `tests/test_data_center_analysis_viewer.py`

## Non-Goals

- Migrating snapshots into SQLite tables.
- Changing unrelated snapshot systems such as ladder boards, paths, or canglangge.
- Adding new user controls for snapshot management in this change.
