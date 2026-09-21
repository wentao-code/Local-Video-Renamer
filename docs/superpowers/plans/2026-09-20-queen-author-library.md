# Queen Author Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent queen author library backed only by `queen_library.db`, with idempotent enrollment, raw-record matching, and separate list/detail views.

**Architecture:** Add `queen_authors` and `queen_author_sources` tables to the existing queen database. The source table records which queen detail caused enrollment, while author detail rows are queried dynamically from `queen_videos.raw_title`; the main actor/author library remains untouched. Expose the service through the existing backend snapshot/action pattern and add dedicated Qt windows within the queen-library package.

**Tech Stack:** Python, SQLite, existing backend client/server, PySide6/PyQt-compatible Qt viewer, pytest/unittest.

## Global Constraints

- Use only the independent `queen_library.db`.
- Match trimmed author keywords as ordinary substrings in `raw_title` only; English matching is case-insensitive and Chinese matching is unchanged.
- Repeated enrollment is idempotent and a queen is hidden from the queen list while any explicit source relationship or matching enrolled author exists.
- Removing an author removes its source relationships but never deletes queen/video records.
- Author detail is read-only except for `移出作者库`.

---

### Task 1: Service schema and behavior

**Files:**
- Modify: `code/app/queen_library/service.py`
- Test: `code/tests/test_queen_library_service.py`

**Interfaces:**
- Produce `add_queen_author(author_name, queen_name)`, `list_queen_authors()`, `get_queen_author_detail(author_name)`, and `remove_queen_author(author_name)` service methods.
- Extend `list_queens()` to omit queens hidden by enrolled-author source relationships or matching `raw_title` rows.

- [x] **Step 1: Write failing tests** for schema creation, idempotent add, source hiding, raw-title substring matching, multiple authors sharing a row, zero-match authors, and removal restoring the queen list.
- [x] **Step 2: Run `pytest code/tests/test_queen_library_service.py -k author -v` and confirm failures are due to missing author-library behavior.
- [x] **Step 3: Create the two tables during `_init_db`, normalize names, and implement the four service methods with parameterized SQLite queries.
- [x] **Step 4: Update `list_queens()` to filter source relationships and `raw_title` matches while returning the existing queen shape.
- [x] **Step 5: Run the focused service tests and the existing service test module.

### Task 2: Backend API

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/backend/client.py`
- Modify: `code/app/backend/server.py`
- Test: `code/tests/test_queen_library_viewer.py`

**Interfaces:**
- Produce backend methods for author list/detail, add, and remove, using `queen_library/author/...` snapshot keys and invalidating the queen-library snapshot prefix after mutations.
- Produce matching client methods and HTTP routes under the existing queen-library route namespace.

- [x] **Step 1: Add client/backend contract tests that assert route payloads and snapshot invalidation.
- [x] **Step 2: Run the focused tests and observe missing-method failures.
- [x] **Step 3: Implement service wrappers, client calls, and server dispatch using existing JSON body/query conventions.
- [x] **Step 4: Run the backend/viewer contract tests.

### Task 3: Queen and author viewers

**Files:**
- Modify: `code/app/queen_library/viewer.py`
- Modify: `code/app/gui/i18n_patch.py`
- Test: `code/tests/test_queen_library_viewer.py`

**Interfaces:**
- Add `作者库` on the queen list and `加入作者库` on queen detail.
- Add a dedicated author list window and read-only author detail window showing every matching queen-library video row.

- [x] **Step 1: Add viewer tests for button actions, list navigation, author detail rows, and absence of queen destructive controls in author detail.
- [x] **Step 2: Run the tests to confirm the new controls are absent.
- [x] **Step 3: Implement windows, callbacks, refresh behavior, and Chinese/English strings following existing Qt patterns.
- [x] **Step 4: Run the full queen-library test set.

### Task 4: Regression verification

**Files:**
- Modify only files required by Tasks 1-3.

- [x] **Step 1: Run all queen-library tests.
- [x] **Step 2: Run the complete configured pytest suite.
- [x] **Step 3: Inspect the diff and verify no main actor-library files or main database schemas changed.
