# Video Entity Repository Finalization Design

## Goal

Complete the consolidation around `video_entities` so that exclusion decisions,
canonical actor/code-prefix writes, active-entity projection, and enrichment SQL
have explicit single ownership.

## Scope

This work is delivered in three ordered phases:

1. Use `video_entity_exclusions` as the only runtime exclusion decision source.
2. Move actor/code-prefix replacement writes into `VideoEntityRepositoryMixin`.
3. Make `active_video_entities` a one-way derived read model and move the
   remaining unified-entity candidate and enrichment SQL into the repository.

## Exclusion Model

`hidden_actors`, `hidden_code_prefixes`, and persisted filter settings remain
editable configuration inputs. They are not queried by visibility, library, or
enrichment-candidate paths.

`rebuild_video_entity_exclusions()` materializes their effects, together with
entity metadata and relations, into `video_entity_exclusions`. Runtime paths
determine visibility and eligibility only with scoped exclusion predicates
against that table. A configuration or relevant canonical-data change rebuilds
the affected projection before subsequent reads.

The canonical archive remains intact. Exclusions never delete rows from
`video_entities`, `local_video_records`, or relation tables.

## Canonical Write Model

`VideoEntityRepositoryMixin` owns the write primitive for an entity, optional
local record, actor relations, code-prefix relations, and relation metadata.
Actor and code-prefix refreshes reuse that primitive rather than maintaining
separate `_upsert_actor_movie_canonical` and
`_upsert_code_prefix_movie_canonical` SQL implementations.

`replace_actor_movies()` and `replace_code_prefix_movies()` move to the
repository while preserving their existing public signatures and refresh
semantics. `VideoDatabase` remains a facade for callers and coordinates rules,
task state, and non-entity domains.

## Active Entity Projection

`video_entities` and `local_video_records` are the only writable entity data
sources. `active_video_entities` is a materialized, rebuildable read model used
by runtime queries. Its synchronization is one-way from the source tables and
the exclusion projection.

The trigger that writes from `active_video_entities` back into archive and
local-record tables is removed. Every direct active-table write is migrated to
the matching canonical source write followed by projection refresh. A rebuild
must produce the same active rows from canonical tables and exclusions.

## Candidate And Enrichment Ownership

Unified-video SQL for enrichment candidate selection, result writeback, and
actor/code-prefix relation statistics moves into `VideoEntityRepositoryMixin`
in focused batches. The repository owns SQL and row shaping; `VideoDatabase`
keeps orchestration and existing public entry points by delegation.

Repository reads may use a small shared rule/exclusion predicate component,
but must not depend on `VideoDatabase` private helpers. That component owns SQL
predicate construction and residual rule application.

## Compatibility And Safety

- Retain public `VideoDatabase` method signatures while delegating internally.
- Retain editable blacklist tables and filter settings as configuration inputs.
- Do not recreate legacy `processed_videos`, `actor_movies`, or
  `code_prefix_movies` paths.
- Use transactional writes and rebuilds so relation replacement cannot leave a
  partially refreshed projection.
- Add behavior tests before each migration batch, including exclusion scope,
  replacement writes, one-way active projection, candidates, and result
  writeback.

## Completion Criteria

- Runtime display and candidate queries use `video_entity_exclusions` only for
  exclusion decisions.
- Actor and code-prefix replacement writes are repository-owned and use one
  canonical relation-write path.
- No code writes directly to `active_video_entities`; it no longer has a
  write-back trigger.
- Unified-entity candidate, enrichment-result, and relation-statistics SQL is
  repository-owned or uses an explicitly scoped shared predicate component.
- Targeted regression tests, full test suite, `ruff`, `pyflakes`, and
  `git diff --check` pass.
