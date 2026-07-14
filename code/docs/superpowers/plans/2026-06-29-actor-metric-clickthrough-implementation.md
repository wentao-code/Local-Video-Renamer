# Actor Metric Clickthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make actor analysis metric distributions clickable for age, height, bust, waist, and hip so each bucket opens a lightweight actor list with per-row detail navigation.

**Architecture:** Extend the actor-analysis backend payload with stable bucket values and add a focused endpoint that returns all actors for one actor-metric bucket. In the desktop UI, replace actor-metric distribution text with lightweight bucket buttons, open a dedicated list dialog on demand, and reuse the existing `ActorDetailViewerWindow` for detail pages.

**Tech Stack:** Python, PyQt5, unittest, existing backend HTTP layer, `DataCenterService`

---

### Task 1: Lock backend bucket payload and bucket list behavior with tests

**Files:**
- Modify: `tests/test_data_center_summary.py`

- [ ] Add a failing test that expects actor-metric distribution rows to include a stable `bucket_value` for clickable buckets.
- [ ] Add a failing test that requests all actors for one actor-metric bucket and verifies sort order plus display values.
- [ ] Run: `python -m pytest tests/test_data_center_summary.py -k actor_metric -v`
- [ ] Confirm the new assertions fail before implementation.

### Task 2: Add actor-metric bucket list support to the backend layer

**Files:**
- Modify: `app/services/library/data_center_service.py`
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/client.py`
- Modify: `app/core/backend_protocol.py`

- [ ] Implement actor-metric distribution rows with `bucket_value` alongside the existing label and count fields.
- [ ] Implement a focused actor-metric bucket list builder that returns all actors for one metric/value pair, sorted by actor name inside the bucket.
- [ ] Add a backend route and client helper for fetching one actor-metric bucket list on demand.
- [ ] Run: `python -m pytest tests/test_data_center_summary.py -k actor_metric -v`
- [ ] Confirm the backend tests pass.

### Task 3: Cover the desktop clickthrough flow with GUI tests

**Files:**
- Create: `tests/test_data_center_analysis_viewer.py`

- [ ] Add a failing GUI test that loads an actor metric page and expects clickable distribution buttons instead of plain text for actor metrics.
- [ ] Add a failing GUI test that opens the bucket list dialog and verifies the per-row detail action targets the expected actor.
- [ ] Run: `python -m pytest tests/test_data_center_analysis_viewer.py -v`
- [ ] Confirm the GUI tests fail before implementation.

### Task 4: Implement the clickable actor-metric distribution flow

**Files:**
- Modify: `app/gui/data_center_analysis_viewer.py`
- Modify: `app/gui/i18n_patch.py`

- [ ] Replace actor-metric distribution text rendering with lightweight bucket buttons while preserving plain-text rendering for non-clickable analysis types.
- [ ] Add a compact actor bucket list dialog that loads rows on demand and opens `ActorDetailViewerWindow` from each row.
- [ ] Keep the ranking display behavior unchanged.
- [ ] Run: `python -m pytest tests/test_data_center_analysis_viewer.py -v`
- [ ] Confirm the GUI tests pass.

### Task 5: Run the touched verification set before reporting completion

**Files:**
- No code changes expected

- [ ] Run: `python -m pytest tests/test_data_center_summary.py -k actor_metric -v`
- [ ] Run: `python -m pytest tests/test_data_center_analysis_viewer.py -v`
- [ ] Review the diff for consistency with the approved behavior before reporting completion.
