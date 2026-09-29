# Queen Library Silent Crawl Mode Implementation Plan

> **For agentic workers:** Use this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-window Silent Mode toggle to Queen Library and Standard Reference Library browser tasks.

**Architecture:** Queen Library already exposes `show_browser` through its service, so the UI choice will flow through the existing client API. Standard Reference will accept a `headless` option and pass it to Playwright's persistent Chromium context. Both choices default to visible mode and only affect the current window instance.

**Tech Stack:** Python, PyQt5, Playwright Chromium, existing HTTP backend.

## Global Constraints

- Default the toggle to off, preserving the current visible-browser behavior.
- The setting lasts for the current page window and is not persisted.
- Login actions always open the existing visible browser.
- Both modes continue to use Chromium, load the target pages, run JavaScript, and extract page content.
- Silent mode only selects headless browser launch.

---

## File Structure

- `code/app/queen_library/viewer.py`: add page-level toggles and pass mode choice to search/crawl calls.
- `code/app/backend/client.py`: pass the mode through Queen Library APIs and Standard Reference crawl request.
- `code/app/backend/server.py`: accept the Standard Reference headless request value.
- `code/app/backend/service.py`: pass the value into the Standard Reference worker and scraper.
- `code/app/queen_library/standard_reference_scraper.py`: configure persistent Chromium visibility.
- `code/app/gui/i18n_patch.py`: add Chinese and English labels.

### Task 1: Wire Silent Mode Through Both Library Pages

**Files:**
- Modify: `code/app/queen_library/viewer.py`
- Modify: `code/app/backend/client.py`
- Modify: `code/app/backend/server.py`
- Modify: `code/app/backend/service.py`
- Modify: `code/app/queen_library/standard_reference_scraper.py`
- Modify: `code/app/gui/i18n_patch.py`

**Interfaces:**
- Queen client APIs keep their existing `show_browser` boolean and receive the toggle value from the UI.
- `BackendClient.start_standard_reference_crawl(start_page, end_page, headless=False)` posts `headless` with the range.
- `BackendClient.crawl_standard_reference(start_page, end_page, poll_interval=1.0, progress_callback=None, headless=False)` preserves existing positional polling arguments and passes the mode to start.
- `BackendService.start_standard_reference_crawl(start_page, end_page, headless=False)` forwards it to the worker.
- `StandardReferenceScraper(profile_dir=None, playwright_factory=None, headless=False)` starts the persistent context with the requested `headless` value.

- [ ] Add a `QCheckBox` labeled `静默模式` to the Queen Library toolbar and Standard Reference Library controls. Leave it unchecked by default. Keep the login action independent of the toggle.
- [ ] In Queen Library `search_keyword` and `start_crawl`, pass `show_browser=not self.silent_mode_checkbox.isChecked()` to their existing backend calls.
- [ ] Extend Standard Reference client, route, service worker arguments, and scraper constructor with `headless`; pass `self.silent_mode_checkbox.isChecked()` from the page's crawl call.
- [ ] In `StandardReferenceScraper._open_session`, set `headless=self.headless` on `launch_persistent_context` and retain the existing Chrome profile, locale, viewport, and page selection.
- [ ] Add localized `queen.library.silent_mode` and `standard_reference.silent_mode` labels in Chinese and English.
- [ ] Inspect the final diff and confirm both launch modes still use their existing Chromium browser and page parsers, and login still launches the visible browser.

## Verification Boundary

Automated tests are not included in this change unless requested. Perform static call-chain review and `git diff --check` only.
