# Code Prefix Read-Only View Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with test-first checkpoints.

**Goal:** Make `code_prefix_movies` a read-only compatibility view while routing番号库 writes to canonical video and prefix relation tables.

**Architecture:** Keep existing read queries against `code_prefix_movies`. Remove its `INSTEAD OF` write triggers and update database APIs to write `video_entities`, `video_code_prefix_relations`, and `video_prefix_relation_meta`. Preserve a narrowly-scoped fallback for databases where `code_prefix_movies` is still a legacy table.

**Tech Stack:** Python, SQLite, unittest/pytest.

## Global Constraints

- Do not change unrelated UI or database schemas.
- Do not use `rowid` for compatibility-view writes or lookups.
- In converted databases, no production write may target `code_prefix_movies`.
- Preserve existing query compatibility and old-table migration behavior.

---

### Task 1: Lock the read-only contract

**Files:**
- Modify: `code/tests/test_video_entity_normalization.py`

- [ ] Add a test that converts legacy tables to compatibility views and asserts direct `INSERT`, `UPDATE`, and `DELETE` on `code_prefix_movies` raise `sqlite3.OperationalError`.
- [ ] Add assertions that `replace_code_prefix_movies` still creates the canonical entity, prefix relation, and relation metadata.
- [ ] Run the focused test and confirm it fails because the current view triggers still allow writes.

### Task 2: Migrate番号库 writes

**Files:**
- Modify: `code/app/data/database_handler.py`

- [ ] Remove `trg_code_prefix_movies_view_insert`, `trg_code_prefix_movies_view_update`, and `trg_code_prefix_movies_view_delete`; drop existing trigger objects during conversion.
- [ ] Add a cursor helper for canonical prefix upserts and legacy-table detection.
- [ ] Migrate replacement, supplement status, bulk update, reset, rename, delete/blacklist, code normalization, and category synchronization writes.
- [ ] Keep old-table fallback only when SQLite reports `code_prefix_movies` as a table; never use it when it is a view.

### Task 3: Verify all paths

**Files:**
- Modify: `code/tests/test_video_entity_normalization.py` only if regression coverage needs extension.

- [ ] Run番号库 and compatibility-focused tests.
- [ ] Scan production code for direct writes or `INSTEAD OF` triggers on `code_prefix_movies`.
- [ ] Run the complete test suite and compile the modified Python module.
