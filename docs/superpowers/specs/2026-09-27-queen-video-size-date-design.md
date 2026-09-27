# Queen Video Size and Publish Date Design

## Goal

Capture and display each queen-library video's file size and source publish date, while allowing later duplicate crawls to fill missing metadata on existing records.

## Data model

Add nullable `file_size_bytes INTEGER` and `published_at TEXT` columns to `queen_crawl_staging`, `queen_videos`, and `queen_author_video_records`. File size is stored as an integer byte count. `published_at` preserves the source's displayed date/time without inventing a timezone. Missing or unparseable values remain `NULL`.

The existing startup schema initialization will add the columns idempotently. Existing rows are not bulk-fetched or assigned synthetic values; their new columns remain `NULL` until a later crawl finds the same record.

## Capture and routing

The scraper extracts title, detail URL, file size, and displayed date from each search-result row. The staging record carries all four values. The existing author-first routing then stores the metadata in the same destination as the video:

- Queen-routed records go to `queen_videos`.
- Author-owned records go to `queen_author_video_records`, unless an existing queen video is linked to the author, in which case that queen video remains the source record.

## Duplicate behavior

Use the existing `(queen_name, video_title)` duplicate identity. On a duplicate, update only metadata fields currently `NULL` or empty and only when the new crawl provides a usable value. Do not overwrite populated values, create a second record, or change author/queen routing. Apply this behavior for both queen records and author-owned records.

## Reads and presentation

Include both values in queen-detail and queen-author-detail database queries, row normalization, any duplicate/merge helpers, and both detail tables. Display file size in a human-readable unit and the source publish date as captured. Empty values display blank.

## Failure handling

If a row lacks either field or parsing fails for one field, retain the other field and continue processing the video. Database migration is additive and idempotent. No extra legacy backfill job or crawl-time network request is introduced.

## Verification

Tests cover list-row extraction, size/date normalization, migration on a pre-existing database, insertion through both routing paths, duplicate enrichment of missing values without overwriting existing values or creating extra rows, and both detail payloads/UI columns. Run the focused queen scraper, service, and viewer tests, followed by the relevant broader test suite using the configured project interpreter.
