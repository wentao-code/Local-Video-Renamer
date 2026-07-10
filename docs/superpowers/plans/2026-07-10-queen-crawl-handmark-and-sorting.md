# Queen Crawl Hand Mark And Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent `hand_mark` skip flag to `queen_crawl_queue_log` and update queen button ordering to place rows without `like_level` first, then tiered rows by `A/B/C/D`, with alphabetical ordering inside each group.

**Architecture:** Keep the queue-skip behavior in `QueenLibraryService` so manual SQL edits immediately affect refresh behavior. Keep presentation ordering in `queen_library_sorting.py`, while extending `list_queens()` to expose `like_level` so the viewer can sort consistently.

**Tech Stack:** Python, SQLite, PyQt5, pytest/unittest

## Global Constraints

- `queen_crawl_queue_log.hand_mark = 1` must prevent that keyword from entering refresh work.
- Marked queue rows must survive successful refresh cleanup so the skip remains effective.
- Queen rows without `like_level` sort before rows with `like_level`.
- Ranked queen rows sort by `A`, `B`, `C`, `D`; ties sort by normalized queen name.

---

### Task 1: Queue Skip Flag

**Files:**
- Modify: `app/services/queen_library_service.py`
- Test: `tests/test_queen_library_service.py`

**Interfaces:**
- Consumes: `QueenLibraryService.refresh_all(show_browser=True, batch_size=None, progress_callback=None, should_stop=None)`
- Produces: `queen_crawl_queue_log.hand_mark`, queue preparation that excludes marked rows, cleanup that preserves marked rows

- [ ] Write failing tests for marked rows being skipped and preserved.
- [ ] Run the focused service tests and confirm the new expectations fail first.
- [ ] Implement the minimal schema and queue preparation changes in `QueenLibraryService`.
- [ ] Re-run the focused service tests and confirm they pass.

### Task 2: Queen Button Sorting

**Files:**
- Modify: `app/services/queen_library_service.py`
- Modify: `app/gui/queen_library_sorting.py`
- Test: `tests/test_queen_library_sorting.py`

**Interfaces:**
- Consumes: `sort_queen_rows(rows)` and `QueenLibraryService.list_queens()`
- Produces: row dictionaries that include `like_level` and a sorter that groups empty levels first, then `A/B/C/D`

- [ ] Write failing sorting tests for empty-level-first and A/B/C/D ordering.
- [ ] Run the focused sorting tests and confirm they fail first.
- [ ] Implement the minimal query and sort-key changes.
- [ ] Re-run the focused sorting tests and confirm they pass.
