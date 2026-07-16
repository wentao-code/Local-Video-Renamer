# Dual-Format Page Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every named data page independently in JSON and MessagePack, prefer MessagePack reads, and split the three Tianjige tiers so a manual refresh only rebuilds the active tier.

**Architecture:** Add a focused `SnapshotStore` that owns dual-format paths and atomic I/O. Existing services keep their payload validation and cache logic but delegate persistence to the store. Page APIs use stable snapshot keys, and Tianjige adds a tier parameter from GUI through HTTP to backend.

**Tech Stack:** Python 3, msgpack, pathlib, JSON, PyQt5, unittest/pytest, SQLite.

## Global Constraints

- New files live under `user_data/snapshots/messagepack` and `user_data/snapshots/json` only.
- Every successful refresh writes both formats; reads prefer MessagePack and fall back to JSON.
- Missing `msgpack` must not prevent backend startup; JSON remains operational.
- Writes use temporary files and atomic replacement.
- Existing legacy JSON remains readable and migrates on successful use.
- Manual refresh rebuilds only the requested page, entity, board, mode, or Tianjige tier.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: Unified Snapshot Store

**Files:**
- Create: `code/app/core/snapshot_store.py`
- Modify: `code/app/core/project_paths.py`
- Create: `code/tests/test_snapshot_store.py`
- Create: `code/requirements.txt`

**Interfaces:**
- Produces: `SnapshotStore(root_dir, messagepack_available=None)`.
- Produces: `read(key, legacy_paths=()) -> dict | list | None`.
- Produces: `write(key, payload) -> None`, `delete(key) -> None`, `delete_prefix(prefix) -> None`.
- Produces: `messagepack_path(key) -> Path`, `json_path(key) -> Path`.

- [ ] **Step 1: Write failing store tests**

Cover dual-write paths, MessagePack-first reads, corrupt MessagePack fallback and repair, legacy JSON migration, safe key validation, deletion, and JSON-only behavior when msgpack is unavailable.

- [ ] **Step 2: Run the store tests and verify RED**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest code/tests/test_snapshot_store.py -q`

Expected: collection/import failure because `SnapshotStore` does not exist.

- [ ] **Step 3: Implement the minimal store**

Use `Path.with_suffix('.tmp')`, `replace`, UTF-8 JSON, `msgpack.packb(..., use_bin_type=True)`, and `msgpack.unpackb(..., raw=False, strict_map_key=False)`. Catch format-specific decode/I/O failures independently. Validate keys as slash-separated relative components with no `..`.

- [ ] **Step 4: Add dependency declaration and run GREEN**

Add `msgpack>=1.0,<2` to `code/requirements.txt`. Run the test command until all store tests pass.

### Task 2: Migrate Existing Persistent Snapshots

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/services/library/data_center_service.py`
- Modify: `code/tests/test_detail_snapshot_support.py`
- Modify: `code/tests/test_actor_viewer_snapshot.py`
- Modify: `code/tests/test_code_prefix_snapshot_support.py`
- Modify: `code/tests/test_data_center_summary.py`
- Modify: `code/tests/test_video_category_viewer.py`

**Interfaces:**
- Consumes: `SnapshotStore` from Task 1.
- Produces stable keys: `actor_library/index`, `actor_detail/<encoded-name>`, `code_prefix_library/index`, `code_prefix_detail/<prefix>`, `masterpiece/detail/<code>`, and `data_center/<view-key>`.

- [ ] **Step 1: Add failing compatibility tests**

Assert that existing JSON fixtures load, then produce both new-format files, and that corrupt MessagePack falls back without breaking current cache-hit behavior.

- [ ] **Step 2: Run focused tests and verify RED**

Run the six modified test modules with `-q`; expect missing new paths or store integration assertions.

- [ ] **Step 3: Replace direct JSON I/O with SnapshotStore calls**

Retain all existing payload versions and normalization methods. Pass old root/detail JSON paths as legacy sources. Clear or prune both formats through the store.

- [ ] **Step 4: Run focused tests and verify GREEN**

Confirm existing snapshot semantics and new dual-format assertions pass.

