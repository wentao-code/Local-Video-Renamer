# Persistent Enrichment Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make enrichment plans durable across restart and view/task mode changes, expose their real progress, and prevent duplicate detail execution.

**Architecture:** SQLite remains the source of truth for plans and the four existing per-task-kind detail tables. The GUI queue only schedules the next runnable plan batch and mirrors plan progress. Runtime mode is stored in `config/user/runtime_settings.json`; startup recovers abandoned running claims before optionally rehydrating unfinished plans.

**Tech Stack:** Python 3, SQLite, PyQt5, unittest/pytest, existing HTTP backend client/server.

---

### Task 1: Persist plan and detail execution state

**Files:**
- Modify: `app/data/database_handler.py`
- Test: `tests/test_supplement_tasks.py`

- [ ] **Step 1: Add failing database tests**

Add tests that create a plan, claim one batch, assert `running`, `started_at`, `claimed_at`, and `attempt_count`, then mark results and assert `completed_batch_count` plus pending/completed/failed counts. Add a restart test that leaves a plan/detail running, calls recovery, and asserts the plan is paused and the detail is pending without touching an already completed detail.

- [ ] **Step 2: Run the focused tests and verify failure**

Run `pytest tests/test_supplement_tasks.py -q`. The new tests must fail because the claim, progress, and recovery APIs do not yet exist.

- [ ] **Step 3: Extend the schema with migrations**

Keep `video_enrichment_batch_items`, `code_prefix_enrichment_batch_items`, `actor_enrichment_batch_items`, and `actor_birthday_enrichment_batch_items`. Add plan columns `paused_reason`, `updated_at`, and `last_started_at`; add detail columns `attempt_count`, `claimed_at`, and `updated_at`, using `_ensure_column` so existing databases migrate safely.

- [ ] **Step 4: Implement atomic claim and recovery APIs**

Implement `claim_enrichment_batch_items(plan_id, task_kind, batch_limit)` in one SQLite transaction. Select only pending or retryable failed rows in sequence order, update them conditionally to `running`, set `claimed_at`/`started_at`, increment `attempt_count`, and return the claimed rows. Implement `recover_running_enrichment_plans(reason)` so running detail rows become pending and running plans become paused, while completed rows remain unchanged.

- [ ] **Step 5: Implement progress aggregation and plan state updates**

Add `get_enrichment_batch_plan_progress`, `list_resumable_enrichment_plans`, and `update_enrichment_plan_progress`. Aggregate pending, running, completed, and failed counts from the task-kind table; increment `completed_batch_count` only when a claimed batch actually completes; set completed only when no pending/retryable/running rows remain; store pause/error reasons and `updated_at` on every transition.

- [ ] **Step 6: Run database tests and the existing supplement tests**

Run `pytest tests/test_supplement_tasks.py -q` and confirm all pass.

### Task 2: Make the backend consume claimed plan details

**Files:**
- Modify: `app/backend/service.py`
- Modify: `app/backend/client.py`
- Modify: `app/backend/server.py`
- Test: `tests/test_backend_reuse.py`

- [ ] **Step 1: Add failing service tests**

Test that `_pending_enrichment_plan_items_for_run` claims a batch rather than merely listing pending rows, and that `_apply_enrichment_batch_plan_result` marks only claimed rows, updates progress, and leaves a stopped plan resumable. Add client/server route tests for listing resumable plans and fetching plan progress.

- [ ] **Step 2: Run focused tests and verify failure**

Run `pytest tests/test_backend_reuse.py -q`. The new assertions must fail against the list-only implementation.

- [ ] **Step 3: Wire service execution to database claims**

Change `_pending_enrichment_plan_items_for_run` to call `claim_enrichment_batch_items`. Update result marking to use claimed/running rows, release unprocessed rows back to pending when cancellation is requested, preserve retryable failures, and call the database progress update at the end of every planned batch. Keep the existing non-plan path unchanged.

- [ ] **Step 4: Add read APIs through HTTP**

Add `BackendService.list_enrichment_plans` and `get_enrichment_plan_progress`, then expose `GET /database/enrich/plans` and `GET /database/enrich/plan-progress?plan_id=...&task_kind=...`. Add matching `BackendClient` methods using `urlencode`.

- [ ] **Step 5: Run backend tests**

Run `pytest tests/test_backend_reuse.py tests/test_supplement_tasks.py -q` and confirm all pass.

### Task 3: Persist runtime mode and recover plans at startup

**Files:**
- Modify: `app/core/project_paths.py`
- Create: `app/gui/runtime_settings.py`
- Modify: `app/gui/main_window.py`
- Test: `tests/test_main_window_startup.py`
- Test: `tests/test_runtime_settings.py`

- [ ] **Step 1: Add failing runtime settings tests**

