# Operation Timeout Settings Design

## Goal

Add a main-window timeout manager that lists user-visible operation timeouts, stores only overrides in SQLite, and applies changes to the next operation without restarting the application.

## Registry And Storage

`app/core/operation_timeout_settings.py` owns an ordered registry. Each entry has a stable key, Chinese operation name, default seconds, minimum seconds, and maximum seconds. The first version includes: normal backend request, list/detail load, snapshot refresh/rebuild, automatic login, manual verification, manual login, AVFan page load, JAVTXT page load, Binghuo page load, Baomu page load, queen-library page load, network probe, database wait, and local media metadata read.

SQLite table `operation_timeout_settings` stores `setting_key`, nullable `custom_value_seconds`, and `updated_at`. Code defaults remain authoritative and are never copied into rows. Unknown keys, non-finite values, zero, negative values, and values outside each entry's safe bounds are rejected atomically.

## Runtime Behavior

Operation-level callers resolve the effective value immediately before starting their next request, page navigation, probe, database connection, or subprocess. Existing waits already in progress are not interrupted. Internal element checks, short page waits, UI polling intervals, cooldowns, and retry sleeps remain unchanged.

Backend endpoints list, update, reset selected, and reset all settings. GUI and backend processes read the same SQLite table, so no restart is required.

## UI

The main window gets a `Timeouts` button. A single-instance dialog contains a row-selectable table with operation name, default seconds, editable custom seconds, effective seconds, and a fixed-size status light. Green means default; red means override. Buttons are Confirm Changes, Restore Selected Default, Restore All Defaults, and Refresh. Validation errors keep the dialog open and identify the operation.

## Verification

Tests cover schema creation, ordered listing, decimal values, atomic validation, selected/all reset, API paths, effective runtime reads, scraper and subsystem integration, indicator colors, row editing, main-window entry, and the complete regression suite.
