# Data Center Video Count Analysis Design

## Goal

Add a video-count metric to actor analysis and code-prefix analysis while preserving the existing snapshot-first refresh flow, clickable distribution buckets, and detail navigation.

## Counting Rules

Actor counts use distinct effective video codes whose normalized category is either `VIDEO_CATEGORY_SINGLE` or `VIDEO_CATEGORY_CO_STAR`. The effective-video set must use the same filter settings already applied by `DataCenterService`.

Actor buckets are mutually exclusive: 0-4, 5-9, 10-29, 30-79, and 80 or more.

Code-prefix counts use distinct effective video codes belonging to each normalized prefix, regardless of video category. Code-prefix buckets are mutually exclusive: 0-49, 50-99, 100-299, 300-799, and 800 or more.

Entities with zero qualifying videos remain visible in the first bucket. Rankings sort by count descending and normalized entity name ascending, limited to 50 rows.

## Architecture

Both metrics are registered in the existing actor and code-prefix metric maps with a range-bucket configuration. `DataCenterService` recognizes the count metric and builds distribution rows, ranking rows, and bucket-detail rows from its existing cached and filtered movie loaders. Range classification and labels are configuration-driven so actor and code-prefix behavior share one implementation.

The backend adds code-prefix bucket retrieval alongside the existing actor bucket endpoint. `MetricAnalysisWindow` remains the shared analysis window and opens the correct actor or code-prefix bucket window according to `analysis_type`. Bucket windows use the existing table and detail-viewer patterns.

## UI Behavior

Each analysis landing page gains one `Video Count` metric button using the same dimensions and interaction style as current metric buttons. Distribution buttons show `label: entity count`. Clicking a button opens the corresponding entity list. Actor list rows open actor details; code-prefix list rows open code-prefix details. Ranking displays up to 50 entities and their qualifying video counts.

## Cache And Errors

Analysis and bucket payloads use the current snapshot-first cache. Filter-setting fingerprint changes invalidate cached data. Unknown metrics or bucket keys continue to raise `ValueError`; GUI async workers display existing operation-failure handling.

## Verification

Tests cover exact range boundaries, zero-count entities, category filtering, effective-video filtering, distinct-code counting, deterministic top-50 ordering, backend routing, both bucket windows, and detail navigation. The full pytest suite must pass.
