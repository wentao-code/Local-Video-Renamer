# Enrichment Running Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one transactional running-task table that physically owns the currently executing enrichment batch and restores infrastructure failures to their original source queue.

**Architecture:** Source-specific tables remain durable pending queues. Claim, acknowledge, and restore operations move rows between a fixed source table and `enrichment_running_items` inside `BEGIN IMMEDIATE` transactions; plan counters retain progress after successful rows are deleted.

**Tech Stack:** Python 3, SQLite, unittest/pytest.

## Global Constraints

- Only one enrichment plan may occupy `enrichment_running_items` at a time.
- Business terminal results are completed and never returned to the source queue.
- Network, connection, process, and execution failures return rows to their exact `origin_table`.
- Dynamic table names are accepted only from the existing fixed table whitelist.
- Preserve compatibility with legacy task-kind queue tables.

---

### Task 1: Specify physical claim behavior

**Files:**
- Modify: `code/tests/test_enrichment_pending_queues.py`
- Modify: `code/app/data/database_handler.py`

**Interfaces:**
- Consumes: `claim_enrichment_batch_items(plan_id, task_kind, batch_limit)`.
- Produces: rows physically moved to `enrichment_running_items` with `origin_table`.

- [ ] Add a test asserting source-row deletion and running-row insertion after claim.
- [ ] Run the test and verify it fails because the running table does not exist.
- [ ] Create the table, plan counters, whitelist validation, and transactional move.
- [ ] Run the test and verify it passes.

### Task 2: Specify completion and failure return behavior

**Files:**
- Modify: `code/tests/test_enrichment_pending_queues.py`
- Modify: `code/app/data/database_handler.py`

**Interfaces:**
- Consumes: `mark_enrichment_batch_item(...)` and `release_enrichment_batch_items(...)`.
- Produces: transactional delete-on-completion and restore-on-failure operations.

- [ ] Add tests proving completion deletes without return and increments progress.
- [ ] Add tests proving `failed` and batch release restore the exact source row.
- [ ] Run both tests and verify the old status-update implementation fails.
- [ ] Implement transactional acknowledge/restore with preserved attempts and errors.
- [ ] Run both tests and verify they pass.

### Task 3: Specify single-task and restart recovery

**Files:**
- Modify: `code/tests/test_enrichment_pending_queues.py`
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/backend/service.py`

**Interfaces:**
- Consumes: global execution-table occupancy and startup recovery.
- Produces: rejection of a competing plan and restoration of interrupted rows.

- [ ] Add a test that a second plan cannot claim while another plan occupies the execution table.
- [ ] Add a restart recovery test for rows from different source tables.
- [ ] Run tests and verify failures under the current per-source `running` statuses.
- [ ] Implement occupancy enforcement and global execution-table recovery.
- [ ] Run tests and verify they pass.

### Task 4: Regression verification

**Files:**
- Modify only files required by failing compatibility tests.

**Interfaces:**
- Consumes: all existing enrichment plan callers.
- Produces: unchanged service/API behavior over the new physical queue lifecycle.

- [ ] Run `pytest -q tests/test_enrichment_pending_queues.py tests/test_enrichment_plan_candidates.py tests/test_supplement_tasks.py` from `code`.
- [ ] Fix only regressions caused by the execution-table lifecycle and rerun the focused suite.
- [ ] Run `pytest -q` from `code`.
- [ ] Run `git diff --check` and inspect the final diff.
