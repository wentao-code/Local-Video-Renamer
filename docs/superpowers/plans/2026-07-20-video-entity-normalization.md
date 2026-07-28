# Video Entity Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `video_entities` the unique video source of truth and move actor/number libraries to relation indexes so supplement enrichment is deduplicated by video code.

**Architecture:** Add normalized entity and relationship tables, backfill them idempotently from existing tables, then route repository queries and supplement writes through the normalized model. Keep legacy reads compatible during the rollout and only replace `processed_videos` with a compatibility view after all write paths are migrated.

**Tech Stack:** Python, SQLite, existing `VideoDatabase` repository, Pytest.

## Global Constraints

- Preserve existing user data and unrelated worktree changes.
- Standardize every video code with the existing `standardize_video_code()` helper.
- A supplement terminal status on the canonical video entity excludes the video from all supplement candidate libraries.
- Actor and code-prefix relations remain many-to-many and unique by `(video_code, owner)`.
- New fields and behavior must not alter non-supplement enrichment sources.

---

### Task 1: Add normalized schema and idempotent migration

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_video_entity_normalization.py`

- [ ] Write tests for table creation, one entity per standardized code, preservation of multiple actor relations, preservation of multiple prefix relations, and running database initialization twice.
- [ ] Run `python -m pytest tests/test_video_entity_normalization.py -q` and verify the new tests fail because normalized tables do not exist.
- [ ] Add `video_entities`, `video_actor_relations`, and `video_code_prefix_relations` with primary keys, foreign keys where safe for the current schema, and indexes for owner/code lookups.
- [ ] Add an idempotent migration that reads `processed_videos`, `actor_movies`, and `code_prefix_movies`, standardizes codes, merges non-empty entity fields, and inserts unique relations without deleting legacy data.
- [ ] Run the migration tests and verify they pass.

### Task 2: Add canonical entity and relationship repository APIs

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_video_entity_normalization.py`

- [ ] Add repository methods to get entities by code, list entities by actor or prefix, upsert entity fields without empty-value overwrite, and replace actor/prefix relationships transactionally.
- [ ] Add a canonical supplement status update that updates `video_entities` once per code.
- [ ] Add tests proving updates through either actor or prefix context modify one entity and preserve all relationships.
- [ ] Run the focused normalization and database tests.

### Task 3: Switch supplement candidate selection and writes

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/services/enrichment/supplement_enrichment.py`
- Test: `code/tests/test_supplement_tasks.py`

- [ ] Change video, actor, and code-prefix supplement candidate SQL to select canonical entities joined through relation tables.
- [ ] Filter candidates by the canonical video supplement status so a video completed through one library is not selected again by another.
- [ ] Change all three supplement bulk writers to update `video_entities` once per video and write the current batch status in the same transaction.
- [ ] Preserve actor/prefix result grouping for progress display while making persistence video-based.
- [ ] Add tests for cross-library de-duplication and one canonical update for a multi-actor video.

### Task 4: Switch library queries and statistics

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/services/library/data_center_service.py`
- Test: `code/tests/test_data_center_summary.py`
- Test: `code/tests/test_library_status_sync.py`

- [ ] Replace actor and code-prefix full-row scans with joins from relations to canonical entities.
- [ ] Keep actor and prefix aggregate counts based on distinct video codes.
- [ ] Verify shared videos count once in global video summaries and once per relevant actor/prefix relationship in library-specific views.
- [ ] Run data center, library status, and normalization tests.

### Task 5: Add compatibility layer and consistency checks

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/backend/service.py`
- Test: `code/tests/test_video_entity_normalization.py`
- Test: `code/tests/test_enrichment_pending_queues.py`

- [ ] Keep legacy APIs returning the existing shapes by joining normalized tables.
- [ ] Add consistency checks comparing legacy and normalized row counts, distinct codes, and relation sets before any view switch.
- [ ] Convert `processed_videos` reads to the compatibility view only after all writes use `video_entities`; retain a guarded migration path for existing installations.
- [ ] Verify old pending supplement rows continue to resolve through canonical entities and links.

### Task 6: Full verification

**Files:**
- No production files.

- [ ] Run `python -m pytest tests/test_video_entity_normalization.py tests/test_supplement_tasks.py tests/test_enrichment_pending_queues.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Inspect migration output on a copy of the current database and confirm duplicate codes collapse only in `video_entities`, while all actor/prefix relationships remain.
