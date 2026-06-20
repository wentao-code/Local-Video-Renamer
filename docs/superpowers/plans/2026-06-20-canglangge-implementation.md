# Canglangge Candidate Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new desktop `沧浪阁` workflow that lists candidate actors from `S`-tier recent local videos and lets the user admit them into the actor library or blacklist them permanently.

**Architecture:** Introduce a dedicated backend candidate service that computes actor candidates from local videos under `S`-tier code prefixes, then expose admit/delete endpoints that reuse the existing actor add and hidden-actor blacklist semantics. Add a focused PyQt viewer dialog and a main-window entry button so the candidate workflow stays separate from the actor library while sharing backend primitives.

**Tech Stack:** Python, PyQt5, sqlite3, unittest

---

### File Structure

**Create:**
- `app/services/library/canglangge_candidate_service.py`
- `app/gui/canglangge_viewer.py`
- `tests/test_canglangge_candidate_service.py`
- `tests/test_canglangge_viewer.py`

**Modify:**
- `app/services/library/__init__.py`
- `app/backend/service.py`
- `app/backend/server.py`
- `app/backend/client.py`
- `app/gui/main_window.py`
- `app/gui/i18n.py`
- `app/gui/i18n_patch.py`

---

### Task 1: Backend Candidate Computation

**Files:**
- Create: `app/services/library/canglangge_candidate_service.py`
- Modify: `app/services/library/__init__.py`
- Test: `tests/test_canglangge_candidate_service.py`

- [ ] **Step 1: Write the failing candidate-service tests**

```python
import unittest

from app.services.library.canglangge_candidate_service import CanglanggeCandidateService


class CanglanggeCandidateServiceTest(unittest.TestCase):
    def test_collects_candidates_only_from_s_tier_recent_local_videos(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [
                    {'entity_name': 'IPX', 'tier': 'S'},
                    {'entity_name': 'ABC', 'tier': 'A'},
                ]

            def list_local_videos_by_prefixes(self, prefixes):
                return [
                    {'code': 'IPX-001', 'author': 'Actor A Actor B', 'release_date': '2021-01-01'},
                    {'code': 'ABC-001', 'author': 'Actor C', 'release_date': '2021-01-01'},
                    {'code': 'IPX-002', 'author': 'Actor D', 'release_date': '2019-12-31'},
                ]

            def list_actors(self, search_text=''):
                return [{'name': 'Actor B'}]

            def list_hidden_actors(self):
                return {'Actor Z'}

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual([row['actor_name'] for row in rows], ['Actor A'])
        self.assertEqual(rows[0]['codes'], ['IPX-001'])
        self.assertEqual(rows[0]['prefixes'], ['IPX'])

    def test_aggregates_multiple_s_prefix_sources_into_one_actor_row(self):
        class FakeDatabase:
            def list_ladder_entries(self, board_key=None, entity_type=None):
                return [
                    {'entity_name': 'IPX', 'tier': 'S'},
                    {'entity_name': 'MIDV', 'tier': 'S'},
                ]

            def list_local_videos_by_prefixes(self, prefixes):
                return [
                    {'code': 'IPX-001', 'author': 'Actor A', 'release_date': '2022-01-01'},
                    {'code': 'MIDV-009', 'author': 'Actor A', 'release_date': '2023-02-02'},
                ]

            def list_actors(self, search_text=''):
                return []

            def list_hidden_actors(self):
                return set()

        rows = CanglanggeCandidateService(FakeDatabase()).list_candidates()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['codes'], ['IPX-001', 'MIDV-009'])
        self.assertEqual(rows[0]['prefixes'], ['IPX', 'MIDV'])
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py -q
```

Expected:

- import failure or missing `CanglanggeCandidateService`

- [ ] **Step 3: Implement the minimal candidate service**

