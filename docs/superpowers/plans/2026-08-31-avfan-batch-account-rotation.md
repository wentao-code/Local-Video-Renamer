# AVFan Batch Account Rotation Implementation Plan

**Goal:** Rotate enabled and logged-in AVFan accounts for eligible batch enrichment tasks.

**Scope:** Apply only to AVFan batch enrichment for actor library, code-prefix library, and supplement tasks. Leave Queen Library, Javtxt, and ordinary single-run tasks unchanged.

**Design:** Select an eligible account at the start of each batch in ascending `account_id` order, advance a persisted in-memory rotation cursor, bind the selected `account_id` to the queue record, and skip unavailable accounts. If no eligible account exists, keep the batch task waiting for an account.

**Tests:** Add main-window regressions for cycling, unavailable-account skipping, and non-eligible task behavior; run the full Python test suite.
