# Desktop Query Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the desktop client with a reusable multi-window navigation layer, unified cross-library search, data-center click-through filters, and asynchronous read-only browsing without changing existing task mutations.

**Architecture:** Add typed query/navigation models and a coordinator owned by the main window. Existing viewers remain the presentation layer and receive navigation requests through the coordinator; the backend exposes one read-only unified search endpoint backed by existing repository list methods. Viewer state is passed as a `QueryContext` and all background reads use the existing async worker pattern.

**Tech Stack:** Python 3, PyQt5, existing `BackendClient`/HTTP backend, existing `AsyncTaskHostMixin`, unittest/pytest.

## Global Constraints

- Preserve the existing multi-window desktop model; do not replace it with a dock-based shell.
- Query and navigation code must not invoke enrichment, crawling, mutation, or snapshot-refresh endpoints.
- Existing task-mode write workflows must keep their current behavior.
- Read-only browsing must remain usable while an enrichment task is running.
- Local search history may use client settings but must not modify the source database.
- Reuse existing list/detail viewers instead of duplicating their data formatting.

### Task 1: Add Typed Query and Navigation Models

**Files:**
- Create: `app/gui/query_context.py`
- Test: `tests/test_query_context.py`

**Interfaces:**
- `EntityType`: string constants `video`, `actor`, `code_prefix`, `ladder`, `masterpiece`.
- `EntityReference(entity_type, entity_key, display_name='')` with `as_dict()`.
- `QueryContext(search_text='', filters=None, sort_field='', sort_order='asc', page=1, page_size=100, source='')` with `copy_with()` and `as_dict()`.
- `NavigationRequest(target=None, context=None, action='open')`.

- [ ] **Step 1: Write tests** for stable serialization, copy isolation, and empty normalization.
- [ ] **Step 2: Run `pytest tests/test_query_context.py -q` and confirm failure.**
- [ ] **Step 3: Implement immutable normalized models with plain dictionaries.**
- [ ] **Step 4: Run the focused test and confirm pass.**
- [ ] **Step 5: Run `python -m compileall app/gui/query_context.py`.**

### Task 2: Add Unified Read-Only Search Backend API

**Files:**
- Modify: `app/backend/client.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/service.py`
- Create or modify: `app/services/library/unified_search_service.py`
- Test: `tests/test_unified_search_service.py`

**Interfaces:**
- `BackendClient.search_all(search_text, limit=20)` sends `GET /search/unified?q=...&limit=...`.
- `BackendService.search_unified(search_text, limit=20)` returns `{'results': [...], 'query': ..., 'total': ...}`.
- Each result contains `entity_type`, `entity_key`, `display_name`, `secondary_text`, and `source`.

- [ ] **Step 1: Add failing service tests with a fake database exposing video, actor, prefix, ladder, and masterpiece list methods.**
- [ ] **Step 2: Run the focused test and confirm the endpoint/service is missing.**
- [ ] **Step 3: Implement bounded searches using existing read methods, normalize results, deduplicate by `(entity_type, entity_key)`, and never call refresh flags.**
- [ ] **Step 4: Add the GET route and client method.**
- [ ] **Step 5: Run `pytest tests/test_unified_search_service.py -q`.**

### Task 3: Add Window Coordinator and Non-Modal Window Reuse

**Files:**
- Create: `app/gui/window_coordinator.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_window_coordinator.py`

**Interfaces:**
- `WindowCoordinator.open_entity(reference, context=None)`.
- `WindowCoordinator.open_list(entity_type, context=None)`.
- `WindowCoordinator.register_window(key, window)` and `unregister_window(key)`.
- `WindowCoordinator.window_key(reference)` returns `(entity_type, entity_key)`.

