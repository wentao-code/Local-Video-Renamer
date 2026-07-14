# Operation Timeout Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a database-backed timeout manager and replace user-visible operation timeout hardcoding with runtime settings.

**Architecture:** An ordered core registry supplies defaults and validation while one SQLite override table stores custom values. Backend CRUD endpoints serve a PyQt5 table dialog. Operation-level callers resolve effective values at execution time so changes apply without restart.

**Tech Stack:** Python 3, SQLite, requests, Playwright, PyQt5, pytest.

## Global Constraints

- Store only custom overrides; defaults remain in code.
- Accept decimal seconds and reject non-finite, zero, negative, and out-of-range values.
- Green means default and red means custom.
- Apply changes to the next operation without interrupting current waits.
- Do not expose or modify element waits, UI polling, cooldowns, or retry sleeps.

---

### Task 1: Registry And SQLite Overrides

**Files:**
- Create: `app/core/operation_timeout_settings.py`
- Modify: `app/data/database_handler.py`
- Test: `tests/test_operation_timeout_settings.py`

**Interfaces:**
- Produces: `list_operation_timeout_settings`, `get_operation_timeout_seconds`, `set_operation_timeout_overrides`, `reset_operation_timeout_overrides`, and `ensure_operation_timeout_settings_table`.

- [ ] Write tests for ordered defaults, schema, decimal overrides, effective values, selected reset, all reset, unknown keys, and atomic validation.
- [ ] Run `& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest tests/test_operation_timeout_settings.py -q` and verify failures are caused by missing APIs.
- [ ] Implement the registry, table helper, validation, and CRUD functions.
- [ ] Run the focused test and verify PASS.

### Task 2: Backend API And Runtime Consumers

**Files:**
- Modify: `app/backend/client.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/service.py`
- Modify: `app/core/backend_protocol.py`
- Modify: `app/data/database_handler.py`
- Modify: `app/queen_library/service.py`
- Modify: `app/services/system/network_guard_service.py`
- Modify: `app/services/local_video/local_video_media_info.py`
- Modify: scraper modules under `app/scraper/` and `app/queen_library/scraper.py`
- Test: `tests/test_operation_timeout_settings.py`
- Test: existing scraper and backend-client tests.

**Interfaces:**
- Produces: client/service methods `list_operation_timeouts`, `update_operation_timeouts`, `reset_operation_timeouts` and routes under `/settings/timeouts`.

- [ ] Write failing client and consumer tests that override values and assert the next call receives the new seconds or milliseconds.
- [ ] Add API routes and protocol revision marker.
- [ ] Replace operation-level constants with `get_operation_timeout_seconds(key)` at call time while preserving dynamic batch-request formulas as lower-bound calculations.
- [ ] Run operation-timeout, backend, scraper, database, and network focused tests.

### Task 3: Timeout Manager Dialog And Main Entry

**Files:**
- Create: `app/gui/timeout_settings_viewer.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/i18n.py`
- Modify: `app/gui/i18n_patch.py`
- Test: `tests/test_timeout_settings_viewer.py`

**Interfaces:**
- Consumes: backend timeout CRUD methods.
- Produces: `TimeoutSettingsViewerWindow` with editable override cells and single-instance main-window navigation.

- [ ] Write failing offscreen PyQt tests for table columns, decimal editing, confirm, selected/all reset, refresh, validation errors, and indicator colors.
- [ ] Implement the dialog and main button using existing child-window ownership patterns.
- [ ] Run GUI focused tests and verify PASS.

### Task 4: Full Verification

**Files:**
- Test: all modified and existing test modules.

**Interfaces:**
- Produces: a regression-safe runtime timeout feature.

- [ ] Run timeout-focused and subsystem test files.
- [ ] Run `& 'D:\Anaconda3Data\envs_dirs\video_env\python.exe' -m pytest -q`.
- [ ] Run `git diff --check` and inspect the final feature diff.