### Task 3: Split Tianjige into Three Snapshots

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/backend/client.py`
- Modify: `code/app/backend/server.py`
- Modify: `code/app/gui/video_category_viewer.py`
- Modify: `code/tests/test_video_category_viewer.py`
- Modify: `code/tests/test_backend_client_server.py` if present; otherwise add route assertions to `code/tests/test_video_category_viewer.py` using the existing client/server test helpers.

**Interfaces:**
- Produces: `list_videos_requiring_manual_category_snapshot(tier, force_refresh=False)`.
- Snapshot keys: `video_category/tier_1`, `video_category/tier_2`, `video_category/tier_3`.

- [ ] **Step 1: Add failing tier-isolation tests**

Assert switching tiers requests only the selected tier, a force refresh only changes that tier's timestamp/file, and each payload contains only rows whose `manual_tier` matches.

- [ ] **Step 2: Run tests and verify RED**

Expected: current API has no tier argument and writes one combined snapshot.

- [ ] **Step 3: Thread the tier through GUI, client, route, and service**

Validate against the three constants. Keep one in-memory snapshot per tier. Filter source rows before payload persistence. Make filter or category-wide mutations invalidate all affected tier keys, while a manual refresh touches one.

- [ ] **Step 4: Run tests and verify GREEN**

Run Tianjige GUI and backend snapshot tests.

### Task 4: Persist Previously Memory-Only and Direct-Query Pages

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/gui/db_viewer.py`
- Modify: `code/app/queen_library/viewer.py` only if request parameters are required.
- Create: `code/tests/test_page_snapshot_persistence.py`
- Modify: `code/tests/test_candidate_library_service.py`
- Modify: `code/tests/test_canglangge_candidate_service.py`
- Modify: `code/tests/test_ladder_board_service.py`
- Modify: `code/tests/test_masterpiece_library.py`
- Modify: `code/tests/test_global_medal_library.py`
- Modify: `code/tests/test_queen_library_service.py`

**Interfaces:**
- Snapshot keys: `video_library/<query-fingerprint>`, `candidate_library/actors`, `candidate_library/code_prefixes`, `canglangge/index`, `ladder_board/<board-key>`, `masterpiece/index`, `medal_catalog/index`, `queen_library/index`, `queen_library/keywords`, `queen_library/detail/<encoded-name>`, `path_library/index`.

- [ ] **Step 1: Add failing cross-instance persistence tests**

For each page family, build once, create a fresh service with a data-source method that raises, and prove the persisted page snapshot is reused. Add force-refresh assertions that only the requested key changes.

- [ ] **Step 2: Run tests and verify RED**

Expected: memory-only/direct-query pages call the source again.

- [ ] **Step 3: Implement per-page store wrappers**

Use stable SHA-256 fingerprints for query/sort/pagination keys. Keep public response schemas unchanged. Mutations delete only related keys/prefixes. Queen data remains sourced from `queen_library.db`; page snapshots only cache presentation payloads.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run page persistence plus existing GUI/service tests for all affected families.

### Task 5: Startup, Migration, and Full Verification

**Files:**
- Modify: `code/app/gui/main_window.py` if startup refresh needs three Tianjige tasks.
- Modify: startup tests.
- Modify: docs only if runtime dependency instructions need clarification.

**Interfaces:**
- Startup health remains independent of snapshot migration.
- Startup refresh may enqueue one task per Tianjige tier, each with its own history key.

- [ ] **Step 1: Add failing startup boundary tests**

Assert startup refresh specifications contain independent tier tasks and no migration work runs on the health-critical path.

- [ ] **Step 2: Implement startup wiring**

Keep migration lazy. Install/import failure of msgpack must leave JSON refresh tasks working.

- [ ] **Step 3: Run syntax and focused tests**

Run `python -m compileall code/app` and all affected test modules.

- [ ] **Step 4: Run the complete suite**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest code/tests -q`

Expected: all tests pass with no new warnings or tracebacks.

- [ ] **Step 5: Inspect final filesystem and diff**

Verify generated snapshot paths are separated, `git diff --check` reports no whitespace errors, and unrelated dirty files remain untouched.
