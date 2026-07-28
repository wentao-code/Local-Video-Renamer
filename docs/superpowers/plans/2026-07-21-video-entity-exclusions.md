# Video Entity Exclusions Implementation Plan

> **For agentic workers:** Implement task-by-task with a test checkpoint after each task.

**Goal:** Materialize video-level exclusion decisions while keeping `video_entities` as the complete canonical entity set.

**Architecture:** Keep blacklist tables and JSON filter rules as rule sources. Add `video_entity_exclusions` as a recomputable projection keyed by video code, and centralize exclusion checks for video visibility, JAVTXT eligibility, and supplement candidates. Local visibility remains controlled by `local_video_records.storage_location <> ''`.

**Tech Stack:** Python, SQLite, pytest.

## Global Constraints

- Do not recreate or query `processed_videos`, `actor_movies`, or `code_prefix_movies` in normal startup or normal reads.
- Preserve canonical writes to `video_entities`, `local_video_records`, relation tables, and relation metadata tables.
- Store multiple exclusion reasons for one video without overwriting earlier reasons.
- Rule changes must be reversible by recomputing exclusions; never delete `video_entities` for policy reasons.

### Task 1: Canonical Exclusion Schema And Rebuild

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_video_entity_exclusions.py`

- [ ] Add `video_entity_exclusions` with `(code, exclusion_type, scope)` as the primary key and indexes on `(scope, code)`.
- [ ] Add `rebuild_video_entity_exclusions()` that derives rows from canonical entities, local records, blacklist tables, release-date eligibility, and filter rules.
- [ ] Add `list_video_entity_exclusions(code=None, scope=None)` for diagnostics and tests.
- [ ] Rebuild rows transactionally and make repeated rebuilds idempotent.

### Task 2: Centralized Query Gates

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/core/supplement_task_state.py`
- Test: `code/tests/test_video_entity_exclusions.py`

- [ ] Apply the exclusion predicate to video library reads/counts after the local storage predicate.
- [ ] Apply the `javtxt` scope to JAVTXT candidates and the `supplement` scope to supplement candidates.
- [ ] Keep pure eligibility helpers for compatibility, but use the materialized exclusion result in database candidate queries.

### Task 3: Rebuild Triggers At Write And Rule Changes

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/gui/video_filter_dialog.py` only if rule-save invalidation needs a backend call.
- Test: `code/tests/test_video_entity_exclusions.py`

- [ ] Recompute affected codes after entity/local-record writes.
- [ ] Rebuild all exclusions after filter or blacklist changes.
- [ ] Ensure an entity becomes visible/eligible again after the matching rule is removed.

### Task 4: Verification And Legacy Read Audit

**Files:**
- Modify: only tests that still directly target removed legacy objects.

- [ ] Run targeted exclusion, video list, supplement, and category tests.
- [ ] Run `rg` audit for unguarded old table reads in active paths.
- [ ] Run the full suite and report any remaining stale migration-fixture failures separately.
