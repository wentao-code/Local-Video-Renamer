# Code Prefix Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data-analysis entry window that branches into actor analysis and code-prefix analysis, and implement a code-prefix "collection video ratio" analysis with 1%-100% rounded distribution counts plus a top-50 leaderboard.

**Architecture:** Keep the current actor analysis result view, but split the UI into an analysis entry dialog, metric-picker dialogs, and a reusable metric result dialog. Extend the backend analysis endpoint to accept an analysis type, then add a code-prefix aggregation path in `DataCenterService` that reuses existing visible-video filtering and code-prefix movie sources.

**Tech Stack:** Python, PyQt5, unittest, existing backend HTTP layer, `DataCenterService`

---

### Task 1: Lock the new analysis payload with tests

**Files:**
- Modify: `tests/test_data_center_summary.py`

- [ ] Add failing tests for code-prefix collection-ratio distribution rows, top-50 ranking order, and filter exclusion.
- [ ] Run the targeted tests and confirm the new assertions fail before implementation.

### Task 2: Add code-prefix analysis support in the backend/service layer

**Files:**
- Modify: `app/backend/client.py`
- Modify: `app/backend/server.py`
- Modify: `app/backend/service.py`
- Modify: `app/services/library/data_center_service.py`
- Create or modify metric config modules under `app/core/`

- [ ] Implement a generic analysis-type request path while preserving the current actor-analysis behavior.
- [ ] Add code-prefix metric config for `collection_ratio`.
- [ ] Implement the code-prefix aggregation, rounded 1%-100% buckets, and top-50 ranking payload.
- [ ] Run the targeted data-center tests until they pass.

### Task 3: Reshape the desktop analysis UI around entry + type-specific windows

**Files:**
- Modify: `app/gui/data_center_analysis_viewer.py`
- Modify: `app/gui/data_center_viewer.py`
- Modify: `app/gui/i18n_patch.py`
- Optionally modify: `tests/test_data_center_viewer.py`

- [ ] Replace the single actor-analysis entry dialog with an analysis entry dialog that opens actor or code-prefix metric pickers.
- [ ] Reuse the existing result dialog for both analysis types, including six-items-per-line formatting for the new code-prefix metric.
- [ ] Add or update GUI tests that verify the new analysis entry behavior.

### Task 4: Verify the finished feature with fresh evidence

**Files:**
- No code changes expected

- [ ] Run the targeted backend and GUI tests for the touched feature area.
- [ ] Review the diff for consistency with the approved behavior before reporting completion.
