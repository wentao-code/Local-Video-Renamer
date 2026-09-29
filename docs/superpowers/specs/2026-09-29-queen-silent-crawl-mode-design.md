# Queen Library Silent Crawl Mode

## Goal

Let users choose whether Queen Library and Standard Reference crawls display
their Chromium browser windows.

## Behavior

- Add an enabled/disabled `静默模式` toggle to both library pages.
- Default the toggle to off, preserving the current visible-browser behavior.
- The setting lasts for the current page window and is not persisted.
- Queen Library keyword searches and batch crawls use the selected mode.
- Standard Reference crawls use the selected mode.
- Login actions always open the existing visible browser.
- Both modes continue to use Chromium, load the target pages, run JavaScript,
  and extract page content. Silent mode only selects headless browser launch.

## Implementation

- Pass the selected mode through Queen Library UI and backend client to the
  existing `show_browser` service option.
- Add a headless option to `StandardReferenceScraper` and set the persistent
  Chromium context's Playwright `headless` argument from it.
- Keep each library's existing profile, browser lifecycle, parsing, task queue,
  cancellation, and progress behavior.

## Verification

- Cover both toggle defaults and selected values passed to crawl/search calls.
- Cover visible and headless launch arguments in scraper tests.
- Run focused Queen Library and Standard Reference tests.
