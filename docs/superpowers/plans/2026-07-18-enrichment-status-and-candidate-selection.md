# Enrichment Status And Candidate Selection Implementation Plan

**Goal:** Refactor actor, video, and code-prefix enrichment status display to use `x/y/z/f/s/w`, separate candidate selection from enrichment execution, and make execution consume only selected pending queues.

**Architecture:** Keep detailed database statuses unchanged and add a centralized display-status mapper. Candidate selection will build and persist plans into the existing `pending_*` tables; execution will resolve an existing selected plan and claim rows into `enrichment_running_items` without rebuilding candidates. Library viewers will request display statuses from the backend and expose an explicit `入选任务` action.

**Tech Stack:** Python, SQLite, PyQt5, existing HTTP backend, pytest.

## Status Contract

- `x`: not selected and not completed.
- `y`: attempted, no search result.
- `z`: search result exists, details missing.
- `f`: search result exists and details are complete.
- `s`: execution failed and is retryable.
- `w`: selected into a pending queue or currently running.
- Detailed raw statuses remain persisted for retries, errors, and source-specific logic.

## Implementation Tasks

1. Add centralized raw-to-display status mapping and queue-overlay helpers.
2. Add database APIs to select candidates and resolve selected plans without rescanning during execution.
3. Change backend task creation/execution flow so selection creates pending rows and enrichment only claims existing rows.
4. Add actor and code-prefix viewer `入选任务` controls and route them to selection APIs.
5. Update actor, code-prefix, video, and detail/status renderers to show the six display states with source-specific aggregation.
6. Add regression tests for each raw state, pending/running precedence, selection-only behavior, and execution not rebuilding candidates.
7. Run focused and full test suites, then inspect the final diff.