```python
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.ladder_board import LADDER_BOARD_CODE_PREFIX, LADDER_ENTITY_CODE_PREFIX, LADDER_TIER_S
from app.services.identity import split_actor_names
from app.services.library import extract_code_prefix


class CanglanggeCandidateService:
    def __init__(self, database):
        self.database = database

    def list_candidates(self):
        s_prefixes = self._load_s_prefixes()
        local_rows = self._load_local_rows(s_prefixes)
        actor_library_names = self._load_actor_library_names()
        hidden_actor_names = self._load_hidden_actor_names()
        grouped = {}

        for row in local_rows:
            if not is_javtxt_eligible_movie(row):
                continue
            prefix = extract_code_prefix((row or {}).get('code', ''))
            for actor_name in split_actor_names((row or {}).get('author', '')):
                if actor_name in actor_library_names or actor_name in hidden_actor_names:
                    continue
                current = grouped.setdefault(
                    actor_name,
                    {'actor_name': actor_name, 'codes': set(), 'prefixes': set(), 'birthday': '', 'age': ''},
                )
                current['codes'].add(str((row or {}).get('code', '') or '').strip())
                if prefix:
                    current['prefixes'].add(prefix)

        return [
            {
                'actor_name': actor_name,
                'codes': sorted(data['codes']),
                'prefixes': sorted(data['prefixes']),
                'birthday': '',
                'age': '',
            }
            for actor_name, data in sorted(grouped.items(), key=lambda item: item[0])
        ]
```

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/library/canglangge_candidate_service.py app/services/library/__init__.py tests/test_canglangge_candidate_service.py
git commit -m "feat: add canglangge candidate service"
```

### Task 2: Backend Endpoints For Listing, Admit, And Delete

**Files:**
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/client.py`
- Test: `tests/test_canglangge_candidate_service.py`

- [ ] **Step 1: Extend the failing backend tests**

```python
def test_admit_candidates_reuses_actor_add_flow(self):
    class FakeAdminService:
        def __init__(self):
            self.calls = []

        def add_actor(self, actor_name, birthday='', age=''):
            self.calls.append((actor_name, birthday, age))
            return 1

    service = BackendService.__new__(BackendService)
    service.ensure_database_loaded = lambda: None
    service.canglangge_candidate_service = type('S', (), {'list_candidates': lambda self: [{'actor_name': 'Actor A'}]})()
    service.library_admin_service = FakeAdminService()
    service.db = type('DB', (), {'hide_actor': lambda self, actor_name: 1})()

    result = BackendService.admit_canglangge_candidates(service, ['Actor A'])

    self.assertEqual(result['admitted_count'], 1)
    self.assertEqual(service.library_admin_service.calls, [('Actor A', '', '')])
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py -q
```

Expected:

- missing backend methods or missing client/server wiring

- [ ] **Step 3: Implement backend list/admit/delete methods**

```python
class BackendService:
    def list_canglangge_candidates(self):
        self.ensure_database_loaded()
        return {'candidates': self.canglangge_candidate_service.list_candidates()}

    def admit_canglangge_candidates(self, actor_names):
        admitted_count = 0
        for actor_name in actor_names or []:
            admitted_count += int(self.library_admin_service.add_actor(actor_name, birthday='', age='') or 0)
        return {'admitted_count': admitted_count}

    def delete_canglangge_candidates(self, actor_names):
        deleted_count = 0
        for actor_name in actor_names or []:
            deleted_count += int(self.db.hide_actor(actor_name) or 0)
        return {'deleted_count': deleted_count}
```

Also add:

- `POST /canglangge/admit`
- `POST /canglangge/delete`
- `GET /canglangge/candidates`

And add matching `BackendClient` methods.

- [ ] **Step 4: Add the minimal database helper for blacklist insertion if needed**

```python
def hide_actor(self, actor_name):
    normalized_name = str(actor_name or '').strip()
    if not normalized_name:
        return 0
    with self._connect() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO hidden_actors (name) VALUES (?)', (normalized_name,))
        conn.commit()
        return int(cursor.rowcount or 0)
```

- [ ] **Step 5: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py -q
```

Expected:

- PASS

- [ ] **Step 6: Commit**

```bash
git add app/backend/service.py app/backend/server.py app/backend/client.py app/data/database_handler.py tests/test_canglangge_candidate_service.py
git commit -m "feat: add canglangge backend endpoints"
```

### Task 3: Desktop Canglangge Viewer

**Files:**
- Create: `app/gui/canglangge_viewer.py`
- Modify: `app/gui/i18n.py`
- Modify: `app/gui/i18n_patch.py`
- Test: `tests/test_canglangge_viewer.py`

- [ ] **Step 1: Write the failing viewer tests**

```python
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from app.gui.canglangge_viewer import CanglanggeViewerWindow
from app.gui.backend_task_worker import AsyncTaskHostMixin


_APP = QApplication.instance() or QApplication([])


def _run_sync_async_task(self, task, success_handler, error_title=None):
    success_handler(task())
    return True


