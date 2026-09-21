# Queen Author Match Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make queen-author enrollment immediate by storing author-video matches in an indexed relation table and backfilling existing videos in resumable background batches.

**Architecture:** `queen_author_videos` stores only confirmed author/video matches. `queen_author_match_jobs` stores one resumable cursor per author. Enrollment inserts the author/source relation and queues a job; the backend worker processes bounded batches and the viewer polls the detail snapshot until completion. New video imports are matched only against enrolled authors.

**Tech Stack:** Python, SQLite WAL, existing backend worker/thread pattern, PySide5, pytest.

## Global Constraints

- Keep all data in the independent `queen_library.db`.
- Do not scan `queen_videos` from author list/detail or queen list requests.
- Use `raw_title` substring matching with the existing trimmed/casefold behavior.
- Preserve queen/video data when authors are removed.
- Keep enrollment idempotent and make batch processing restartable from `last_video_id`.

---

### Task 1: Relation tables and batch service

**Files:** `code/app/queen_library/service.py`, `code/tests/test_queen_library_service.py`

- [x] Add failing tests for immediate enrollment, resumable batches, relation-table detail queries, new-import matching, and removal cleanup.
- [x] Run those tests and confirm the missing job/relation behavior.
- [x] Add `queen_author_videos` and `queen_author_match_jobs` with indexes and foreign keys.
- [x] Make `add_queen_author()` enqueue and return without historical scanning.
- [x] Implement `process_queen_author_match_job()` and expose job progress in author detail/list rows.
- [x] Update import, rename, delete, and remove paths to maintain relations.
- [x] Upgrade legacy enrolled authors by creating resumable pending match jobs.
- [x] Run service tests.

### Task 2: Backend worker and progress snapshots

**Files:** `code/app/backend/service.py`, `code/app/backend/client.py`, `code/app/backend/server.py`, `code/tests/test_queen_author_library_backend.py`

- [x] Add failing tests for background job startup, progress snapshots, and restart of pending jobs.
- [x] Start a per-job backend thread after enrollment and resume pending jobs during backend initialization.
- [x] Keep mutation response immediate and invalidate only relevant queen-author snapshots.
- [x] Run backend tests.

### Task 3: Smooth author detail refresh

**Files:** `code/app/queen_library/viewer.py`, `code/tests/test_queen_library_viewer.py`

- [x] Add failing tests for polling while matching and stopping polling after completion.
- [x] Add a timer to author detail that refreshes the fast relation-table snapshot and displays progress.
- [x] Keep the existing immediate close-and-return behavior after enrollment.
- [x] Run queen-library tests.

### Task 4: Regression verification

- [x] Run all queen-library tests and the complete pytest suite.
- [x] Run `py_compile` and `git diff --check`.
- [x] Verify no main actor-library schema or API was changed.
