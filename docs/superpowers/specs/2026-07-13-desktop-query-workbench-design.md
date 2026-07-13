# Desktop Query Workbench Design

## 1. Goal

Upgrade the desktop client from a collection of mostly independent windows into a linked data workbench while preserving the existing multi-window model.

The main workflow is:

`search an entity -> open its detail -> follow related entities -> apply a filter -> inspect the result list`

The upgrade must keep enrichment and other background tasks from blocking read-only data browsing. Existing write operations remain available only in their current task-capable windows.

## 2. Scope

### In scope

- A unified search window for videos, actors, code prefixes, ladder entries, and masterpiece entries.
- Cross-window navigation between video, actor, code-prefix, ladder, and masterpiece views.
- Reusing an already-open detail window for the same entity instead of opening duplicates.
- A shared query context carrying entity type, key, search text, filters, sort order, page, and source window.
- Clickable data-center metrics and distributions that open the matching library with filters applied.
- Preserving list state when returning from a detail window.
- Asynchronous read-only queries, cancellation of stale results, timeout reporting, and retry.
- Local query and recently viewed history stored in client settings, never in the source database.
- Optional side-by-side comparison windows for actors and code prefixes.

### Out of scope

- Replacing the existing multi-window desktop layout with a dock-based shell.
- Moving enrichment, crawling, task scheduling, or database mutation into the query layer.
- Adding write controls to the read-only query center or cross-navigation panels.
- Rebuilding existing detail windows from scratch.

## 3. User Experience

### 3.1 Unified search

The main window gets a global search action. The search window groups results by type:

- 视频
- 演员
- 番号前缀
- 天梯榜
- 名作堂

Double-click opens the corresponding existing viewer. Each result exposes a stable entity type and key so navigation does not depend on display text.

### 3.2 Linked navigation

Existing detail windows emit typed navigation requests instead of constructing other windows directly:

- Video -> actors, code prefix, masterpiece entry.
- Actor -> videos, code prefixes, ladder entry, masterpiece appearances.
- Code prefix -> videos, actors, ladder entry.
- Ladder candidate/selected entry -> actor or code-prefix detail.
- Masterpiece entry -> related video, actors, and code prefix.

The coordinator resolves each request to an existing window or creates one, activates it, and applies the requested context.

### 3.3 Data-center click-through

Every metric or distribution bucket that represents a queryable set becomes clickable. The data-center window emits a `QueryContext` rather than containing library-specific filtering code. The target viewer receives the context and shows:

- the originating filter in the toolbar;
- the filtered result count;
- a clear-filter action;
- the original data-center window as the return source.

### 3.4 Window reuse and state

Open detail windows are keyed by `(entity_type, entity_key)`. Reopening the same entity activates the current window and refreshes only when explicitly requested. List windows preserve search text, filters, sort order, page, and scroll position while a detail window is open.

### 3.5 Query history and comparison

The client stores recent searches, recently viewed entities, and optionally saved query presets in local settings. These records do not use or modify the application database.

Actor and code-prefix comparison windows are read-only and accept two entity keys. The first version compares core identity, age/metadata, work count, ladder status, and source coverage.

## 4. Architecture

### 4.1 Query model

Add a small query-domain module with typed values:

- `EntityType`: video, actor, code prefix, ladder, masterpiece.
- `EntityReference`: entity type plus stable key and display label.
- `QueryContext`: search text, structured filters, sort, page, source, and optional entity reference.
- `NavigationRequest`: target entity or target list plus `QueryContext`.

The models must be serializable to query parameters and must not contain QWidget references.

### 4.2 Window coordinator

Add a coordinator owned by the main window. It maintains weak references to opened viewers and exposes Qt signals for:

- `open_entity(EntityReference, QueryContext)`;
- `open_list(EntityType, QueryContext)`;
- `compare_entities(EntityReference, EntityReference)`;
- `entity_selected(EntityReference)`.

Existing windows receive the coordinator through their constructors or a narrow navigation protocol. The coordinator owns reuse, activation, and cleanup when a window closes.

### 4.3 Search and read services

The unified search service uses existing backend client read methods where available. Missing capabilities are added as read-only service/client methods. No query endpoint may call enrichment, crawling, mutation, or snapshot refresh logic.

Search and related-data requests run through the existing asynchronous GUI worker pattern. Every request carries a monotonically increasing request id; a late result is ignored if the window has already moved to another query.

### 4.4 Existing viewer integration

The implementation extends existing viewers through small adapter methods:

- `apply_query_context(context)` for list viewers;
- `open_entity_reference(reference)` for detail viewers;
- typed navigation signals for links.

This keeps the existing table/detail layout and avoids duplicating repository and formatting logic.

## 5. Data Flow

1. User enters text in the global search window.
2. Search window submits a read-only asynchronous request with a request id.
3. Results return as typed references grouped by entity type.
4. User activates a result.
5. Coordinator resolves or creates the target viewer and activates it.
6. Detail viewer emits a typed related-entity request when a link is clicked.
7. Coordinator routes the request and transfers the query context.
8. The target list viewer loads asynchronously and displays the applied filter.

When a task is running, browsing remains available. Task-mode operations may continue in their existing task windows, while query windows only read the current database/snapshot through non-blocking backend calls. View mode suppresses task execution according to the existing runtime-mode rules.

## 6. Error Handling

- Empty search: show a typed empty state with supported entity categories.
- Network/backend failure: show retry and last successful result timestamp where available.
- Entity removed between search and open: show a not-found state with a new search action.
- Stale asynchronous result: discard silently and keep the newer query visible.
- Window closed during a request: cancel or ignore the result and release the worker.
- Task-mode contention: show a non-blocking status message; never use a modal dialog for ordinary read latency.

## 7. Implementation Phases

### Phase 1: Navigation foundation

- Add query models and the main-window coordinator.
- Add typed navigation requests to existing detail windows.
- Add window reuse and activation tests.

### Phase 2: Unified search

- Add read-only search service/client methods.
- Build grouped search results and route activation.
- Add recent search/recent entity history in local settings.

### Phase 3: Data-center and library click-through

- Convert data-center metrics and distributions into query contexts.
- Add context-aware loading to video, actor, and code-prefix viewers.
- Preserve list state and add clear-filter controls.

### Phase 4: Related data and comparison

- Add missing links in masterpiece and ladder viewers.
- Add actor/code-prefix comparison windows.
- Add read-only export/copy of current results.

### Phase 5: Hardening

- Add stale-result, retry, window-reuse, and cross-navigation tests.
- Run the full desktop test suite and verify browsing while an enrichment task is active.
- Check that query windows never invoke mutation endpoints.

## 8. Acceptance Criteria

- One global search can find all five supported entity types.
- Opening the same entity twice activates one existing window instead of creating duplicates.
- Every listed relationship can be followed in both directions where the data supports it.
- Clicking a data-center distribution opens the correct library with the expected filter.
- Returning from details restores the previous list state.
- A slow or failed read request does not freeze the main window.
- Running enrichment tasks does not prevent query windows from opening and loading.
- Query history and saved presets do not modify the source database.
- Existing enrichment, task queue, ladder write, and masterpiece write workflows keep their current behavior.
