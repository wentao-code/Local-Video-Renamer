# Queen Search Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch each queen keyword through five default pages and five relevance-sorted pages with primary/backup domain selection.

**Architecture:** Extend `QueenSearchScraper.search()` to navigate the ten URL variants on one reused browser page, select `y.9cili.click` on the first successful page, and fall back to `a.1cili.click` only for the first-page access failure. Merge and dedupe all page records before returning them to the unchanged service import pipeline.

**Tech Stack:** Python, Playwright page abstraction, pytest.

## Global Constraints

- Make exactly ten search URL variants per keyword in normal operation.
- Use `y.9cili.click` as primary and `a.1cili.click` as fallback.
- Keep the existing `page` session reuse contract.
- Deduplicate combined results by normalized raw title before service routing.
- Preserve `source_url` compatibility and add `source_urls` for the complete URL list.

---

### Task 1: Add failing scraper tests

**Files:** `code/tests/test_queen_search_scraper.py`

- [x] Test URL construction for default pages 1-5 and relevance pages 1-5.
- [x] Test one search visits ten URLs in the required order and deduplicates a title repeated across pages.
- [x] Test a primary first-page navigation failure selects the backup domain for all ten URLs.
- [x] Run the focused tests and confirm the current one-page search implementation fails.

### Task 2: Implement paginated search and domain fallback

**Files:** `code/app/queen_library/scraper.py`

- [x] Add primary/backup domain constants and URL construction with optional sort/page/base URL parameters.
- [x] Let the first page use the existing readiness/retry flow with one-time backup-domain switching.
- [x] Navigate the remaining nine URLs on the selected domain using the existing page object.
- [x] Merge page records by normalized raw title while preserving detail URLs.
- [x] Return `source_url` and `source_urls` without changing the existing records contract.
- [x] Run scraper tests until all pass.

### Task 3: Verify service compatibility

**Files:** `code/app/queen_library/service.py`, `code/tests/test_queen_library_service.py`

- [x] Confirm the service consumes the merged records once and still performs author-first routing and queen fallback.
- [x] Add a service regression test using a multi-page scraper stub if needed.
- [x] Run all queen-library and scraper tests.

### Task 4: Regression verification

- [x] Run the complete pytest suite.
- [x] Run `python -m compileall -q code`.
- [x] Run `git diff --check`.
