# Persistent Task Recovery Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with test-first development and verification checkpoints.

**Goal:** Keep queued task records visible across mode changes and restore the same persisted records after an unexpected application exit without creating tasks during mode switching.

**Architecture:** Runtime mode controls scheduling eligibility only. `GuiTaskQueue` owns the existing task records and distinguishes user pauses from mode-switch waiting. Startup recovery loads persisted GUI task records through `TaskResumeRegistry`; mode changes never query backend plans or enqueue replacement records.

**Tech Stack:** Python, PyQt5, SQLite persistence, unittest.

## Global Constraints

- Preserve unrelated existing worktree changes.
- Do not restore manually paused tasks when switching to task mode.
- Keep resumable persisted records in the task queue with their original `task_id`.

---

### Task 1: Lock down queue mode semantics

**Files:**
- Modify: `code/tests/test_task_queue.py`
- Modify: `code/app/gui/task_queue.py`

- [x] Add tests proving task mode restores only `等待模式切换`, while a user `已暂停` record remains paused.
- [x] Run the focused queue tests and verify the new assertion fails against the current implementation.
- [x] Change `set_run_mode` so task mode only requeues mode-switch waiting records; leave user-paused records unchanged.
- [x] Run the focused queue tests and verify they pass.

### Task 2: Remove plan re-enqueue from mode switching

**Files:**
- Modify: `code/tests/test_main_window_startup.py`
- Modify: `code/app/gui/main_window.py`

- [x] Add a regression test proving `set_runtime_mode('task')` does not call `recover_unfinished_enrichment_plans`.
- [x] Run the focused main-window test and verify it fails because the current transition invokes recovery.
- [x] Remove the transition-time and automatic startup recovery calls while leaving explicit plan recovery behavior intact.
- [x] Run the focused main-window tests and verify they pass.

### Task 3: Verify restart recovery keeps original records

**Files:**
- Modify: `code/tests/test_task_persistence_startup.py`
- Modify: `code/tests/test_task_resume_registry.py` if required by coverage

- [x] Add a regression assertion that an interrupted persisted task is restored with the same `task_id`, remains in the queue, and can be resumed through its registered callback.
- [x] Run persistence and resume-registry tests.
- [x] Run the full test suite and inspect the diff for unrelated changes.
