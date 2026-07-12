# Queued Batch Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement queued enrichment submissions with explicit batch-count limits and execution-time database batch plans.

**Architecture:** The GUI remains the outer FIFO coordinator through `GuiTaskQueue`. Batch plan persistence lives in `VideoDatabase` with one metadata table and per-task item tables. Main-window enrichment submission captures immutable request payloads, creates database plans only when the queued worker starts, and runs bounded batch loops until the batch count or planned items are exhausted.

**Tech Stack:** Python 3.13, PyQt5, SQLite, pytest/unittest.

## Global Constraints

- Build batch work tables when the queued task starts executing, not when the user submits it.
- Keep each task kind isolated with its own item table.
- Batch count is a hard upper bound.
- If all planned items are marked before the batch count is reached, the task ends and the next queued task starts.
- The "补全信息" button stays available while enrichment is running or queued.
- Do not change scraper behavior.
- Do not rewrite the GUI task queue.

---

### Task 1: Dialog Batch Count Setting

**Files:**
- Modify: `app/gui/enrichment_dialog.py`
- Modify: `app/gui/i18n.py`
- Test: `tests/test_enrichment_dialog_actor_birthday.py`

**Interfaces:**
- Produces: `values()['batch_count'] -> int`
- Produces: every target/source settings dict includes `batch_count`

- [ ] **Step 1: Write the failing test**

Add a test that opens `EnrichmentDialog`, sets `batch_count_input` to `3`, and asserts `dialog.values()['batch_count'] == 3`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_enrichment_dialog_actor_birthday.py::EnrichmentDialogActorBirthdayTest::test_values_include_batch_count -q`
Expected: FAIL because `batch_count_input` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `batch_count` to defaults, normalization, saved settings, a `QSpinBox`, the form row `enrichment.dialog.batch_count`, and `values()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_enrichment_dialog_actor_birthday.py::EnrichmentDialogActorBirthdayTest::test_values_include_batch_count -q`
Expected: PASS.

### Task 2: Database Batch Plan Tables

**Files:**
- Modify: `app/data/database_handler.py`
- Test: `tests/test_supplement_tasks.py`

**Interfaces:**
- Produces: `create_enrichment_batch_plan(task_kind, target_type, source_key, batch_limit, batch_count_limit, combo_key='', candidates=None) -> dict`
- Produces: `list_enrichment_batch_items(plan_id, task_kind, status='pending', limit=None) -> list[dict]`
- Produces: `mark_enrichment_batch_item(plan_id, task_kind, sequence_index, status, error='') -> int`
- Produces: `finish_enrichment_batch_plan(plan_id, status='completed', error='') -> int`

- [ ] **Step 1: Write failing tests**

Add tests that create one plan per task kind, assert each task kind writes to its own table, assert no items exist before `create_enrichment_batch_plan()` is called, and assert item marking changes only that plan row.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_supplement_tasks.py::SupplementTaskTest::test_enrichment_batch_plan_tables_are_created_at_execution_time -q`
Expected: FAIL because plan methods do not exist.

- [ ] **Step 3: Write minimal implementation**

Create the metadata table and four item tables in `_init_db`. Implement the four methods above using deterministic task-kind-to-table mapping and generated UUID plan IDs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_supplement_tasks.py::SupplementTaskTest::test_enrichment_batch_plan_tables_are_created_at_execution_time -q`
Expected: PASS.

### Task 3: Main Window Queued Submission Behavior

**Files:**
- Modify: `app/gui/main_window.py`
- Test: `tests/test_main_window_startup.py`

**Interfaces:**
- Produces: `update_enrichment_controls()` keeps `btn_enrich` enabled.
- Produces: `start_batch_enrichment(values)` stores `batch_count_limit`.
- Produces: queued enrichment factories are captured per request and do not depend on a mutable shared `_queued_enrichment_worker_factory`.

- [ ] **Step 1: Write failing tests**

Add tests that call `update_enrichment_controls()` on a stub with an active task and assert `btn_enrich` remains enabled, and that `start_batch_enrichment()` records `batch_count_limit`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_enrichment_button_stays_enabled_while_task_is_active -q`
Expected: FAIL because the button is disabled.

