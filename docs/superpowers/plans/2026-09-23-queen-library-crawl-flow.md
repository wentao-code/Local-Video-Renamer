# Queen Library Crawl Flow Implementation Plan

**Goal:** Make queen-library crawling switch to task mode correctly, prevent duplicate starts, and show live backend progress instead of remaining at the startup message.

**Architecture:** The queen-library dialog delegates task-mode confirmation to its main-window parent. The dialog keeps its existing queued worker for the crawl request, while a separate non-queued progress poll updates the UI during that worker's backend polling. Start requests are rejected when either the dialog or backend already has a crawl active.

**Tech Stack:** PyQt5, the existing GUI task queue, BackendClient polling, unittest/pytest.

## Global Constraints

- Do not change the queen-library database schema or crawl data flow.
- Preserve the existing task category `补全任务` and task kind `queen_crawl`.
- Do not modify unrelated Feishu plugin changes in the working tree.

### Task 1: Add regression coverage for queen-library task-mode delegation

**Files:**
- Modify: `code/tests/test_queen_library_viewer.py`
- Test: `code/tests/test_queen_library_viewer.py`

- [ ] Add a parent stub exposing `_ensure_task_mode_for_task`, construct `QueenLibraryWindow` with that parent, invoke `start_crawl`, and assert the parent hook receives `TASK_CATEGORY_ENRICHMENT` before the crawl is queued.
- [ ] Add a test where the parent hook returns `False`; assert `start_crawl` does not call `refresh_queen_library`, re-enables the start button, and leaves the stop button disabled.
- [ ] Run `python -m pytest code/tests/test_queen_library_viewer.py -q`; the new tests must fail before the production change because the dialog does not expose the parent hook.

### Task 2: Add regression coverage for duplicate prevention and live progress polling

**Files:**
- Modify: `code/tests/test_queen_library_viewer.py`

- [ ] Add a test where `get_queen_refresh_progress()` reports `is_running=True` before `start_crawl`; assert no new crawl task is queued and the dialog displays the existing progress.
- [ ] Add a test where the dialog has a pending/running async task; assert a second `start_crawl` does not queue another task.
- [ ] Change the progress polling test setup so `is_async_task_running()` returns true, call `poll_crawl_progress`, and assert the backend progress request still runs with `show_in_task_queue=False`.
- [ ] Run the focused tests and confirm these cases fail against the current implementation.

### Task 3: Implement task-mode delegation and safe start behavior

**Files:**
- Modify: `code/app/queen_library/viewer.py`

- [ ] Add `_ensure_task_mode_for_task(self, task_category)` that calls the parent window's same-named method when available and otherwise returns `True`.
- [ ] Update `start_crawl` to return early for an existing dialog task or backend crawl, apply the current backend progress when one exists, and only set the startup UI state after task-mode validation and duplicate checks pass.
- [ ] Handle a `False` return from `start_async_task` by restoring the idle controls and status instead of leaving “正在启动批量抓取...”.
- [ ] Update `poll_crawl_progress` so it always performs the non-queued backend progress request; the existing async task guard must not suppress live progress updates.

### Task 4: Verify the implementation

**Files:**
- No additional production files.

- [ ] Run `python -m pytest code/tests/test_queen_library_viewer.py code/tests/test_task_queue.py -q`.
- [ ] Run `python -m pytest code/tests/test_queen_search_scraper.py code/tests/test_queen_refresh_background.py code/tests/test_queen_library_service.py code/tests/test_queen_author_library_backend.py -q`.
- [ ] Run `python -m compileall -q code` and `git diff --check`.
- [ ] Run `python -m pytest -q`; report any unrelated existing failures separately.
