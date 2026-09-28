# Queen Video Size and Publish Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture file size and source publish date for queen-library videos, persist them through both author-first and queen routes, and enrich missing fields when a later crawl finds a duplicate.

**Architecture:** Parse metadata from each search-result row and carry it through the existing staging table. Add nullable columns idempotently to staging and both video tables, then update only missing metadata on duplicate identities. Include the fields in existing snapshot queries and show them in both detail tables.

**Tech Stack:** Python, Playwright, SQLite, PyQt, pytest.

## Global Constraints

- File size is stored as nullable integer bytes in `file_size_bytes`.
- `published_at` is nullable text preserving the source's date/time without inventing a timezone.
- Existing `(queen_name, video_title)` identity and author-first routing remain unchanged.
- Duplicate handling fills only currently empty fields from usable newly scraped values; populated fields are never overwritten.
- Existing rows are not batch-fetched; they are enriched only when a later crawl rediscovers them.
- Preserve unrelated working-tree changes and do not run tests with an unrelated global Python interpreter.

---

## File Map

- `code/app/queen_library/scraper.py`: extract visible row size/date and normalize the size value.
- `code/app/queen_library/service.py`: add idempotent columns, stage metadata, route metadata, enrich queen and author duplicates, and expose the fields in snapshots/merge helpers.
- `code/app/queen_library/viewer.py`: render size/date in queen and author detail tables.
- `code/app/gui/i18n_patch.py`: add localized column headings.
- `code/tests/test_queen_search_scraper.py`: test row extraction and size parsing.
- `code/tests/test_queen_library_service.py`: test old-schema migration, inserts, both duplicate paths, and snapshot values.
- `code/tests/test_queen_library_viewer.py`: test table headings and rendered values in both detail views.

## Task 1: Search-Result Metadata Extraction

**Interfaces:** `QueenSearchScraper.extract_result_row_records` returns records with `raw_title`, `detail_url`, `file_size_bytes`, and `published_at`. Missing or invalid metadata is `None` and does not discard the title.

- [x] Add a failing DOM-row fixture test in `test_queen_search_scraper.py` where the result row contains a title link, size text, and date text; assert the extracted record has the same title/link, an integer byte count, and the displayed date/time.
- [x] Add failing cases for recognized size units and missing/invalid size; assert missing fields are `None` while the video record remains extracted.
- [x] Run the focused scraper test and confirm it fails because metadata is not currently returned.
- [x] Implement selectors based on the result-row structure and a focused size parser for the site's displayed units; preserve the displayed publish timestamp as text.
- [x] Re-run the focused scraper tests and confirm all pass.

## Task 2: Schema, Staging, Routing, and Duplicate Enrichment

**Interfaces:** Scraped records and staging rows carry nullable `file_size_bytes` and `published_at`; `queen_videos` and `queen_author_video_records` persist both fields.

- [x] Add failing service tests that initialize against a pre-existing queen schema and verify all three tables acquire the two columns without changing existing rows.
- [x] Add failing service tests for metadata insertion into queen-routed and author-owned records.
- [x] Add failing duplicate-enrichment tests for each storage route: an existing record with missing metadata receives new nonempty values, populated values stay unchanged, absent new values do not clear existing data, and row counts remain unchanged.
- [x] Run the new focused service tests and confirm failures expose the missing schema and duplicate-update behavior.
- [x] Add the two nullable columns idempotently to all three tables using the existing `_ensure_column` pattern.
- [x] Extend scraped-record normalization and staging insert/select to preserve the two values.
- [x] Extend queen insert and conflict handling to fill only `NULL`/empty fields from nonempty staged values.
- [x] Extend `_store_author_first_record` so an already-linked queen video or an existing author-owned record is enriched without creating a duplicate.
- [x] Run the focused service tests and the existing author-first routing tests.

## Task 3: Snapshot and Merge Propagation

**Interfaces:** `get_queen_detail` and `get_queen_author_detail` return `file_size_bytes` and `published_at` on every video row; duplicate/merge helpers retain them.

- [x] Add failing service assertions for both detail payloads and merged duplicate video rows.
- [x] Run those focused assertions and confirm the metadata is absent or dropped by selection/normalization.
- [x] Add both fields to the explicit SELECT lists, row normalizer, loader helpers, and merge selection logic that constructs queen video rows.
- [x] Re-run service tests, including queen merge and author snapshot coverage.

## Task 4: Detail-View Presentation

**Interfaces:** Both detail tables show columns for file size and publish date; missing values render blank; file sizes render in readable units.

- [x] Add failing viewer tests that load representative queen and author records and assert both columns display the supplied values and empty values remain blank.
- [x] Run the focused viewer tests and confirm the current six-column views do not expose the new fields.
- [x] Add localized headings in `i18n_patch.py`; extend both tables and row renderers in `viewer.py`, keeping the existing action/link columns intact.
- [x] Format integer bytes into readable units in the view layer without changing persisted bytes.
- [x] Re-run viewer tests and verify all headers/cell indices are aligned.

## Task 5: Verification

- [x] Check interpreter configuration and confirm the approved `D:\Anaconda3\python.exe` interpreter with `-c "import sys; print(sys.executable)"` before running tests.
- [x] Run focused tests: `tests/test_queen_search_scraper.py`, `tests/test_queen_library_service.py`, and `tests/test_queen_library_viewer.py`.
- [x] Run the full `code/tests` suite: 1016 passed, 24 subtests passed.
- [x] Run `git diff --check` and inspect the final diff; pre-existing Feishu changes remain untouched.
