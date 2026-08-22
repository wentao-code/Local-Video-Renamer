# Task Log Linkage Design

## Goal

Allow every persisted GUI task to open the logs associated with its trace ID and any explicit log path returned by the business operation.

## Scope

This phase covers task metadata persistence and read-only log inspection. It does not change log rotation, multi-process handlers, or exception logging policy.

## Architecture

- Add an optional `log_path` column to `gui_task_records`; old databases receive the column through the existing additive schema migration path.
- Pass the operation result into task completion metadata so explicit paths such as enrichment or subtitle logs are persisted without changing business result formats.
- Add a `TaskLogResolver` that scans the existing runtime log directories by `trace_task_id`, reads bounded matching lines, and reports missing or unreadable files.
- Add a read-only task-log dialog opened from the task list. The dialog shows task identity, explicit paths, and matched log lines.

## Constraints

- All SQL values remain parameterized.
- Existing task IDs, task statuses, pause/resume behavior, and result payloads remain backward compatible.
- Log inspection must not create a new business task or mutate log files.
- The viewer must bound displayed output so a large log cannot exhaust the GUI.

## Acceptance Criteria

1. Existing databases open and persist tasks after the new column is added.
2. A completed task keeps an explicit `log_path` found in its result.
3. A task with no explicit path can still find matching lines by `trace_task_id`.
4. The task list opens a log dialog for one selected task and reports no matches clearly.
5. Existing tests and the full test suite pass.