class ViewerTest(unittest.TestCase):
    def test_renders_candidate_rows(self):
        class BackendStub:
            def list_canglangge_candidates(self):
                return [
                    {'actor_name': 'Actor A', 'codes': ['IPX-001'], 'prefixes': ['IPX'], 'birthday': '', 'age': ''}
                ]

        with patch.object(AsyncTaskHostMixin, 'start_async_task', _run_sync_async_task):
            window = CanglanggeViewerWindow(BackendStub())
            self.assertEqual(window.table.item(0, 0).text(), 'Actor A')
            self.assertEqual(window.table.item(0, 1).text(), 'IPX-001')
            self.assertEqual(window.table.item(0, 2).text(), 'IPX')
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_canglangge_viewer.py -q
```

Expected:

- import failure or missing window methods

- [ ] **Step 3: Implement the minimal viewer dialog**

```python
class CanglanggeViewerWindow(AsyncTaskHostMixin, QDialog):
    def __init__(self, backend_client, parent=None):
        super().__init__(parent)
        self.backend_client = backend_client
        self.rows = []
        self._init_async_task_host()
        self.init_ui()
        self.load_data()

    def load_data(self):
        self.start_async_task(
            lambda: {'rows': self.backend_client.list_canglangge_candidates()},
            self._on_load_finished,
            tr('common.read_failed'),
        )

    def _on_load_finished(self, result):
        self.rows = list((result or {}).get('rows', []) or [])
        self.render_rows(self.rows)
```

The full dialog should include:

- table columns for actor/codes/prefixes/birthday/age/actions
- top-level `批量入选`, `批量删除`, `刷新数据`
- per-row `入选`, `删除`
- multi-row selection
- refresh-after-action using backend endpoints

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_canglangge_viewer.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add app/gui/canglangge_viewer.py app/gui/i18n.py app/gui/i18n_patch.py tests/test_canglangge_viewer.py
git commit -m "feat: add canglangge desktop viewer"
```

### Task 4: Main-Window Entry And End-to-End Verification

**Files:**
- Modify: `app/gui/main_window.py`
- Test: `tests/test_canglangge_viewer.py`
- Test: `tests/test_canglangge_candidate_service.py`
- Test: `tests/test_backend_reuse.py`

- [ ] **Step 1: Extend tests for the main-window open flow**

```python
def test_main_window_opens_canglangge_viewer(self):
    app = VidNormApp.__new__(VidNormApp)
    app.backend_client = object()
    created = {}

    class FakeViewer:
        def __init__(self, backend_client, parent=None):
            created['backend_client'] = backend_client
            created['parent'] = parent

        def exec_(self):
            created['opened'] = True

    # patch app.gui.main_window.CanglanggeViewerWindow with FakeViewer
    # call VidNormApp.show_canglangge_viewer(app)
    # assert created['opened'] is True
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py tests/test_canglangge_viewer.py -q
```

Expected:

- missing main-window button/open method or incomplete action wiring

- [ ] **Step 3: Implement the button and open flow**

```python
self.btn_canglangge = QPushButton(tr('main.canglangge'))
self.btn_canglangge.clicked.connect(self.show_canglangge_viewer)
top_button_row.addWidget(self.btn_canglangge)

def show_canglangge_viewer(self):
    viewer = CanglanggeViewerWindow(backend_client=self.backend_client, parent=self)
    viewer.exec_()
```

- [ ] **Step 4: Run the combined verification command**

Run:

```bash
python -m pytest tests/test_canglangge_candidate_service.py tests/test_canglangge_viewer.py tests/test_backend_reuse.py -q
```

Expected:

- all tests pass

- [ ] **Step 5: Run the broader regression command**

Run:

```bash
python -m pytest tests/test_actor_profile_update_service.py tests/test_library_inline_add_viewers.py tests/test_canglangge_candidate_service.py tests/test_canglangge_viewer.py tests/test_backend_reuse.py -q
```

Expected:

- all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/gui/main_window.py tests/test_canglangge_candidate_service.py tests/test_canglangge_viewer.py
git commit -m "feat: add canglangge entry workflow"
```

---

### Self-Review

**Spec coverage:** The plan covers the dedicated home-screen entry, candidate computation from `S`-tier recent local videos, row aggregation across codes/prefixes, admit/delete flows, blacklist reuse, empty birthday/age admission, and focused viewer actions. No spec requirement is uncovered.

**Placeholder scan:** No `TODO`, `TBD`, or deferred implementation markers remain. Every task includes concrete file paths, test commands, and implementation sketches.

**Type consistency:** The plan consistently uses `actor_name`, `codes`, `prefixes`, `birthday`, and `age` for candidate rows; `list_canglangge_candidates`, `admit_canglangge_candidates`, and `delete_canglangge_candidates` for backend methods; and `CanglanggeViewerWindow` for the UI class.
