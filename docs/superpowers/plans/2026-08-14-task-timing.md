# Task Timing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist effective execution time for every GUI task, excluding paused intervals, and show the current/final duration in the task list.

**Architecture:** Add a `gui_task_timing_records` repository alongside the existing GUI task repository. The queue owns timing transitions and persists monotonic active duration at state changes; the task viewer formats the stored/current duration. Existing task persistence and recovery remain the source of task state and resume behavior.

**Tech Stack:** Python, SQLite, PyQt5, unittest.

## Global Constraints

- Use parameterized SQL values and whitelist any dynamic SQL identifiers.
- Keep timing persistence failures non-fatal to task execution and log them.
- Exclude paused intervals from `active_seconds`.
- Preserve existing task pause, resume, cancellation, and startup recovery behavior.
- Use monotonic time for duration calculation and wall-clock timestamps only for display/audit.

---

### Task 1: Timing Repository

**Files:**
- Create: `code/app/data/repositories/gui_task_timing_repo.py`
- Modify: `code/app/data/repositories/__init__.py`
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_gui_task_timing_repository.py`

**Interfaces:**
- Produces `save_gui_task_timing(record)`, `update_gui_task_timing(task_id, **changes)`, `get_gui_task_timing(task_id)`, and `list_gui_task_timings(task_category=None)`.

- [ ] **Step 1: Write the failing repository tests**

Cover schema creation, insert/update, category filtering, and persistence of active/paused seconds.

- [ ] **Step 2: Run the repository tests and verify they fail**

Run from `code`: `python -m unittest tests.test_gui_task_timing_repository`.
Expected: import or missing-method failures because the timing repository does not exist.

- [ ] **Step 3: Implement the timing table and repository methods**

Create `gui_task_timing_records` with one row per task, indexed by `(task_category, status)` and `task_id`. Use parameterized values, explicit column mapping, JSON-free scalar fields, and commits matching `GuiTaskRepositoryMixin`.

- [ ] **Step 4: Register the mixin and initialize the table**

Add the mixin to `VideoDatabase` and call its schema initializer during database initialization.

- [ ] **Step 5: Run the repository tests and verify they pass**

Run the same command; expected output is `OK`.

### Task 2: Queue Timing State Machine

**Files:**
- Modify: `code/app/gui/task_queue.py`
- Modify: `code/app/gui/main_window.py`
- Test: `code/tests/test_task_queue_timing.py`

**Interfaces:**
- Consumes the timing repository configured on the queue.
- Produces timing updates at running, paused, resumed, and terminal transitions.

- [ ] **Step 1: Write failing queue timing tests**

Use an injected clock and in-memory persistence double to assert that running time accumulates, paused intervals are excluded, resume continues the same row, and terminal states close the record.

- [ ] **Step 2: Run tests and verify the expected failure**

Run: `python -m unittest tests.test_task_queue_timing` from `code`.
Expected: missing timing configuration or timing assertions fail.

- [ ] **Step 3: Implement timing state transitions**

Add queue timing persistence configuration, track `active_seconds`, `paused_seconds`, `last_resumed_at`, and counters on `TaskRecord`, and persist timing safely from `_persist_record`/state transitions. Use `time.monotonic()` for intervals and `datetime.now()` for display timestamps. Catch and log repository errors without changing task state results.

- [ ] **Step 4: Connect application startup**

Configure the queue with the timing repository instance created from the same database connection path. Close stale running timing intervals as part of startup recovery before restoring resumable tasks.

- [ ] **Step 5: Run queue and startup tests**

Run: `python -m unittest tests.test_task_queue_timing tests.test_task_persistence_startup tests.test_main_window_startup`.
Expected: all tests pass.

### Task 3: Task List Display

**Files:**
- Modify: `code/app/gui/task_queue_viewer.py`
- Test: `code/tests/test_task_queue_viewer.py`

**Interfaces:**
- Consumes `TaskRecord.active_seconds` and timing persistence values.
- Displays a formatted `耗时` column without changing pause/resume/delete controls.

- [ ] **Step 1: Write the failing viewer test**

Assert the table has an `耗时` column and formats a sample duration as `01:02:03`.

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m unittest tests.test_task_queue_viewer`.
Expected: the column or formatted value is missing.

- [ ] **Step 3: Implement formatting and display**

Add a stable duration column and a small formatter that displays active elapsed time for running tasks and persisted final active time for terminal tasks.

- [ ] **Step 4: Run viewer tests**

Expected: `OK`.

### Task 4: Integration Verification

**Files:**
- Test: existing queue, repository, startup, viewer, and full test suite.

- [ ] **Step 1: Run focused timing tests**

Run: `python -m unittest tests.test_gui_task_timing_repository tests.test_task_queue_timing tests.test_task_queue_viewer tests.test_task_persistence_startup tests.test_main_window_startup`.

- [ ] **Step 2: Run syntax and diff checks**

Run the project compile check and `git diff --check`.

- [ ] **Step 3: Run the complete suite**

Run from `code`: `python -W ignore::ResourceWarning -m unittest discover -s tests -q`.
Expected: all tests pass with exit code 0.
