# Queen Author-First Crawl Routing

## Goal

When a newly crawled record contains an enrolled queen-library author name, route it directly to the independent queen author library. Only records with no author match continue into the existing queen keyword video table.

## Behavior

- Crawl results are normalized before routing.
- Enrolled authors are checked first using the existing trimmed, case-folded substring rule.
- Author-matched records are stored in an author-owned video table and linked to every matching author.
- Author-matched records are never inserted into `queen_videos`.
- Records without an author match retain the current `queen_videos` import and keyword behavior.
- Existing `queen_videos` rows are not migrated or deleted.
- Repeated crawls are idempotent across both author-owned and queen video records.
- Staging rows are removed after successful routing; failed batches remain marked for diagnosis.

## Data Design

`queen_crawl_staging` stores one normalized row per crawl result while the import transaction classifies it. `queen_author_video_records` stores video fields for author-only records. `queen_author_video_links` associates one author-owned record with one or more enrolled authors. Existing `queen_author_videos` remains the relation for historical rows backed by `queen_videos`.

Author detail queries combine historical relation-backed rows and author-owned rows. Removing an author removes its links and orphaned author-owned records without touching `queen_videos`.

## Verification

Tests cover author-first routing, no queen row for a matched record, fallback routing, duplicate crawls, multi-author matches, and cleanup of author-owned records.
