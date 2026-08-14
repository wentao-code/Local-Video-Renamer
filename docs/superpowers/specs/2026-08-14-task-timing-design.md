# Task Timing Design

## Goal

Record the effective execution time of every GUI task and retain timing details by task type for later troubleshooting and statistics.

## Timing Semantics

- A task starts timing when the queue transitions it from waiting to running.
- Paused time is excluded from effective duration.
- Resuming a task continues the same timing record rather than creating a new task timing identity.
- Completion, terminal failure, partial completion, and cancellation close the timing record.
- A task interrupted by application restart is kept resumable when supported; its timing remains open until it resumes or is finally closed.

## Data Model

Add `gui_task_timing_records` as a separate table. It stores one row per GUI task and includes:

- `task_id`, `trace_task_id`, `task_category`, `title` for lookup and grouping;
- `started_at`, `ended_at`, `last_resumed_at`, `paused_at`;
- `paused_seconds`, `active_seconds`;
- `status`, `pause_count`, `resume_count`, and `close_reason`;
- `created_at`, `updated_at`.

`active_seconds` is calculated from monotonic elapsed intervals in the process and persisted whenever the task state changes. Wall-clock timestamps are stored for display and audit only.

## Integration

The task queue owns timing state transitions and calls the repository when a task enters running, paused, resumed, or terminal state. The existing `gui_task_records` table remains the task snapshot/source of truth; the new table is the timing ledger and does not replace task state persistence.

The task list adds an execution-time column showing the current effective duration, formatted as `HH:MM:SS`. Existing task controls and recovery behavior remain unchanged.

## Failure Handling

Timing persistence errors are logged and must not crash or change the task worker result. Missing legacy timing rows are created lazily when a task first enters a tracked state. Stale running tasks are marked paused on startup and their persisted active interval is closed before recovery.

## Verification

- Repository tests cover table creation, upsert, status filtering, and type grouping.
- Queue tests cover start, pause, resume, completion, failure, cancellation, and restart persistence.
- Viewer tests cover time display without changing existing pause/delete behavior.
- Full test suite and syntax checks must pass.
