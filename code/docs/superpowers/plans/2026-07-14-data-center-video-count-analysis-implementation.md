# Data Center Video Count Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clickable video-count distributions and top-50 rankings to actor and code-prefix data analysis.

**Architecture:** Register both metrics in the existing metric maps and extend `DataCenterService` with shared range bucketing plus entity-specific count collection. Reuse persisted analysis snapshots and the shared metric window, adding a code-prefix bucket API and detail window parallel to the actor path.

**Tech Stack:** Python 3, SQLite, PyQt5, unittest/pytest.

## Global Constraints

- Actor ranges: 0-4, 5-9, 10-29, 30-79, 80+.
- Code-prefix ranges: 0-49, 50-99, 100-299, 300-799, 800+.
- Actor counts include only effective single and co-star videos.
- Code-prefix counts include all effective videos.
- Count distinct standardized codes, retain zero-count entities, sort ties by entity name, and limit rankings to 50.
- Preserve snapshot-first loading and background refresh.

---

### Task 1: Metric Configuration And Count Analysis

**Files:**
- Modify: `app/core/actor_data_analysis.py`
- Modify: `app/core/code_prefix_data_analysis.py`
- Modify: `app/services/library/data_center_service.py`
- Test: `tests/test_data_center_summary.py`
- Test: `tests/test_data_center_actor_metric_clickthrough.py`

**Interfaces:**
- Consumes: existing filtered actor and code-prefix movie loaders in `DataCenterService`.
- Produces: analysis payloads with `distribution_rows`, `ranking_rows`, and stable range `bucket_value` keys.

- [ ] **Step 1: Write failing actor and code-prefix count tests**

Seed videos at every boundary, duplicate one code, include an excluded category for an actor, and assert rows shaped like:

```python
{
    'label': '5-9',
    'count': 2,
    'bucket_value': '5_9',
}
```

Assert rankings use `numeric_value`, descending counts, ascending names for ties, and at most 50 entries.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest tests/test_data_center_summary.py tests/test_data_center_actor_metric_clickthrough.py -q
```

Expected: failures because `video_count` is not registered or built.

- [ ] **Step 3: Register range metric configurations**

Add actor and prefix metric entries containing `key='video_count'`, `label_key='data_center.analysis.video_count'`, `value_type='range_count'`, and their exact range definitions.

- [ ] **Step 4: Implement shared range classification and analysis builders**

Build `{entity_name: distinct_code_count}` maps. Actor movie rows must pass the existing effective filter and normalized category membership in `{VIDEO_CATEGORY_SINGLE, VIDEO_CATEGORY_CO_STAR}`. Prefix rows use all effective movies. Convert maps into five distribution rows and top-50 ranking rows.

- [ ] **Step 5: Run focused tests**

Run the command from Step 2. Expected: PASS.

### Task 2: Bucket Retrieval And Backend API

**Files:**
- Modify: `app/services/library/data_center_service.py`
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/client.py`
- Test: `tests/test_data_center_actor_metric_clickthrough.py`
- Test: `tests/test_backend_reuse.py`

**Interfaces:**
- Consumes: range-count maps and bucket normalization from Task 1.
- Produces: `get_code_prefix_metric_bucket_snapshot(metric_key, bucket_value, force_refresh=False)` and client method `get_code_prefix_metric_bucket(...)`.

- [ ] **Step 1: Write failing bucket and route tests**

Assert actor `5_9` returns only actors with 5 through 9 qualifying videos. Assert prefix `50_99` returns only prefixes with 50 through 99 effective videos. Assert server/client routing carries `metric`, `value`, and `refresh`.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest tests/test_data_center_actor_metric_clickthrough.py tests/test_backend_reuse.py -q
```

Expected: missing code-prefix bucket API or unknown bucket failures.

- [ ] **Step 3: Add generic range-bucket normalization and entity rows**

Return actor rows as `actor_name`, `display_value`, and `numeric_value`; return prefix rows as `prefix`, `display_value`, and `numeric_value`. Sort by count descending and name ascending.

- [ ] **Step 4: Add backend and client routes**

Add `/data-center/analysis/code-prefixes` parallel to `/data-center/analysis/actors`, then bump `BACKEND_API_REVISION` with a `video-count-analysis` marker.

- [ ] **Step 5: Run focused tests**

Run the command from Step 2. Expected: PASS.

### Task 3: Metric Buttons, Bucket Windows, And Detail Navigation

**Files:**
- Modify: `app/gui/data_center_analysis_viewer.py`
- Modify: `app/gui/i18n_patch.py`
- Test: `tests/test_data_center_analysis_viewer.py`

**Interfaces:**
- Consumes: actor and prefix metric analysis/bucket payloads.
- Produces: one new metric button per analysis page and clickable actor/prefix bucket windows.

- [ ] **Step 1: Write failing GUI tests**

Assert actor and prefix entry windows expose `video_count`. Click a distribution button and assert the correct bucket window is created. Assert actor rows open `ActorDetailViewerWindow`; prefix rows open `CodePrefixDetailViewerWindow`.

- [ ] **Step 2: Verify the GUI tests fail**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; & 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest tests/test_data_center_analysis_viewer.py -q
```

Expected: missing button or prefix bucket window failures.

- [ ] **Step 3: Add localized label and shared click dispatch**

Add `data_center.analysis.video_count`. In `MetricAnalysisWindow`, dispatch actor buckets to `ActorMetricBucketWindow` and prefix buckets to a new `CodePrefixMetricBucketWindow`.

- [ ] **Step 4: Implement the prefix bucket window**

Mirror actor bucket snapshot/background refresh, render prefix/count columns, and open `CodePrefixDetailViewerWindow` for the selected prefix. Keep one window instance per bucket through existing child-window ownership.

- [ ] **Step 5: Run GUI tests**

Run the command from Step 2. Expected: PASS.

### Task 4: Snapshot Compatibility And Full Verification

**Files:**
- Modify: `app/services/library/data_center_service.py`
- Test: `tests/test_data_center_summary.py`
- Test: `tests/test_data_center_analysis_viewer.py`

**Interfaces:**
- Consumes: all completed feature behavior.
- Produces: validated persisted snapshots and a regression-safe application.

- [ ] **Step 1: Add a snapshot reload test**

Build and persist both `video_count` metrics and buckets, construct a new service, and assert cached payloads load without a database rebuild.

- [ ] **Step 2: Run all data-center tests**

```powershell
& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest tests/test_data_center_summary.py tests/test_data_center_viewer.py tests/test_data_center_analysis_viewer.py tests/test_data_center_actor_metric_clickthrough.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete suite**

```powershell
& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Check the final diff**

```powershell
git diff --check
```

Expected: exit code 0 with no whitespace errors.
