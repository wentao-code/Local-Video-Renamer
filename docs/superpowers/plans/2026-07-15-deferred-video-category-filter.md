# Deferred Video Category Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backend health available before the expensive video-category snapshot filter runs.

**Architecture:** Load the persisted snapshot without recomputing `videos`. After `ThreadingHTTPServer` is constructed, start one daemon thread that filters a cloned `raw_videos` list and replaces the in-memory snapshot only if its identity and the current settings fingerprints are still current. Scheduling failures are logged without preventing the request loop.

**Tech Stack:** Python 3, threading, HTTPServer, unittest/pytest.

## Global Constraints

- Do not increase the startup timeout as the primary fix.
- Do not run `filter_video_rows` synchronously from `BackendService.__init__`.
- Health requests must be serviceable while filtering runs.
- A stale background result must not overwrite a newer snapshot.
- Background failure must not terminate the backend.

---

### Task 1: Remove filtering from snapshot load

**Files:**
- Modify: `code/tests/test_video_category_viewer.py`
- Modify: `code/app/backend/service.py`

**Interfaces:**
- Consumes: `_load_video_category_snapshot()` and persisted `overview_snapshot`.
- Produces: immediate in-memory snapshot without calling `filter_video_rows`.

- [x] Add a test whose filter stub raises if called during `_load_video_category_snapshot`.
- [x] Run the test and verify it fails at the synchronous filter call.
- [x] Remove filtering from the load path and retain persisted `videos`.
- [x] Run the test and verify it passes.

### Task 2: Add safe background filtering

**Files:**
- Modify: `code/tests/test_video_category_viewer.py`
- Modify: `code/app/backend/service.py`

**Interfaces:**
- Produces: `start_background_video_category_snapshot_filter()` and the worker that atomically replaces current `videos`.

- [x] Add tests for filtered replacement, stale-result rejection, changed-settings rejection, idempotent thread start, and non-fatal thread-start failure.
- [x] Run tests and verify the methods are absent.
- [x] Implement daemon-thread scheduling, filtering outside the snapshot lock, identity and settings comparison, persistence, and exception logging.
- [x] Run tests and verify they pass.

### Task 3: Start background work after HTTP binding

**Files:**
- Modify: `code/tests/test_backend_health.py`
- Modify: `code/app/backend/server.py`

**Interfaces:**
- Consumes: `BackendService.start_background_video_category_snapshot_filter()`.
- Produces: server startup ordering of construct server, announce listener, start background filter, serve requests.

- [x] Add server tests recording constructor/background-start order and non-fatal scheduling failure.
- [x] Run them and verify the background behavior is missing.
- [x] Call the background-start method after `ThreadingHTTPServer` construction, with a server-level scheduling guard.
- [x] Run the tests and verify they pass.

### Task 4: Verification

**Files:**
- Modify only files required by regressions caused by this change.

- [x] Run focused snapshot, health, safe-launcher, and startup tests.
- [x] Measure real backend health availability against the production snapshot.
- [x] Run the complete pytest suite.
- [x] Run `git diff --check` and inspect the final diff.
