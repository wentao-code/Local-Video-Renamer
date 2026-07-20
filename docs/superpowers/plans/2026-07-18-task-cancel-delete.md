# Task Cancellation And Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow selected task-list tasks to be cancelled and deleted without future scheduling, database locks, orphaned running rows, or late background writes reviving the task.

**Architecture:** The database owns an atomic `cancelled` plan transition and removes that plan's queued/running items. The GUI queue owns task cancellation and removes waiting callbacks; running tasks receive the existing cancellation signal and are finalized as deleted after the worker exits. The task viewer selects rows and invokes the queue/database cancellation path, while retaining a deleted audit row.

**Tech Stack:** Python, SQLite, PyQt5, unittest.

## Global Constraints

- Deleting a task must not delete library records or unrelated plans.
- Running task cancellation must be idempotent and tolerate a late worker callback.
- A cancelled plan must never be returned by resumable-plan discovery or claimed for execution.
- Candidate rows belonging to a deleted plan are removed so a later selection pass can select them again.

### Task 1: Database cancellation lifecycle

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_enrichment_pending_queues.py`

- [ ] Add failing tests for cancelling pending, paused, and running plan items, verifying source/running rows are removed, plan status is `cancelled`, and late item updates do not change it.
- [ ] Add `cancel_enrichment_batch_plan(plan_id, task_kind, reason)` using one SQLite transaction.
- [ ] Exclude `cancelled` plans from resumable discovery and claim operations.
- [ ] Guard progress/item updates from changing a cancelled plan.
- [ ] Run the database tests and verify the new tests fail before implementation and pass afterward.

### Task 2: GUI task queue cancellation

**Files:**
- Modify: `code/app/gui/task_queue.py`
- Test: `code/tests/test_task_queue.py` or the existing GUI task queue test module.

- [ ] Add failing tests showing a waiting task is removed from scheduling and a running task receives a cancellation request.
- [ ] Add `TASK_STATUS_CANCELLING` and `TASK_STATUS_DELETED`.
- [ ] Add `cancel_task(task_id, reason)` and multi-task cancellation support.
- [ ] Remove waiting callbacks immediately; keep running records until worker cleanup confirms exit.
- [ ] Make late `mark_completed`/`mark_failed` calls unable to revive a deleted task.

### Task 3: Backend cancellation bridge

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/backend/server.py`
- Modify: `code/app/backend/client.py`
- Modify: `code/app/gui/main_window.py`
- Test: `code/tests/test_enrichment_pending_queues.py`, `code/tests/test_main_window_startup.py`

- [ ] Add a backend endpoint for cancelling a plan and invoke the database atomic cancellation method.
- [ ] Connect running-task cancellation to the existing enrichment cancel event.
- [ ] On worker cleanup, finalize the GUI task as deleted and refresh plan progress.
- [ ] Ensure cancelled plans are not re-enqueued during startup recovery.

### Task 4: Task list selection and deletion UI

**Files:**
- Modify: `code/app/gui/task_queue_viewer.py`
- Modify: `code/app/gui/i18n.py`
- Test: `code/tests/test_task_queue_viewer.py` or the existing GUI test module.

- [ ] Enable row selection and add a `删除选中任务` button.
- [ ] Disable deletion when no eligible task is selected.
- [ ] Confirm deletion and show the affected task count.
- [ ] Display cancelling/deleted states and keep deleted history rows visible.

### Task 5: Verification

- [ ] Run all enrichment queue and GUI task queue tests.
- [ ] Run `python -m compileall` for modified Python modules.
- [ ] Run `git diff --check` and inspect only intended changes.