- [ ] **Step 1: Test registering a window, re-opening the same key, and removing it after destruction.**
- [ ] **Step 2: Implement coordinator callbacks that activate existing windows and call main-window factories for new windows.**
- [ ] **Step 3: Add `self.window_coordinator` to the main window and pass it to query-capable viewers.**
- [ ] **Step 4: Change `show_video_library`, `show_actor_viewer`, `show_code_prefix_viewer`, `show_data_center`, `show_ladder_board_viewer`, and `show_masterpiece_viewer` to tracked `show()` windows instead of blocking `exec_()` calls.**
- [ ] **Step 5: Run focused tests and compile affected GUI modules.**

### Task 4: Build Unified Search Window

**Files:**
- Create: `app/gui/unified_search_viewer.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_unified_search_viewer.py`

**Interfaces:**
- `UnifiedSearchWindow(backend_client, coordinator, parent=None)`.
- Search input debounces by 250 ms and sends stale-result-safe async requests.
- Double-clicking a result calls `coordinator.open_entity(EntityReference(...), QueryContext(...))`.

- [ ] **Step 1: Test result activation produces the expected typed reference and context.**
- [ ] **Step 2: Implement grouped result table, empty/error/loading states, retry, and keyboard Enter activation.**
- [ ] **Step 3: Add a global “统一查询” button to the main window and reuse one search window instance.**
- [ ] **Step 4: Run focused viewer tests with `QT_QPA_PLATFORM=offscreen pytest tests/test_unified_search_viewer.py -q`.**

### Task 5: Integrate Cross-Window Links and Context Filters

**Files:**
- Modify: `app/gui/actor_detail_viewer.py`
- Modify: `app/gui/code_prefix_detail_viewer.py`
- Modify: `app/gui/video_list_detail_viewer.py`
- Modify: `app/gui/masterpiece_viewer.py`
- Modify: `app/gui/ladder_board_viewer.py`
- Modify: `app/gui/data_center_viewer.py`
- Modify: `app/gui/db_viewer.py`
- Modify: `app/gui/actor_viewer.py`
- Modify: `app/gui/code_prefix_viewer.py`
- Test: `tests/test_cross_window_navigation.py`

**Interfaces:**
- Detail viewers emit `navigation_requested = pyqtSignal(object)` carrying `NavigationRequest`.
- List viewers accept `apply_query_context(context)` and expose `clear_query_context()`.
- Data-center metric widgets emit `QueryContext` instead of opening hard-coded dialogs.

- [ ] **Step 1: Add tests for video -> actor, actor -> video, prefix -> video, masterpiece -> actor, and data-center -> filtered-list requests.**
- [ ] **Step 2: Add coordinator wiring and typed link buttons while preserving existing write buttons.**
- [ ] **Step 3: Implement list-view context application and visible filter chips/clear actions.**
- [ ] **Step 4: Run focused cross-window tests and existing viewer tests.**

### Task 6: Add Local Query History and Comparison Windows

**Files:**
- Create: `app/gui/query_history.py`
- Create: `app/gui/comparison_viewer.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_query_history.py`

**Interfaces:**
- `QueryHistoryStore(path=None).record_search(text)`, `.record_entity(reference)`, `.recent_searches()`, `.recent_entities()`.
- `ComparisonWindow` accepts two `EntityReference` values and loads read-only details asynchronously.

- [ ] **Step 1: Test bounded, deduplicated history with no database calls.**
- [ ] **Step 2: Implement JSON/settings-backed history and add recent items to the search window.**
- [ ] **Step 3: Implement actor/code-prefix comparison with copyable rows and error/retry states.**
- [ ] **Step 4: Run focused history/comparison tests.**

### Task 7: Verification and Regression Coverage

**Files:**
- Modify: relevant files from Tasks 1-6 only.
- Test: `tests/test_backend_service.py`, `tests/test_main_window.py`, and focused new tests.

- [ ] **Step 1: Run `python -m compileall app`.**
- [ ] **Step 2: Run focused new tests with `pytest -q`.**
- [ ] **Step 3: Run the full suite and record failures without hiding unrelated pre-existing failures.**
- [ ] **Step 4: Run `git diff --check` and inspect changed-file scope.**
- [ ] **Step 5: Verify no new query path contains POST/mutation calls or refresh flags.**
