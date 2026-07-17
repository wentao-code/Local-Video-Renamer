# Data Center SQL Aggregation Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with tests after each task.

**Goal:** Move high-volume data-center counts and distribution calculations from Python loops into parameterized SQLite aggregate queries while preserving existing filter semantics.

**Architecture:** Add focused aggregate methods to `VideoDatabase` for actor and code-prefix statistics. `DataCenterService` will call those methods for count/range metrics and retain Python processing only for source fallback, complex multi-source merging, and irregular text parsing. Existing `RuleSet` SQL predicates remain the first-stage filter; residual rules remain validated in Python.

**Tech Stack:** Python, SQLite, parameterized SQL, pytest/unittest.

## Global Constraints

- Preserve current visible/filtered library semantics.
- Use parameter binding for all values; whitelist metric-to-column mappings.
- Do not introduce destructive migrations or alter existing stored data.
- Keep complex multi-source merge behavior unchanged in this pass.

---

### Task 1: Add SQL aggregate database interfaces

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_data_center_summary.py`

- [x] Add failing tests for actor grouped video counts and code-prefix grouped counts, including duplicate codes and filter rules.
- [x] Run the focused tests and confirm the new interfaces are missing.
- [x] Implement parameterized `GROUP BY`/`COUNT(DISTINCT code)` queries with the existing `RuleSet` predicate.
- [x] Add SQL-side numeric metric extraction for age, height, bust, waist, and hip using whitelisted expressions.
- [x] Run the focused tests and confirm they pass.

### Task 2: Route count and range analyses through SQL

**Files:**
- Modify: `code/app/services/library/data_center_service.py`
- Test: `code/tests/test_data_center_summary.py`

- [x] Add failing service tests proving actor video-count and code-prefix video-count analyses use aggregate results.
- [x] Replace Python per-actor/per-prefix movie counting for supported metrics with database aggregate calls.
- [x] Keep unknown-value handling and existing ranking/bucket labels unchanged.
- [x] Run the focused tests and compare aggregate results with seeded expected values.

### Task 3: Move simple actor metric distributions to SQL

**Files:**
- Modify: `code/app/data/database_handler.py`, `code/app/services/library/data_center_service.py`
- Test: `code/tests/test_data_center_summary.py`

- [x] Existing tests cover age/height/bust/waist/hip/cup distribution and ranking.
- [x] Implement SQL-side extraction for fields that have a stable numeric expression; retain Python parsing for cup and malformed text.
- [x] Preserve the existing `无数据` bucket and top-50 ranking contract.
- [x] Run data-center tests and the full relevant regression suite.

### Task 4: Verify performance and compatibility

**Files:**
- Test: `code/tests/test_data_center_summary.py`, existing data-center and database tests

- [x] Run all data-center, filter, snapshot, and database tests.
- [x] Run `EXPLAIN QUERY PLAN` for the new aggregate queries; actor counts use `idx_actor_movies_category_code`, and prefix aggregation uses the code index plus temporary grouping B-trees.
- [x] Run compile and diff checks.
- [x] Review the final diff for unchanged multi-source merge behavior.
