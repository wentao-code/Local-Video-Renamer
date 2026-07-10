# Queen Crawl Stop Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stop button for queen-library crawling and make batch crawl resumable from the last unfinished queue position.

**Architecture:** Keep the existing background refresh thread and progress polling model, but add a cancel signal that the queen crawl loop checks between keywords. Persist crawl queue rows with a new `status` field so completed batches mark rows as `ok`, interrupted runs preserve remaining rows, and the next run resumes unfinished rows before rebuilding a new queue.

**Tech Stack:** Python, SQLite, PyQt5, unittest, existing backend HTTP service/client.

## Global Constraints

- Keep the queen crawl as a background task; do not block the UI thread.
- Preserve the existing fixed batch size of `10` and emit progress once per batch.
- Use TDD: add failing tests before production code changes.
- Use the existing `queen_crawl_queue_log` table instead of creating a second queue table.

---

### Task 1: Lock Resume Semantics With Tests

**Files:**
- Modify: `tests/test_queen_library_service.py`
- Modify: `tests/test_queen_refresh_background.py`
- Modify: `tests/test_queen_library_viewer.py`

**Interfaces:**
- Consumes: `QueenLibraryService.refresh_all(show_browser=True, batch_size=None, progress_callback=None, should_stop=None)`
- Produces: queue-status and cancel expectations for service, backend, and UI layers

- [ ] **Step 1: Write the failing service tests**

```python
def test_refresh_all_marks_completed_queue_rows_ok_and_resumes_unfinished_rows():
    ...

def test_refresh_all_stops_after_current_batch_and_preserves_unfinished_rows():
    ...
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `python -m pytest tests/test_queen_library_service.py -k "queue or stop or resume" -v`
Expected: FAIL because queue status persistence and stop-aware refresh do not exist yet.

- [ ] **Step 3: Write the failing backend and UI tests**

```python
def test_cancel_queen_library_refresh_marks_progress_stopped():
    ...

def test_queen_library_stop_button_requests_cancel_and_updates_status():
    ...
```

- [ ] **Step 4: Run backend and UI tests to verify they fail**

Run: `python -m pytest tests/test_queen_refresh_background.py tests/test_queen_library_viewer.py -k "stop or cancel" -v`
Expected: FAIL because stop endpoint, cancel flow, and stop button do not exist yet.

- [ ] **Step 5: Commit**

```bash
git add tests/test_queen_library_service.py tests/test_queen_refresh_background.py tests/test_queen_library_viewer.py
git commit -m "test: cover queen crawl stop and resume flow"
```

### Task 2: Implement Stop-Aware Queue Persistence In Queen Service

**Files:**
- Modify: `app/services/queen_library_service.py`

**Interfaces:**
- Consumes: existing queue-log writes and `QueenSearchScraper.search(...)`
- Produces: `refresh_all(..., should_stop=None)`, queue bootstrap/resume helpers, queue status updates

- [ ] **Step 1: Implement queue-status schema support and helpers**

```python
def _ensure_queue_status_column(...): ...
def _list_pending_crawl_queue_keywords(...): ...
def _replace_crawl_queue(...): ...
def _mark_crawl_queue_keywords_ok(...): ...
def _clear_crawl_queue_when_all_ok(...): ...
```

- [ ] **Step 2: Make `refresh_all` resume unfinished rows and stop after the current batch**

```python
def refresh_all(..., should_stop=None):
    ...
    if callable(should_stop) and should_stop():
        stopped = True
        break
```

- [ ] **Step 3: Return progress payloads that distinguish running, completed, and stopped states**

```python
return {
    ...,
    "stopped": stopped,
    "remaining_count": remaining_count,
}
```

- [ ] **Step 4: Run service tests to verify they pass**

Run: `python -m pytest tests/test_queen_library_service.py -k "queue or stop or resume" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/queen_library_service.py tests/test_queen_library_service.py
git commit -m "feat: persist queen crawl queue progress"
```

### Task 3: Add Backend Cancel Flow For Queen Crawl

**Files:**
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/client.py`
- Modify: `tests/test_queen_refresh_background.py`

**Interfaces:**
- Consumes: `QueenLibraryService.refresh_all(..., should_stop=...)`
- Produces: `BackendService.cancel_queen_library_refresh()`, `POST /queen-library/refresh/cancel`, `BackendClient.cancel_queen_library_refresh()`

- [ ] **Step 1: Add failing backend-cancel test coverage**

```python
def test_cancel_queen_library_refresh_marks_progress_stopped():
    ...
```

- [ ] **Step 2: Implement backend cancel event, stopped progress text, and stop-aware worker**

```python
self._queen_refresh_cancel_event = threading.Event()
...
def cancel_queen_library_refresh(self):
    self._queen_refresh_cancel_event.set()
```

- [ ] **Step 3: Expose the cancel endpoint through server and client**

```python
if method == "POST" and path == "/queen-library/refresh/cancel":
    return service.cancel_queen_library_refresh()
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `python -m pytest tests/test_queen_refresh_background.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backend/service.py app/backend/server.py app/backend/client.py tests/test_queen_refresh_background.py
git commit -m "feat: add queen crawl cancellation API"
```

### Task 4: Wire The Stop Button Into The Queen Library UI

**Files:**
- Modify: `app/gui/queen_library_viewer.py`
- Modify: `tests/test_queen_library_viewer.py`

**Interfaces:**
- Consumes: `BackendClient.refresh_queen_library(...)`, `BackendClient.cancel_queen_library_refresh()`, progress payload `stopped`
- Produces: `QueenLibraryWindow.stop_crawl()`, button enabled-state updates, stopped-status display

- [ ] **Step 1: Add failing UI test coverage for the stop button**

```python
def test_queen_library_stop_button_requests_cancel_and_updates_status():
    ...
```

- [ ] **Step 2: Add the stop button and connect it to a cancel request**

```python
self.btn_stop_crawl = QPushButton("停止抓取")
self.btn_stop_crawl.clicked.connect(self.stop_crawl)
```

- [ ] **Step 3: Update progress rendering so running/completed/stopped states toggle buttons correctly**

```python
def _set_crawl_running_state(self, is_running):
    ...
```

- [ ] **Step 4: Run UI tests to verify they pass**

Run: `python -m pytest tests/test_queen_library_viewer.py -k "queen_library" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/gui/queen_library_viewer.py tests/test_queen_library_viewer.py
git commit -m "feat: add queen crawl stop button"
```

### Task 5: Run Regression Verification

**Files:**
- Modify: none
- Test: `tests/test_queen_library_service.py`
- Test: `tests/test_queen_refresh_background.py`
- Test: `tests/test_queen_library_viewer.py`
- Test: `tests/test_queen_library_sorting.py`

**Interfaces:**
- Consumes: all updated queen-library code paths
- Produces: verification evidence for completion

- [ ] **Step 1: Run the focused queen regression suite**

Run: `python -m pytest tests/test_queen_library_service.py tests/test_queen_refresh_background.py tests/test_queen_library_viewer.py tests/test_queen_library_sorting.py -v`
Expected: PASS

- [ ] **Step 2: Review final diff for accidental unrelated edits**

Run: `git diff -- app/services/queen_library_service.py app/backend/service.py app/backend/server.py app/backend/client.py app/gui/queen_library_viewer.py tests/test_queen_library_service.py tests/test_queen_refresh_background.py tests/test_queen_library_viewer.py`
Expected: only queen-crawl stop/resume related changes

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-10-queen-crawl-stop-resume.md
git commit -m "docs: add queen crawl stop resume plan"
```
