# Baomu Actor Birthday Enrichment Design

## Goal

Add a second actor-profile enrichment source named `保木` to the existing `演员生日` workflow.

This workflow must:

- keep `保木` source data independent from `并火`
- allow `演员生日` to choose between `并火` and `保木`
- only enqueue `保木` candidates after `并火` has already run and the actor still lacks at least one required profile field
- support both `沧浪阁` candidates and actor-library rows
- show merged actor profile values in the detail page while preserving source-specific stored fields

The `保木` source is backed by Netflav actress pages:

`https://netflav.com/all?actress=<actor_name>`

The initial verification example is:

`https://netflav.com/all?actress=一松愛梨`

## User Experience

### Enrichment Dialog

When `演员生日` is selected:

- the source section shows two radio options:
  - `并火`
  - `保木`
- the combo-task group remains hidden
- the combo-task action buttons remain hidden
- the cooldown option remains hidden
- regular single-run, batch-run, and save actions remain available

Source selection must persist in the existing enrichment settings payload, just like other target/source pairs.

### Detail Page

The actor detail page should continue to show one visible set of birthday, height, and measurements, but these values now come from a merged view:

1. actor-library base fields
2. `并火` fallback fields
3. `保木` fallback fields

This keeps the detail page readable while still allowing the database to preserve per-source provenance.

The detail payload should also expose `保木` source status and raw `保木` fields so future UI work can show source-level diagnostics if needed.

## Required Profile Fields

For `保木` candidate selection, the required actor profile fields are:

- birthday
- height
- bust
- waist
- hip

An actor is considered still incomplete if any one of these fields is empty after the merged `actor-library + 并火` view is evaluated.

`age` is useful when present, but it is not part of the gating rule described by the user and must not block completion by itself.

## Candidate Rules

`保木` candidates are drawn from the union of:

- `沧浪阁` candidates
- actor-library rows

Deduplicate by actor name across both sources.

An actor becomes eligible for `保木` only if all of the following are true:

1. `并火` has already been attempted for that actor
2. the `并火` result is not an untouched `未补全` state
3. the merged `actor-library + 并火` profile still lacks at least one required field
4. the actor has not already been fully completed by `保木`

The intended reading of "并火补全之后沧浪阁或者演员库仍然缺生日、身高、三围等任何一个数据" is:

- `保木` is a second-pass completion source
- `保木` does not compete with `并火` for first-pass discovery
- `保木` focuses on actors still missing profile data after the `并火` pass

### Priority

`保木` candidates are processed in this order:

1. `沧浪阁` actors still missing any required field after `并火`
2. actor-library actors still missing any required field after `并火`

If the same actor appears in both queues, the `沧浪阁` priority wins.

### Retry Semantics

`保木` should follow the same retry model as other sources:

- `无搜索结果` is terminal for repeated search attempts
- `失败` is retryable
- `未补全` is pending
- `已补全` means the source has already contributed all fields it could extract for the current actor page

If `保木` has already stored a complete source profile for an actor, that actor should not be re-queued.

If `保木` has only stored a partial profile and still leaves required merged fields empty, the actor may be retried.

## Scraping Strategy

### Source URL

Open the actress page directly:

`https://netflav.com/all?actress=<actor_name>`

The actor name must be URL-encoded exactly as provided by the current candidate name.

Unlike `并火`, `保木` does not need a separate person-id search step for the initial implementation.

### Extracted Fields

Netflav actress pages currently expose the needed profile data both in the visible header block and in the embedded page-state JSON.

The scraper should extract when present:

- birthday
- height
- bust
- waist
- hip
- cup
- actress display name

Only the first five fields are required for enrichment persistence in this task.

`cup` and display name can be ignored for database persistence unless the parser naturally returns them as extra keys.

### Parsing Preference

Prefer parsing the embedded page-state JSON when available, because it is less sensitive to layout changes than visible text selectors.

Fallback to DOM text extraction only if the JSON block cannot be parsed.

### Normalization

Normalize values before persistence:

- birthday to `YYYY-MM-DD` when possible
- height to numeric centimeters without `cm`
- bust to numeric centimeters without `cm`
- waist to numeric centimeters without `cm`
- hip to numeric centimeters without `cm`

If a value is absent or unparseable, leave it empty rather than guessing.

For Netflav values such as `101cm (G)`, store:

- `bust = 101`

The cup letter should not be packed into the stored bust field.

## Database Model

Extend `actor_enrichments` with a `保木` field family parallel to `并火`:

