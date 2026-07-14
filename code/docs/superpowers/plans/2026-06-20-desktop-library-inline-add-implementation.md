# Desktop Library Inline Add Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline top-row creation flows to the desktop actor library and code prefix library, with duplicate prevention and hidden-entry validation.

**Architecture:** Extend the existing backend/library-admin/database path with explicit `add_actor` and `add_code_prefix` operations, then reuse the current table-based edit UX in each PyQt viewer by inserting a temporary editable row at index 0 and flipping the window-level button from add to confirm.

**Tech Stack:** Python, PyQt5, sqlite3, unittest

---

### Task 1: Backend Add Operations

**Files:**
- Modify: `app/services/library/library_admin_service.py`
- Modify: `app/data/database_handler.py`
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/client.py`
- Test: `tests/test_actor_profile_update_service.py`

- [ ] **Step 1: Write failing tests**
- [ ] **Step 2: Run the focused tests and verify they fail for missing add methods**
- [ ] **Step 3: Implement `add_actor` and `add_code_prefix` with visible-duplicate and hidden-entry validation**
- [ ] **Step 4: Re-run the focused tests and verify they pass**

### Task 2: Code Prefix Visibility For Empty Manual Entries

**Files:**
- Modify: `app/services/library/code_prefix_library.py`
- Test: `tests/test_code_prefix_detail_library.py`

- [ ] **Step 1: Write a failing test showing a manually added prefix with only an enrichment record still appears in the library**
- [ ] **Step 2: Run the focused test and verify it fails**
- [ ] **Step 3: Update the prefix aggregation logic to merge enrichment-only prefixes unless hidden**
- [ ] **Step 4: Re-run the focused test and verify it passes**

### Task 3: Desktop Inline Add UX

**Files:**
- Modify: `app/gui/actor_viewer.py`
- Modify: `app/gui/code_prefix_viewer.py`
- Modify: `app/gui/i18n.py`
- Modify: `app/gui/i18n_patch.py`
- Test: `tests/test_actor_code_prefix_library_sorting.py`

- [ ] **Step 1: Write failing viewer tests for entering add mode, confirming a new row, and blocking duplicate values**
- [ ] **Step 2: Run the focused viewer tests and verify they fail**
- [ ] **Step 3: Implement top-row add state, confirm handling, duplicate warnings, and button label toggling**
- [ ] **Step 4: Re-run the focused viewer tests and verify they pass**

### Task 4: Final Verification

**Files:**
- Test: `tests/test_actor_profile_update_service.py`
- Test: `tests/test_code_prefix_detail_library.py`
- Test: `tests/test_actor_code_prefix_library_sorting.py`

- [ ] **Step 1: Run the combined focused test command for backend and viewer coverage**
- [ ] **Step 2: Review output for failures or warnings and fix anything uncovered**
- [ ] **Step 3: Re-run the same command and keep the final passing output as verification evidence**
