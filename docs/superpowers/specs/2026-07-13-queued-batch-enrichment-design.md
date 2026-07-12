# Queued Batch Enrichment Design

## Context

The application already has a GUI task queue that runs queued work in FIFO order. The enrichment flow also has single-task and batch-task modes, but the main "补全信息" button is disabled while an enrichment or batch plan is active. Batch enrichment currently controls only per-batch size and interval. It does not have an explicit batch-count cap, and it does not persist a per-task execution plan.

## Goals

- Allow users to open "补全信息" and submit more enrichment work while another enrichment task is running or queued.
- Run submitted enrichment work through the existing task queue in order.
- Add a batch count setting. A batch plan stops when it reaches the configured batch count, when all planned items are completed, when there are no eligible items, when the user stops it, or when manual verification/network failure stops enrichment.
- Build the batch work table when the queued task starts executing, not when the user submits it.
- Store each batch plan in database tables so completion state is explicit and resumable during the running task.
- Keep each task kind isolated with its own plan table.

## Non-Goals

- Do not change the core scraper behavior.
- Do not make batch enrichment infinite by default.
- Do not pre-reserve candidates at task submission time.
- Do not rewrite the existing GUI task queue.

## User Flow

1. User clicks "补全信息".
2. If another enrichment is running, the dialog still opens.
3. User chooses target/source and either a single enrichment task or batch enrichment.
4. The request is appended to the GUI task queue.
5. When the queued task reaches the front:
   - the application creates a new database plan for that task,
   - fills the corresponding task-specific plan table with the currently eligible candidates,
   - executes batches in order,
   - marks each processed item complete, failed, skipped, or stopped in the plan table.
6. If the plan has no remaining items before the configured batch count is reached, the plan ends and the next queued task starts.
7. If the batch count is reached while remaining items still exist, the plan ends cleanly and the next queued task starts.

## Batch Count Semantics

Batch count is a hard upper bound for a batch plan.

Example: "每批 5 个，执行 10 批" processes at most 50 planned items. If only 23 eligible items exist when the task starts, the task finishes after those 23 are marked and then releases the queue.

For combo batch tasks, each subtask uses its own per-batch limit and interval, but the shared batch-count cap applies to each subtask loop. A combo plan finishes when all subtasks have ended because they exhausted their plans, hit the batch-count cap, stopped, or require manual verification.

## Database Design

Add a shared plan metadata table:

```sql
CREATE TABLE IF NOT EXISTS enrichment_batch_plans (
    plan_id TEXT PRIMARY KEY,
    task_kind TEXT NOT NULL,
    target_type TEXT NOT NULL,
    source_key TEXT NOT NULL,
    combo_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    batch_limit INTEGER NOT NULL,
    batch_count_limit INTEGER NOT NULL,
    completed_batch_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    last_error TEXT NOT NULL DEFAULT ''
);
```

Add one item table per task family:

- `video_enrichment_batch_items`
- `code_prefix_enrichment_batch_items`
- `actor_enrichment_batch_items`
- `actor_birthday_enrichment_batch_items`

Each item table stores:

```sql
plan_id TEXT NOT NULL,
sequence_index INTEGER NOT NULL,
target_key TEXT NOT NULL,
code TEXT NOT NULL DEFAULT '',
source_key TEXT NOT NULL DEFAULT '',
status TEXT NOT NULL DEFAULT 'pending',
last_error TEXT NOT NULL DEFAULT '',
started_at TEXT,
completed_at TEXT,
PRIMARY KEY (plan_id, sequence_index)
```

Task-specific columns may be added where needed, for example `prefix` for code-prefix items and `actor_name` for actor items. The tables intentionally duplicate the minimal target identifiers needed to execute a planned item without re-querying the whole candidate set.

## Candidate Planning

The queued task creates its plan immediately before the worker starts enrichment. Candidate selection uses the same eligibility rules as the current enrichment services:

- video library: current video candidates for target/source,
- code-prefix library: current eligible prefix movie rows,
- actor library: current eligible actor movie rows,
- actor birthday: current actor birthday candidates,
- supplement tasks: current supplement candidates after filter settings.

The plan size should be capped by `batch_limit * batch_count_limit` so a limited task does not reserve more items than it can process.

If no candidates are inserted, the plan is marked completed with zero processed items and the queue advances.

## Execution Model

The GUI task queue remains the outer coordinator. Only one queued task executes at a time.

For a batch plan:

1. Load the next `batch_limit` pending items from that plan table.
2. Execute them through the existing enrichment service path.
3. Mark item rows as completed, failed, no-result, or stopped as each item reaches a terminal state.
4. Increment `completed_batch_count` after each batch attempt.
5. Stop the plan if:
   - `completed_batch_count >= batch_count_limit`,
   - no pending plan items remain,
   - no eligible work can be processed,
   - stop/cancel/manual-verification/network stop is requested.
6. Mark the plan completed/stopped/failed and release the queued task.

The existing progress widgets continue to show current task progress. The task queue table remains the source of ordering.

## Button Behavior

The "补全信息" button stays enabled while enrichment is running or queued. Submitting while work is active adds a new queue entry instead of showing "当前补全任务还没有结束。"

The "停止补全" button applies to the currently running enrichment plan. It does not delete later queued enrichment tasks. Later queued tasks still run unless the user removes them through a future queue-management feature.

## Error Handling

- Manual verification stops the current plan and marks the current item with the verification message.
- Network guard stop requests stop the current plan after the current item/batch boundary according to existing behavior.
- Per-item scraper failures mark the item failed and continue with the next item unless the existing service treats the error as terminal.
- If plan table creation or candidate insertion fails, the queued task fails and may retry under the existing queue retry rules.

## Testing

Add tests for:

- enrichment dialog includes and persists batch count,
- "补全信息" remains enabled while an enrichment task is active,
- submitting enrichment while active enqueues another task instead of blocking,
- batch plan tables are created when the task starts, not when submitted,
- batch execution stops at the configured batch count,
- batch execution ends early when all plan items are marked,
- each task family writes to its own item table,
- queued enrichment tasks run FIFO after the previous plan completes.