- [ ] **Step 3: Write minimal implementation**

Remove the early block in `enrich_video_info()`. Pass worker factories directly into `_start_enrichment_task_runner(worker_factory, queued_kind, queued_mode, task_title)`. Store `batch_count_limit` in batch configs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_enrichment_button_stays_enabled_while_task_is_active -q`
Expected: PASS.

### Task 4: Bounded Batch Execution

**Files:**
- Modify: `app/gui/main_window.py`
- Modify: `app/services/enrichment/combo_enrichment_service.py`
- Test: `tests/test_main_window_startup.py`
- Test: `tests/test_combo_enrichment_service.py`

**Interfaces:**
- Produces: `batch_count_limit` passed into single and combo batch workers.
- Produces: single batch plans stop when `batch_enrichment_round >= batch_count_limit`.
- Produces: combo subtask loops stop when `batch_index >= batch_count_limit`.

- [ ] **Step 1: Write failing tests**

Add a main-window test that calls `on_enrichment_finished()` with `has_more_pending=True` after the configured last batch and asserts no next timer is scheduled. Add a combo-service test that a subtask with `batch_count_limit=2` runs exactly two batches when remaining work stays positive.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_batch_plan_stops_at_configured_batch_count tests/test_combo_enrichment_service.py::ComboEnrichmentServiceBatchLoopTest::test_batch_loop_stops_at_batch_count_limit -q`
Expected: FAIL because no batch-count cap exists.

- [ ] **Step 3: Write minimal implementation**

Add `batch_count_limit` to configs, status text, combo task settings normalization, and combo loop stop checks. Finish the current queued task instead of scheduling another batch when the count is reached.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_batch_plan_stops_at_configured_batch_count tests/test_combo_enrichment_service.py::ComboEnrichmentServiceBatchLoopTest::test_batch_loop_stops_at_batch_count_limit -q`
Expected: PASS.

### Task 5: Plan Creation on Worker Start

**Files:**
- Modify: `app/gui/main_window.py`
- Modify: `app/backend/client.py`
- Modify: `app/backend/service.py`
- Test: `tests/test_main_window_startup.py`

**Interfaces:**
- Produces: `BackendClient.create_enrichment_batch_plan(payload) -> dict`
- Produces: `BackendService.create_enrichment_batch_plan(payload) -> dict`
- Produces: main-window queued `before_start` creates the plan for batch requests before the worker starts.

- [ ] **Step 1: Write failing test**

Add a main-window test with a fake backend client and fake `_start_queued_gui_runner`. Assert `create_enrichment_batch_plan()` is not called by `start_batch_enrichment()`, then invoke captured `before_start` and assert it is called once.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_batch_plan_is_created_when_queued_task_starts_not_when_submitted -q`
Expected: FAIL because plan creation hook does not exist.

- [ ] **Step 3: Write minimal implementation**

Add the client/service endpoint method. Build candidate snapshots in the backend using existing candidate listing methods and pass them into `VideoDatabase.create_enrichment_batch_plan()`. In main-window `before_start`, call the backend method for batch requests and attach `plan_id` to the worker payload.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main_window_startup.py::MainWindowStartupTest::test_batch_plan_is_created_when_queued_task_starts_not_when_submitted -q`
Expected: PASS.

### Task 6: Verification

**Files:**
- Test: `tests/test_enrichment_dialog_actor_birthday.py`
- Test: `tests/test_supplement_tasks.py`
- Test: `tests/test_main_window_startup.py`
- Test: `tests/test_combo_enrichment_service.py`

- [ ] **Step 1: Run focused test suite**

Run: `python -m pytest tests/test_enrichment_dialog_actor_birthday.py tests/test_supplement_tasks.py tests/test_main_window_startup.py tests/test_combo_enrichment_service.py -q`
Expected: PASS.

- [ ] **Step 2: Run diff check**

Run: `git diff --check`
Expected: no whitespace errors.
