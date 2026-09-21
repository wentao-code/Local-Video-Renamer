# Queen Search Pagination and Domain Fallback

## Goal

Search every queen-library keyword across two sort modes and five pages per mode, preferring `y.9cili.click` and falling back to `a.1cili.click` when the first search page cannot be reached.

## Behavior

- Each keyword requests these ten URLs in order:
  - `search?q=<keyword>`
  - `search?q=<keyword>&page=2` through `page=5`
  - `search?q=<keyword>&sort=relevance`
  - `search?q=<keyword>&sort=relevance&page=2` through `page=5`
- The first URL is attempted on `y.9cili.click`.
- If that first URL fails to load or is a Cloudflare 522 page, retry it on `a.1cili.click` and use that domain for all remaining URLs.
- If the primary domain loads the first page, all ten URLs use the primary domain.
- Records from all ten responses are merged by normalized raw title before the existing author-first routing and queen-library import logic.
- `source_urls` reports the ten requested URLs; `source_url` remains the first selected URL for backward compatibility.
- Existing session reuse, page readiness checks, transient-error handling, and per-page extraction remain intact.

## Error Handling

Only the first page participates in domain fallback. If both domains fail, the existing transient error is raised. Failures after domain selection retain the existing retry behavior and do not silently switch domains mid-run.

## Verification

Tests verify URL order, ten requests, result deduplication, primary-domain selection, backup-domain selection after navigation failure, and compatibility with the existing scraper and service import flow.