Test missing/corrupt settings default to `task`, valid `view` survives save/load, and unknown modes normalize to `task`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run `pytest tests/test_runtime_settings.py -q`; it must fail before the settings module exists.

- [ ] **Step 3: Implement safe runtime settings persistence**

Add `RUNTIME_SETTINGS_FILE` and `load_runtime_mode`/`save_runtime_mode`. Write JSON with UTF-8 and replace a temporary file so a shutdown during write cannot leave invalid settings.

- [ ] **Step 4: Add startup mode ordering**

Load the saved mode before setting the queue mode. On startup call backend recovery, then query resumable plans. In view mode leave them persisted as paused and do not enqueue runners; in task mode rehydrate unfinished plans. Save the mode immediately in `set_runtime_mode`, before requesting cancellation when switching to view.

- [ ] **Step 5: Add mode-switch tests**

Test that switching to view persists `view`, requests cancellation for active enrichment, and switching back to task asks the backend for resumable plans. Test startup with saved view does not start an enrichment worker, while saved task requeues one.

- [ ] **Step 6: Run startup/runtime tests**

Run `pytest tests/test_runtime_settings.py tests/test_main_window_startup.py -q` and confirm all pass.

### Task 4: Rehydrate the GUI queue and show plan progress

**Files:**
- Modify: `app/gui/task_queue.py`
- Modify: `app/gui/main_window.py`
- Modify: `app/gui/task_queue_viewer.py`
- Test: `tests/test_task_queue.py`
- Test: `tests/test_task_queue_viewer.py`

- [ ] **Step 1: Add failing queue and viewer tests**

Test a queue record can carry plan id, current/total batches, pending/success/failure counts, and pause reason; a pause request keeps the callback for later resume; and the viewer creates columns for all requested plan fields.

- [ ] **Step 2: Run focused tests and verify failure**

Run `pytest tests/test_task_queue.py tests/test_task_queue_viewer.py -q` and confirm the new fields/columns are absent.

- [ ] **Step 3: Extend queue records and pause semantics**

Add plan/progress fields and `pause_requested` to `TaskRecord`. Add `update_record_plan`, `update_plan_progress`, and `request_pause`; when cleanup arrives after a pause request, keep the record paused and retain its callback instead of marking it completed. Resume paused records only in task mode and prevent duplicate plan records during startup hydration.

- [ ] **Step 4: Attach plan state when execution really starts**

Pass the queue record to the enrichment `before_start` hook. Create the plan there, update the record with its id/progress, and use the same plan id for every resumed batch. Do not create detail rows when the user only submits a queued task.

- [ ] **Step 5: Expand task list rendering**

Add plan id, batch progress, pending, success, failed, and pause reason columns while retaining existing task columns. Populate blank values for ordinary view tasks and color exhausted/failed rows consistently.

- [ ] **Step 6: Run queue/viewer tests**

Run `pytest tests/test_task_queue.py tests/test_task_queue_viewer.py -q` and confirm all pass.

### Task 5: Wire persisted plans into batch continuation and validate end to end

**Files:**
- Modify: `app/gui/main_window.py`
- Modify: `app/backend/service.py`
- Modify: `tests/test_main_window_startup.py`
- Modify: `tests/test_backend_reuse.py`

- [ ] **Step 1: Add failing resume tests**

Create a persisted plan with two batches, simulate startup recovery in task mode, run the first rehydrated callback, and assert the same plan id is passed to the worker and the next batch is scheduled only while pending details remain. Assert a stopped batch does not increment completed batches.

- [ ] **Step 2: Implement plan rehydration**

Build runner configuration from persisted plan metadata, enqueue one GUI record per resumable plan, and set batch round from `completed_batch_count`. Reuse the existing batch timer only when the plan still has pending details and remaining batch capacity; if all details are exhausted early, finish immediately and continue to the next queued plan.

- [ ] **Step 3: Persist pause reasons on all stop paths**

When view mode, user stop, network cancellation, or exception interrupts a planned run, write `paused`/`failed` with a reason before cleanup. On normal completion update plan progress before the queue record is completed.

- [ ] **Step 4: Run the complete regression suite**

Run `pytest -q`, `python -m compileall app tests`, and `git diff --check`. Expected result: all tests pass, compilation succeeds, and no new whitespace errors are reported.

---

## Self-review

- Database durability, claim/retry state, restart recovery, completed batch counting, and progress aggregation are covered by Tasks 1 and 2.
- Mode persistence and the required startup ordering are covered by Task 3.
- Queue hydration, pause retention, duplicate prevention, and all requested task-list fields are covered by Task 4.
- Same-plan batch continuation, early exhaustion, and stop/error persistence are covered by Task 5.
- No placeholder implementation steps are used; each task names the exact files, APIs, tests, and verification commands.
