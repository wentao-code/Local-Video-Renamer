# Queen Author-First Crawl Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route newly crawled records to the independent queen author library before the queen keyword video library.

**Architecture:** Normalize each crawl result into a staging row, classify it against enrolled authors in the same transaction, and write author matches to an independent author-record table plus author links. Only unmatched rows are inserted into `queen_videos`; existing historical rows and background match jobs remain compatible.

**Tech Stack:** Python, SQLite WAL, existing `QueenLibraryService`, pytest.

## Global Constraints

- Keep all data in the independent `queen_library.db`.
- Use parameterized SQL and one transaction for staging, routing, and cleanup.
- Reuse `_raw_title_contains_author()` for author matching.
- Do not migrate or delete existing `queen_videos` rows.
- Keep duplicate crawls idempotent and preserve multi-author matches.

---

### Task 1: Add failing service tests

**Files:** `code/tests/test_queen_library_service.py`

- [x] Add a test that enrolls `黑喵`, crawls a matching and an unmatched record, and asserts only the unmatched record exists in `queen_videos` while the matching record appears in author detail.
- [x] Add a test for repeated crawls and a record matching two authors; assert one author-owned record and two author links.
- [x] Add a test that removing an author cleans author-owned links/records but keeps ordinary `queen_videos` rows.
- [x] Run the focused tests and confirm they fail because author-only storage/routing does not exist.

### Task 2: Add author-owned storage and staging schema

**Files:** `code/app/queen_library/service.py`

- [x] Add `queen_crawl_staging`, `queen_author_video_records`, and `queen_author_video_links` with unique keys and indexes.
- [x] Keep current historical `queen_author_videos` unchanged for rows backed by `queen_videos`.
- [x] Add normalized row helpers and parameterized insert/upsert helpers.
- [x] Run the focused tests again and confirm the schema-only changes still fail on routing behavior.

### Task 3: Route crawl imports author-first

**Files:** `code/app/queen_library/service.py`, `code/tests/test_queen_library_service.py`

- [x] Stage normalized records before the current queen insertion loop.
- [x] Query enrolled authors and route each matching staged record to author-owned storage, linking all matching authors.
- [x] Route only unmatched staged records through the current keyword resolution and `queen_videos` insert path.
- [x] Delete successful staging rows and mark failed batches without exposing SQL details to the UI.
- [x] Run the focused service tests and confirm they pass.

### Task 4: Display and clean up author-owned records

**Files:** `code/app/queen_library/service.py`, `code/tests/test_queen_library_service.py`

- [x] Union historical relation-backed videos with author-owned videos in author detail and count queries.
- [x] Include author-owned records in author list counts without scanning `queen_videos`.
- [x] Delete author links and orphaned author-owned records when an author is removed.
- [x] Run all queen-library tests.

### Task 5: Regression verification

**Files:** `code/app/queen_library/service.py`, existing queen tests as needed

- [x] Run the complete pytest suite.
- [x] Run `python -m compileall -q code`.
- [x] Run `git diff --check`.
- [x] Confirm no main actor-library schema or API changed.
