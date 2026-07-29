# Video Entity Repository Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `video_entities` the sole canonical write model, make exclusions a single runtime decision source, and move unified-video SQL into `VideoEntityRepositoryMixin`.

**Architecture:** Blacklists and filter settings remain editable inputs. `video_entity_exclusions` is the recomputed runtime projection used by every visibility and candidate decision. `active_video_entities` remains a materialized read model but only receives one-way data from canonical source tables. `VideoDatabase` keeps public facades and orchestration while `VideoEntityRepositoryMixin` owns unified-video persistence SQL.

**Tech Stack:** Python, SQLite, pytest, ruff, pyflakes.

## Global Constraints

- Do not recreate or read `processed_videos`, `actor_movies`, or `code_prefix_movies` in runtime paths.
- Retain `hidden_actors`, `hidden_code_prefixes`, and saved rule settings as editable configuration inputs.
- Runtime visibility and candidate decisions use `video_entity_exclusions`, not blacklist-table joins.
- Preserve all existing `VideoDatabase` public method signatures.
- Add a failing behavior test before each production migration batch.
- Do not write directly to `active_video_entities` after the one-way projection task.

---

### Task 1: Centralize Runtime Exclusion Decisions

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/data/repositories/actor_repo.py`
- Modify: `code/app/data/repositories/code_prefix_repo.py`
- Modify: `code/app/data/repositories/candidate_library_repo.py`
- Test: `code/tests/test_video_entity_exclusions.py`

**Interfaces:**
- Consumes: `rebuild_video_entity_exclusions()` and `video_entity_exclusions`.
- Produces: public list/candidate methods whose exclusion decisions use scoped projection predicates only.

- [ ] **Step 1: Write failing visibility regression tests**

```python
def test_runtime_library_and_candidate_reads_do_not_query_blacklist_tables():
    # Materialize exclusions, then drop access to blacklist tables with a SQLite authorizer.
    # Library/candidate methods must still return results based on video_entity_exclusions.
    ...
```

- [ ] **Step 2: Run the new test and verify it fails because a runtime query still joins a blacklist table**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_exclusions.py -q`

- [ ] **Step 3: Replace runtime blacklist joins with scoped exclusion predicates**

Keep blacklist access inside configuration editing and `rebuild_video_entity_exclusions()` only. Use `_append_entity_exclusion_where()` or its extracted shared predicate component for runtime SQL.

- [ ] **Step 4: Run exclusion and library tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_exclusions.py tests/test_actor_profile_display.py tests/test_code_prefix_detail_library.py -q`

### Task 2: Move Relation Replacement Writes Into VideoEntityRepository

**Files:**
- Modify: `code/app/data/repositories/video_entity_repo.py`
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_video_entity_normalization.py`
- Test: `code/tests/test_video_entity_exclusions.py`

**Interfaces:**
- Consumes: canonical entity/relation tables and current `replace_actor_movies(actor_name, movies)` / `replace_code_prefix_movies(prefix, movies)` public signatures.
- Produces: repository-owned replacement methods and one internal relation upsert primitive.

- [ ] **Step 1: Write failing ownership and behavior tests**

```python
def test_relation_replacement_methods_are_provided_by_repository(self):
    self.assertIs(VideoDatabase.replace_actor_movies, VideoEntityRepositoryMixin.replace_actor_movies)
    self.assertIs(VideoDatabase.replace_code_prefix_movies, VideoEntityRepositoryMixin.replace_code_prefix_movies)
```

Add a fixture asserting replacement preserves canonical entity fields, replaces only the requested owner relation, updates relation metadata, and refreshes exclusions.

- [ ] **Step 2: Run the ownership test and verify it fails because methods remain on VideoDatabase**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_normalization.py -q`

- [ ] **Step 3: Extract one repository relation-write primitive and move both replacement methods**

The primitive accepts a code, entity payload, and optional actor/prefix relation payloads. Preserve existing merge/blacklist and JAVTXT-state normalization before calling it. Delete `_upsert_actor_movie_canonical` and `_upsert_code_prefix_movie_canonical` after callers use the primitive.

- [ ] **Step 4: Run relation replacement regression tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_normalization.py tests/test_video_entity_exclusions.py tests/test_library_status_sync.py -q`

