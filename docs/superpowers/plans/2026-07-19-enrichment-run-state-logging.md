# Enrichment Run State and Phase Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate current plan state, pause reason, and the previous run result, while recording claim, resolve, execute, and release phases for every enrichment run.

**Architecture:** Keep the existing `status` column as the canonical current state and expose it as `current_status` for callers. Add JSON-backed previous-run metadata to `enrichment_batch_plans`; update it once per run with phase counters and outcome. Add phase events to the existing per-run `TaskTraceLogger` without changing the HTTP contract.

**Tech Stack:** Python, SQLite, unittest/pytest, existing task trace logger and GUI task queue.

## Global Constraints

- Preserve existing `status`, `paused_reason`, and plan recovery behavior.
- Preserve pending rows when a run is paused, cancelled, or fails.
- Do not load the full candidate table solely for diagnostic logging.
- Every phase log must include `plan_id`, `task_kind`, `run_id`, and counts where available.

### Task 1: Persist Previous Run Metadata

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_enrichment_pending_queues.py`

- [ ] Add a failing test asserting plan progress exposes `current_status`, `last_run_id`, and parsed `last_run_result`.
- [ ] Add a failing test asserting a stored run result survives a fresh `VideoDatabase` instance.
- [ ] Add the migration columns with safe defaults and a method that stores the structured result.
- [ ] Keep `status` as the source of truth and return it under both `status` and `current_status`.

### Task 2: Record Four Execution Phases

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/services/enrichment/task_trace_logger.py` only if a helper is needed
- Test: `code/tests/test_enrichment_pending_queues.py` or a focused backend test

- [ ] Add failing tests for phase records and counts.
- [ ] Log claim before and after `_pending_enrichment_plan_items_for_run`.
- [ ] Log resolve before and after the enrichment service resolves candidates.
- [ ] Log execute around the service call with processed/success/failure counts.
- [ ] Log release before and after plan-item release and persist the previous-run result.

### Task 3: Keep GUI State Independent

**Files:**
- Modify: `code/app/gui/task_queue.py`
- Test: `code/tests/test_task_queue.py`

- [ ] Add a failing test showing a paused reason does not replace a running current status.
- [ ] Apply `current_status` and `last_run_result` separately when plan progress updates arrive.
- [ ] Keep the existing task table columns compatible while using the current status as the status display.

### Task 4: Verify

- [ ] Run focused tests.
- [ ] Run the full test suite.
- [ ] Run compile and diff checks.
