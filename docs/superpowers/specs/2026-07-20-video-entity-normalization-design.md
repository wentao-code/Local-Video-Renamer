# Video Entity Normalization Design

**Goal:** Normalize all video records by standardized `code`, preserve many-to-many actor and code-prefix relationships, and make supplement enrichment status video-level so a video is not enriched repeatedly through different libraries.

## Architecture

`video_entities` becomes the single authoritative video table with one row per standardized code. `video_actor_relations` and `video_code_prefix_relations` store library membership and relationship-specific metadata. The existing `processed_videos` name remains available during migration as a compatibility view while application writes are moved to `video_entities`.

Supplement status is stored on `video_entities`. A video with a terminal supplement status is excluded from actor, code-prefix, and video supplement candidates. Actor and prefix library queries join their relation table to the same video entity instead of maintaining independent copies of title, dates, source URLs, and supplement fields.

## Data Rules

- `standardize_video_code()` is applied before every entity lookup and relation insert.
- `video_entities.code` is the primary key.
- `video_actor_relations` is unique on `(video_code, actor_name)`.
- `video_code_prefix_relations` is unique on `(video_code, prefix)`.
- Non-empty values are merged deterministically: prefer an existing enriched value, then a non-empty source value; never replace a non-empty value with an empty value.
- Existing actor and prefix relationships are preserved during migration.
- Supplement completion updates the entity once; all libraries observe the same video-level status.

## Compatibility

The migration is additive and runs inside the existing SQLite initialization transaction. Existing tables are copied into the normalized tables before reads switch. `processed_videos` is retained as a compatibility view only after all application write paths use `video_entities`; actor and prefix legacy tables remain read-compatible during the transition and are no longer authoritative.

## Rollout

1. Create normalized tables and indexes.
2. Backfill entities by standardized code and copy actor/prefix relationships.
3. Add repository APIs for entity and relationship reads/writes.
4. Switch candidate selection, supplement updates, library views, and statistics to joins over normalized tables.
5. Add consistency checks and compatibility tests.
6. Convert `processed_videos` to a compatibility view only after all writes have moved.

## Failure Handling

Migration is idempotent and preserves the original tables until the compatibility switch is complete. A failed migration leaves the old tables usable. Duplicate entity values are merged without deleting source records until consistency checks pass.

## Verification

Tests must prove: one entity per normalized code, preservation of all actor/prefix relations, cross-library supplement de-duplication, compatibility query behavior, idempotent startup migration, and no loss of source/status fields.