- `baomu_enrichment_status TEXT DEFAULT ''`
- `baomu_last_error TEXT DEFAULT ''`
- `baomu_last_enriched_at TEXT`
- `baomu_birthday TEXT DEFAULT ''`
- `baomu_height TEXT DEFAULT ''`
- `baomu_bust TEXT DEFAULT ''`
- `baomu_waist TEXT DEFAULT ''`
- `baomu_hip TEXT DEFAULT ''`

No `baomu_person_id` field is required for this implementation because the source URL is name-based rather than id-based.

`actors` table schema does not need new columns for this task. The merged display can continue to derive final visible values from:

- `actors.birthday`
- existing source fields in `actor_enrichments`

If the current project already syncs source birthday/age into `actors`, that behavior may continue for `并火`. `保木` should not force a broader actor-table schema change unless implementation reveals an existing dependency.

## Write Rules

When a `保木` actress page is loaded successfully:

- save `baomu_enrichment_status = 已补全`
- save `baomu_last_error = ''`
- save `baomu_last_enriched_at = CURRENT_TIMESTAMP`
- save any extracted `baomu_*` fields that are present
- preserve previously stored `baomu_*` values when the new page lacks them

If the page resolves successfully but still does not provide every field:

- the run is still considered `已补全` for the source
- source-level missing values remain empty
- actor-level merged completeness is determined separately

If the actress page has no matching profile data for the requested actor:

- save `baomu_enrichment_status = 无搜索结果`
- save `baomu_last_error` with a clear message

If the run fails due to browser, network, or parser problems:

- save `baomu_enrichment_status = 失败`
- save `baomu_last_error`

## Runtime Integration

### New Source Key

Add a new enrichment source key constant for `保木`.

This source belongs only to `演员生日` for now.

### Router

Update the enrichment router so:

- `演员生日 + 并火` dispatches to `ActorBinghuoEnrichmentService`
- `演员生日 + 保木` dispatches to a new `ActorBaomuEnrichmentService`

### Dedicated Service

Create a dedicated `ActorBaomuEnrichmentService`.

Responsibilities:

- build the second-pass candidate queue
- open the Netflav actress page for each candidate
- parse actor profile fields
- persist `baomu_*` source state
- report progress with the same task-progress contract used by the existing enrichment services

This service should not reuse `ActorBinghuoEnrichmentService` directly because its candidate gate, source parser, and stored field family differ.

## Detail Merge Rules

The actor detail service should return merged visible values using this precedence:

- `birthday`: actor row, then `binghuo_birthday`, then `baomu_birthday`
- `height`: `binghuo_height`, then `baomu_height`
- `bust`: `binghuo_bust`, then `baomu_bust`
- `waist`: `binghuo_waist`, then `baomu_waist`
- `hip`: `binghuo_hip`, then `baomu_hip`

For this task, `并火` stays ahead of `保木` in fallback priority because the user described `保木` as the completion source used after `并火`.

The raw detail payload should additionally expose:

- `baomu_height`
- `baomu_bust`
- `baomu_waist`
- `baomu_hip`
- `baomu_birthday`
- `baomu_enrichment_status`

This keeps source-specific state inspectable without changing the visible layout too aggressively.

## Testing

Implementation should include tests for:

- enrichment dialog source availability for `演员生日`
- invalid saved `演员生日` source fallback behavior with the new `保木` option
- `保木` candidate gating:
  - skips actors never processed by `并火`
  - includes actors whose merged `actor-library + 并火` profile still lacks any required field
  - prioritizes `沧浪阁` before actor library
  - skips actors already fully completed by `保木`
- Netflav parser behavior:
  - parses embedded actress JSON
  - normalizes `1984-05-20`
  - normalizes `171cm` to `171`
  - normalizes `101cm (G)` to `101`
  - normalizes `63cm` to `63`
  - normalizes `93cm` to `93`
- `保木` source persistence for success, no-result, and failure
- detail merge behavior preferring `并火` first and `保木` second

### Verification Actor

Use `一松愛梨` as the reference actor for parser verification.

Expected Netflav values from the user-provided page at the time of inspection on June 27, 2026:

- birthday: `1984-05-20`
- height: `171`
- bust: `101`
- waist: `63`
- hip: `93`

## Summary

This feature turns `保木` into a second independent actor-profile source for the `演员生日` workflow. It keeps per-source data separate in storage, gates `保木` work to actors that remain incomplete after `并火`, and merges the stored fields back into one readable actor-detail view. The first production verification target is `一松愛梨` from the Netflav actress page.
