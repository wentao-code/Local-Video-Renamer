# Fouroursons Actor Birthday Enrichment Design

## Goal

Add a new enrichment workflow dedicated to actor profile data from Fouroursons (`并火`).

This workflow must:

- add a new enrichment target named `演员生日`
- use a single fixed source named `并火`
- hide the combo-task section when this target is selected
- enrich actor birthday and profile fields from Fouroursons actor pages
- store the Fouroursons person id so future runs can open the actor page directly
- permanently stop retrying actors that already produced a Fouroursons "no search result" outcome

The workflow is for actor-profile enrichment only. It does not enrich videos or code-prefix libraries.

## User Experience

### Enrichment Dialog

Add a fourth target option in the enrichment dialog:

- `视频库`
- `番号库`
- `演员库`
- `演员生日`

When `演员生日` is selected:

- the source section shows only one radio option: `并火`
- the combo-task group is hidden
- the combo-task action buttons are hidden
- the regular actions remain available:
  - `开始补全`
  - `分批补全`
  - `保存配置`
- the common controls remain available and behave the same as other targets:
  - `本次补全数量`
  - `每批补全数量`
  - `批次间隔`
  - `显示浏览器窗口`

The cooldown option is not needed for Fouroursons and should be hidden or disabled for this target/source pair.

### Behavior Summary

The actor birthday target behaves like a normal single-source library enrichment task, except:

- it has no combo mode
- it always uses Fouroursons
- it builds candidates from actor priority queues instead of video/code queues

## Candidate Priority

Candidate actors are selected in three priority tiers, in this exact order:

1. actors appearing in `沧浪阁` whose `birthday` is empty
2. actors in the actor library whose `birthday` is empty
3. actors in the actor library whose `birthday` is already filled but who do not yet have a Fouroursons id

Rules:

- candidates are deduplicated by actor name across all three tiers
- higher priority wins if an actor appears in multiple tiers
- actors already marked as Fouroursons `no search result` must be skipped entirely
- actors with a stored Fouroursons id can still be revisited if birthday/height/measurements are incomplete, but they should open the saved page directly instead of using search

This means:

- `无生日` actors are always processed before `仅缺并火 id` actors
- `无搜索结果` is terminal for Fouroursons search and blocks future search retries

## Search And Matching

### Search URL

Search URL template:

`https://www.fouroursonsinc.com/search.php?f=_all&s=relevance&q=<actor_name>`

The query text is the actor name currently being processed.

### Search Result Handling

Search uses strict exact-match logic.

Rules:

- only exact actor-name matches are considered valid candidates
- if there are no exact matches, the actor is recorded as Fouroursons `no search result`
- if there are multiple exact matches, open the first exact match

No fuzzy fallback should be used.

### Direct Open Optimization

If the actor enrichment record already contains a Fouroursons person id, skip search and open:

`https://www.fouroursonsinc.com/person/<fouroursons_person_id>`

This avoids repeated search and makes later profile completion runs cheaper and more stable.

## Scraped Fields

From the Fouroursons actor page, extract when present:

- Fouroursons person id
- birthday
- age
- height
- bust
- waist
- hip

Page fields may be absent. Missing values must remain empty and must not be fabricated.

The person id is derived from the URL path, for example:

`https://www.fouroursonsinc.com/person/5921`

stores:

- `fouroursons_person_id = "5921"`

## Database Model

### Actors Table

Extend `actors` with profile fields:

- `height TEXT DEFAULT ''`
- `bust TEXT DEFAULT ''`
- `waist TEXT DEFAULT ''`
- `hip TEXT DEFAULT ''`

Birthday and age already exist and continue to be stored in `actors`.

### Actor Enrichments Table

Extend `actor_enrichments` with Fouroursons source fields:

- `fouroursons_person_id TEXT DEFAULT ''`
- `fouroursons_enrichment_status TEXT DEFAULT ''`
- `fouroursons_last_error TEXT DEFAULT ''`
- `fouroursons_last_enriched_at TEXT`

These fields are independent from the existing AVFan and JAVTXT actor-source fields.

### Status Semantics

Fouroursons status should follow the existing library status pattern:

- `未补全`
- `已补全`
- `失败`
- `无搜索结果`

Important behavior:

- `无搜索结果` is terminal and blocks future Fouroursons search retries
- `失败` is retryable
- `已补全` means a Fouroursons run completed successfully, even if some optional fields were absent on the page

## Write Rules

When a Fouroursons actor page is opened successfully:

- save `fouroursons_person_id`
- save `fouroursons_enrichment_status = 已补全`
- save `fouroursons_last_error = ''`
- save `fouroursons_last_enriched_at = CURRENT_TIMESTAMP`

Then merge page fields into `actors`:

- if page has `birthday`, write it
- if page has `age`, write it
- if page has `height`, write it
- if page has `bust`, write it
- if page has `waist`, write it
- if page has `hip`, write it

If a page field is absent, leave the current database value unchanged.

If search returns no exact match:

- save `fouroursons_enrichment_status = 无搜索结果`
- save `fouroursons_last_error` with a clear no-result message
- do not save a Fouroursons id

If a run fails due to network/browser/parser errors:

- save `fouroursons_enrichment_status = 失败`
- save `fouroursons_last_error`
- keep any previously saved Fouroursons id

## Runtime Integration

### New Target And Source

Add:

- new target type constant for actor birthday enrichment
- new source key constant for Fouroursons

The backend enrichment router should dispatch this target to a dedicated Fouroursons actor-profile enrichment service.

### Dedicated Service

Create a dedicated actor-profile enrichment service for Fouroursons.

Responsibilities:

- build prioritized candidate actor queue
- decide whether to search or direct-open by saved person id
- scrape actor profile fields
- persist profile fields and Fouroursons source status
- report progress using the same task-progress structure as other enrichment tasks

This service should not reuse AVFan actor-movie enrichment semantics because its output is actor profile data, not movie lists.

## Progress And Batch Behavior

The target should support:

- single-run mode
- batch mode

Progress reporting should stay consistent with the existing enrichment UI:

- processed count
- success count
- failed count
- remaining count
- current item

Count unit for this target should be `演员`.

## Error Handling

The workflow must handle:

- no exact search result
- multiple exact results
- missing optional fields on the actor page
- browser/network failures
- human verification or site access failures if encountered

Expected behavior:

- no-result is terminal and not retried
- parse/network failures are marked failed and can be retried later
- missing page fields do not make the run fail

## Testing

Implementation should include tests for:

- enrichment dialog target/source visibility and combo hiding for `演员生日`
- candidate priority order:
  - `沧浪阁无生日` first
  - then actor library `无生日`
  - then actor library `有生日但无并火 id`
- deduplication across tiers
- no-result actors being excluded from future Fouroursons candidate selection
- direct-open behavior when Fouroursons id already exists
- exact-match search behavior
- multiple exact matches opening the first one
- page-field merge behavior:
  - writes present values
  - leaves absent values unchanged
- status persistence for success, failure, and no-result

## Summary

This feature adds a dedicated `演员生日 / 并火` enrichment workflow that focuses on actor profile data rather than movies. It introduces a Fouroursons-specific candidate queue, exact-match search, direct-open by stored id, terminal no-result handling, and database support for birthday/body-profile fields plus Fouroursons source state.