### Task 3: Make Active Entities One-Way

**Files:**
- Modify: `code/app/data/repositories/video_entity_repo.py`
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_video_entity_exclusions.py`

**Interfaces:**
- Consumes: `video_entities`, `local_video_records`, and `video_entity_exclusions`.
- Produces: `rebuild_active_video_entities()` and source-table write helpers; no active-table write-back trigger or direct writes.

- [ ] **Step 1: Write failing one-way projection tests**

```python
def test_active_entity_updates_do_not_write_back_to_canonical_tables():
    # A direct active-table update cannot alter video_entities or local_video_records.
    ...
```

Add a projection rebuild assertion after archive/local/exclusion changes.

- [ ] **Step 2: Run the test and verify it fails because the active-table update trigger exists**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_exclusions.py -q`

- [ ] **Step 3: Remove write-back trigger and migrate direct active writes to source-table writes**

Place rebuild logic in `VideoEntityRepositoryMixin`; update every active-table mutation in the handler to write archive/local sources and then rebuild or refresh the projection.

- [ ] **Step 4: Run projection, import, and enrichment status tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_video_entity_exclusions.py tests/test_local_video_media_import.py tests/test_enrichment_status_migration.py -q`

### Task 4: Extract Candidate, Result, And Statistics SQL

**Files:**
- Modify: `code/app/data/repositories/video_entity_repo.py`
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_enrichment_plan_candidates.py`
- Test: `code/tests/test_enrichment_selection_jobs.py`
- Test: `code/tests/test_enrichment_pending_queues.py`

**Interfaces:**
- Consumes: repository-owned canonical query helpers and public `VideoDatabase` candidate/result methods.
- Produces: repository methods for video candidates, supplement candidates, video enrichment writes, and actor/code-prefix statistics.

- [ ] **Step 1: Add one failing ownership or behavioral test per SQL batch**

Test JAVTXT/AVFAN candidate selection respects materialized exclusions, a completed enrichment writes canonical fields and status, and relation statistics retain ordering and counts.

- [ ] **Step 2: Run each test and verify it fails before extraction**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_enrichment_plan_candidates.py tests/test_enrichment_selection_jobs.py tests/test_enrichment_pending_queues.py -q`

- [ ] **Step 3: Move SQL in focused groups**

Move `list_sql_javtxt_video_candidates`, `list_video_supplement_candidates`, video enrichment result methods, then actor/code-prefix dashboard/statistic reads. Leave task-plan orchestration in `VideoDatabase`.

- [ ] **Step 4: Run targeted candidate and enrichment tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_enrichment_plan_candidates.py tests/test_enrichment_selection_jobs.py tests/test_enrichment_pending_queues.py tests/test_enrichment_task_state.py -q`

### Task 5: Full Verification And Cleanup

**Files:**
- Modify: tests only when they reference a removed write-back behavior.

- [ ] **Step 1: Audit forbidden runtime dependencies**

Run: `rg -n "JOIN hidden_|FROM hidden_|UPDATE active_video_entities|INSERT INTO active_video_entities" code/app`

Expected: configuration/rebuild paths may read hidden tables; no runtime library/candidate path reads them, and no application write path targets `active_video_entities`.

- [ ] **Step 2: Run full verification**

Run:
`D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest -q`

`D:\Anaconda3\python.exe -m ruff check app tests --select F401,F811,F821,F841`

`D:\Anaconda3\python.exe -m pyflakes app tests`

`git diff --check`

- [ ] **Step 3: Commit each completed phase separately**

Use commits named `refactor: centralize runtime video exclusions`, `refactor: move relation replacement writes`, `refactor: make active video projection one way`, and `refactor: move unified entity enrichment sql`.
