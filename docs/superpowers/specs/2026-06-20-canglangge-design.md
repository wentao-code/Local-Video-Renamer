# Canglangge Candidate Library Design

Date: 2026-06-20

## Goal

Add a new desktop entry named `沧浪阁` on the home screen. It opens a dedicated candidate-management window that lists actors who:

- appear in videos under `S` tier code prefixes
- have a usable release date
- have release date `>= 2020-01-01`
- are not already in the actor library
- are not already in the hidden-actor blacklist

The window lets the user either:

- admit candidates into the actor library
- delete candidates into the hidden blacklist so they never reappear

## Non-Goals

- building the future dedicated enrichment program for birthday/age completion
- changing the ladder tier model
- changing the actor-library schema beyond reusing existing actor and hidden-actor tables
- mixing candidate rows directly into the actor library UI
- adding web scraping or new external data sources

## Constraints

- Candidate detection must reuse the current desktop database and local backend.
- Candidate eligibility must not depend on the current video filter rules anymore.
- Blacklist behavior must reuse the existing `hidden_actors` semantics so deleted candidates and deleted actor-library rows behave consistently.
- Birthday and age fields must remain blank when admitted from `沧浪阁`.

## Recommended Approach

Implement `沧浪阁` as an independent candidate workflow with three focused layers:

1. a backend candidate service that computes the candidate list from existing local and indexed data
2. backend operations for admit/delete actions against the existing actor tables
3. a dedicated PyQt window for browsing and acting on candidates

This keeps candidate logic isolated from the actor library while still reusing actor add/delete behaviors already present in the system.

## Candidate Rule

`沧浪阁` candidates are derived from local videos only.

Source videos must satisfy all of the following:

1. the video's code prefix belongs to the code-prefix ladder with tier `S`
2. the video has a usable release date
3. the usable release date is `>= 2020-01-01`
4. the video author text can be split into actor names

Candidate actor names are then filtered:

- remove ignored/empty actor names using the existing actor-name normalization rules
- remove names already present in the actor library
- remove names already present in `hidden_actors`

Each remaining actor becomes one candidate row.

## Candidate Aggregation

Each row represents one actor candidate, not one video.

The row aggregates all matching source videos:

- `actor_name`: normalized actor name
- `codes`: all matching video codes, de-duplicated and ordered
- `prefixes`: all source `S`-tier prefixes, de-duplicated and ordered
- `birthday`: empty string
- `age`: empty string

Display behavior:

- the `番号` column shows all related video codes for the actor
- the `来自哪个番号` column shows all related `S`-tier prefixes
- if the same actor appears under multiple `S`-tier prefixes, all of them are shown in the same row

## Architecture

### 1. Backend candidate service

Add a focused service, for example `CanglanggeCandidateService`, responsible for building the candidate list.

Responsibilities:

- load `S`-tier code prefixes from ladder entries
- load local videos for those prefixes using targeted prefix queries when available
- filter source videos by release-date eligibility
- split actor names from author text
- exclude names already in actors or hidden actors
- aggregate rows by actor

This service should be read-only and return already-shaped row dictionaries for the UI.

### 2. Backend endpoints

Add dedicated endpoints for:

- listing `沧浪阁` candidates
- admitting one or more candidates into the actor library
- deleting one or more candidates into `hidden_actors`

Admit behavior should reuse the actor add path rather than duplicate actor validation rules.

Delete behavior should reuse hidden-actor insertion semantics so a deleted candidate stays hidden permanently.

### 3. Desktop viewer window

Add a new dialog window similar in style to the existing library viewers.

Responsibilities:

- load and render candidate rows
- support row selection
- provide per-row and batch actions
- refresh after admit/delete actions

The window should not embed candidate-building logic itself; it should only render backend responses.

## UI Design

### Home entry

Add a new button `沧浪阁` on the main window alongside existing library buttons.

Click behavior:

- open the new `沧浪阁` viewer dialog

### Candidate viewer columns

Recommended columns:

1. 演员
2. 番号
3. 来自哪个番号
4. 生日
5. 年龄
6. 操作

Birthday and age render empty for all rows in this phase.

### Actions

Each row gets:

- `入选`
- `删除`

The window should also support multi-row selection and top-level batch buttons:

- `批量入选`
- `批量删除`
- `刷新数据`

This keeps single-row actions convenient while avoiding repetitive clicks for large candidate lists.

## Data Flow

### Load flow

1. user opens `沧浪阁`
2. viewer requests candidate rows from backend
3. backend candidate service gathers `S`-tier prefixes
4. backend loads local videos for those prefixes
5. backend filters videos by usable release date `>= 2020-01-01`
6. backend splits actor names and removes actor-library and blacklist matches
7. backend aggregates candidate rows by actor
8. viewer renders the resulting table

### Admit flow

1. user clicks `入选` or `批量入选`
2. viewer sends actor names to backend
3. backend adds actors with empty birthday/age fields
4. backend returns success payload
5. viewer refreshes candidates so admitted rows disappear

### Delete flow

1. user clicks `删除` or `批量删除`
2. viewer sends actor names to backend
3. backend inserts names into `hidden_actors`
4. backend returns success payload
5. viewer refreshes candidates so deleted rows disappear permanently

## Error Handling

- No candidates: show an empty-state message rather than an error.
- Candidate admit conflicts:
  if an actor was added elsewhere just before admit, backend validation should reject duplicate insertion cleanly and the next refresh should remove that row from candidates.
- Candidate delete duplicates:
  inserting an already-hidden actor should be harmless via `INSERT OR IGNORE`.
- Missing or malformed release date:
  skip that source video entirely.
- Empty or ignored actor tokens:
  skip them during candidate extraction.

## Testing Strategy

Add focused tests for:

1. candidate service only includes actors from `S`-tier prefixes
2. candidate service excludes videos with missing or invalid release dates
3. candidate service excludes videos with release dates before `2020-01-01`
4. candidate service excludes actors already in `actors`
5. candidate service excludes actors already in `hidden_actors`
6. candidate service aggregates multiple codes/prefixes into a single actor row
7. admit action inserts actor rows with empty birthday/age
8. delete action inserts actor names into `hidden_actors`
9. viewer opens and renders candidate rows correctly
10. viewer admit/delete actions refresh away affected rows

## Implementation Order

1. add backend candidate service and tests
2. add backend endpoints and client methods
3. add the `沧浪阁` viewer dialog and tests
4. add the main-window button and open-flow wiring
5. add i18n strings and success/error messaging

## Risks

- Candidate generation may become slow if it scans the entire local video table instead of using targeted `S`-prefix queries.
- Author text may contain noisy tokens; correctness depends on the existing actor-name split/ignore rules.
- Batch actions need careful refresh behavior so partially successful operations do not leave the UI stale.

## Decision Summary

`沧浪阁` will be a dedicated candidate library for actor discovery from `S`-tier recent videos. It will reuse the existing ladder, actor normalization, actor library, and hidden blacklist mechanisms, while keeping candidate computation and candidate UI isolated from the main actor library.
