# Task Log Linkage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each persisted task directly traceable to explicit log files and matching central log lines from the task list.

**Architecture:** Extend the existing SQLite task record with an optional log path, pass task results into queue completion metadata, and resolve logs by trace ID across the existing runtime directories. Add a bounded read-only Qt dialog and a single-selection action in the task list.

**Tech Stack:** Python, SQLite, PyQt5, pytest.

## Global Constraints

- Preserve existing task statuses, pause/resume behavior, and task result payloads.
- Use additive SQLite schema changes and parameterized SQL values.
- Keep log inspection read-only and bounded.
- Do not change log rotation or multi-process logging in this phase.

---

### Task 1: Persist Explicit Task Log Paths

**Files:**
- Modify: `code/app/gui/task_queue.py`
- Modify: `code/app/data/repositories/gui_task_repo.py`
- Test: `code/tests/test_gui_task_repository.py`
- Test: `code/tests/test_task_queue.py`

Interfaces:
- `TaskRecord.log_path: str` stores the primary explicit log path.
- `GuiTaskQueue.mark_completed(task_id, result=None)` and `mark_partial(task_id, error_message, result=None)` extract `log_path` from dictionary results.

- [ ] Write failing repository and queue metadata tests.
- [ ] Run the focused tests and verify they fail because `log_path` is not persisted.
- [ ] Add the additive `log_path` column and queue serialization.
- [ ] Pass result metadata through completion paths and run focused tests.

### Task 2: Add Bounded Log Resolution

**Files:**
- Create: `code/app/gui/task_log_resolver.py`
- Test: `code/tests/test_task_log_resolver.py`

Interfaces:
- `TaskLogResolver.resolve(trace_task_id, explicit_log_path='', max_lines=1000)` returns a dictionary containing `trace_task_id`, `explicit_paths`, `matched_files`, `lines`, and `errors`.

- [ ] Write failing tests for trace-ID matching, explicit path reporting, missing files, and line limits.
- [ ] Run the focused resolver tests and verify they fail because the resolver does not exist.
- [ ] Implement bounded UTF-8 replacement-mode scanning over `LOG_DIR`, `TASK_TRACE_LOG_DIR`, and `COMBO_TASK_LOG_DIR`.
- [ ] Run the resolver tests.

### Task 3: Add Task List Log Viewer

**Files:**
- Create: `code/app/gui/task_log_viewer.py`
- Modify: `code/app/gui/task_queue_viewer.py`
- Test: `code/tests/test_task_queue_viewer.py`

Interfaces:
- `TaskLogViewerWindow(task_record, resolver=None, parent=None)` displays task identity, paths, and bounded matching lines.
- `TaskQueueViewerWindow.view_selected_task_logs()` opens the dialog for exactly one selected task.

- [ ] Write failing UI tests for the action state and task identity rendering.
- [ ] Run focused UI tests and verify they fail.
- [ ] Add the read-only dialog and task-list action.
- [ ] Run focused UI tests and the full test suite.

### Task 4: Final Verification

**Files:**
- Verify: all files above

- [ ] Run `git diff --check`.
- [ ] Run `PYTHONPATH=code python -m pytest -q`.
- [ ] Confirm only the intended task-log linkage files and existing user changes are present.
