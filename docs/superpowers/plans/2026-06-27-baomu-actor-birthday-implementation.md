# Baomu Actor Birthday Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second `演员生日` source named `保木` that fills profile gaps left after `并火`, stores source-specific fields independently, and merges them into actor detail display.

**Architecture:** Extend the existing actor birthday enrichment target so it can dispatch either the current `并火` flow or a new `保木` flow. Persist `保木` status and profile fields alongside `并火` in `actor_enrichments`, parse Netflav actress pages into normalized values, gate `保木` candidates to actors still missing birthday/height/measurements after `并火`, and merge source values back into actor detail payloads with `并火` taking precedence over `保木`.

**Tech Stack:** Python, PyQt5, sqlite3, Playwright-compatible scraper patterns, unittest/pytest

---

### Task 1: Add Failing UI And Routing Tests

**Files:**
- Modify: `tests/test_enrichment_dialog_actor_birthday.py`
- Modify: `tests/test_actor_binghuo_enrichment_service.py`
- Create: `tests/test_baomu_actor_scraper.py`
- Create: `tests/test_baomu_actor_enrichment_service.py`
- Modify: `tests/test_actor_profile_display.py`

- [ ] **Step 1: Write the failing dialog tests**

Add tests asserting that `演员生日` now allows both `并火` and `保木`, preserves hidden combo controls, and falls back invalid saved actor-birthday source values to a valid actor-birthday source.

- [ ] **Step 2: Write the failing parser tests**

Add `tests/test_baomu_actor_scraper.py` cases that parse embedded Netflav actress JSON for `一松愛梨` and normalize:

- `1984-05-20` to `1984-05-20`
- `171cm` to `171`
- `101cm (G)` to `101`
- `63cm` to `63`
- `93cm` to `93`

- [ ] **Step 3: Write the failing enrichment-service tests**

Add `tests/test_baomu_actor_enrichment_service.py` cases covering:

- skip actors never attempted by `并火`
- include actors whose merged actor-library + `并火` profile still lacks birthday/height/measurements
- prioritize `沧浪阁` before actor library
- skip actors fully completed by `保木`
- persist `保木` success, failure, and no-result states

- [ ] **Step 4: Write the failing detail-merge tests**

Extend `tests/test_actor_profile_display.py` so actor detail prefers `并火` fields first and `保木` second when visible values are missing.

- [ ] **Step 5: Run focused tests to verify they fail**

Run:

```bash
python -m pytest tests/test_enrichment_dialog_actor_birthday.py tests/test_baomu_actor_scraper.py tests/test_baomu_actor_enrichment_service.py tests/test_actor_profile_display.py -q
```

Expected:

- FAIL due to missing `保木` source constants, parser, persistence, service, and merge logic.

### Task 2: Implement Source Constants, Dialog Support, And Persistence

**Files:**
- Modify: `app/core/enrichment_sources.py`
- Modify: `app/gui/enrichment_dialog.py`
- Modify: `app/gui/i18n_patch.py`
- Modify: `app/data/database_handler.py`
- Modify: `tests/test_binghuo_actor_profile_storage.py`

- [ ] **Step 1: Add the new source constant and label**

Implement `BAOMU_ACTOR_SOURCE = 'baomu'` and include it in normalization/labels for actor-birthday-capable sources.

- [ ] **Step 2: Extend dialog source handling**

Allow `演员生日` to choose `并火` or `保木`, keep combo controls hidden, and ensure saved settings load/store correctly for both source keys.

- [ ] **Step 3: Extend actor enrichment persistence**

Add `baomu_*` columns to `actor_enrichments`, include them in read helpers, and add a dedicated save helper analogous to `save_binghuo_actor_profile` but without requiring a person id.

- [ ] **Step 4: Re-run focused tests for persistence and dialog**

Run:

```bash
python -m pytest tests/test_enrichment_dialog_actor_birthday.py tests/test_binghuo_actor_profile_storage.py tests/test_actor_profile_display.py -q
```

Expected:

- dialog tests improve
- persistence tests still fail on missing scraper/service logic until later tasks

### Task 3: Implement Netflav Parser And 保木 Enrichment Service

**Files:**
- Create: `app/scraper/baomu_actor_scraper.py`
- Create: `app/services/enrichment/actor_baomu_enrichment.py`
- Modify: `app/services/enrichment/__init__.py`
- Modify: `app/services/library/canglangge_candidate_service.py`

- [ ] **Step 1: Implement the scraper**

Create a focused scraper that:

- opens `https://netflav.com/all?actress=<actor_name>`
- extracts the `__NEXT_DATA__` payload
- reads `props.pageProps.actress`
- normalizes birthday, height, bust, waist, and hip

- [ ] **Step 2: Implement candidate gating**

Build a candidate queue from `沧浪阁` and actor library that only includes actors already attempted by `并火` and still missing any required field after merged actor-library + `并火` evaluation.

- [ ] **Step 3: Implement the 保木 enrichment service**

Persist `baomu_*` source status and fields, mark no-result terminal, keep failures retryable, and report progress with the existing tracker contract.

- [ ] **Step 4: Re-run focused scraper/service tests**

Run:

```bash
python -m pytest tests/test_baomu_actor_scraper.py tests/test_baomu_actor_enrichment_service.py -q
```

Expected:

- PASS

### Task 4: Wire Routing And Detail Merge

**Files:**
- Modify: `app/services/enrichment/library_enrichment_service.py`
- Modify: `app/services/detail/actor_detail_library.py`
- Modify: `app/gui/actor_detail_viewer.py`
- Modify: `tests/test_actor_detail_viewer.py`
- Modify: `tests/test_actor_profile_display.py`

- [ ] **Step 1: Route `演员生日 + 保木` to the new service**

Update the enrichment router so `演员生日` dispatches to `ActorBinghuoEnrichmentService` for `并火` and `ActorBaomuEnrichmentService` for `保木`.

- [ ] **Step 2: Merge source values in actor detail**

Expose visible detail values using:

- birthday: actor row, then `binghuo_birthday`, then `baomu_birthday`
- height/measurements: `binghuo_*`, then `baomu_*`

Also expose raw `baomu_*` fields in the detail payload.

- [ ] **Step 3: Re-run focused routing/detail tests**

Run:

```bash
python -m pytest tests/test_actor_profile_display.py tests/test_actor_detail_viewer.py tests/test_enrichment_dialog_actor_birthday.py tests/test_baomu_actor_enrichment_service.py -q
```

Expected:

- PASS

### Task 5: Regression Verification

**Files:**
- Test only

- [ ] **Step 1: Run the new focused suites**

Run:

```bash
python -m pytest tests/test_baomu_actor_scraper.py tests/test_baomu_actor_enrichment_service.py tests/test_enrichment_dialog_actor_birthday.py tests/test_actor_profile_display.py tests/test_actor_detail_viewer.py -q
```

Expected:

- all pass

- [ ] **Step 2: Run broader regression coverage**

Run:

```bash
python -m pytest tests/test_actor_binghuo_enrichment_service.py tests/test_binghuo_actor_profile_storage.py tests/test_canglangge_candidate_service.py tests/test_data_center_summary.py tests/test_enrichment_dialog_actor_birthday.py tests/test_actor_profile_display.py tests/test_actor_detail_viewer.py tests/test_baomu_actor_scraper.py tests/test_baomu_actor_enrichment_service.py -q
```

Expected:

- all pass

### Self-Review

**Spec coverage:** The plan covers new `保木` source visibility, independent persistence fields, Netflav parsing, candidate gating after `并火`, source-specific status semantics, router integration, and actor-detail merge precedence.

**Placeholder scan:** No `TODO`, `TBD`, or vague deferred implementation steps remain.

**Type consistency:** The plan consistently uses `BAOMU_ACTOR_SOURCE`, `ActorBaomuEnrichmentService`, `baomu_enrichment_status`, `baomu_last_error`, `baomu_last_enriched_at`, `baomu_birthday`, `baomu_height`, `baomu_bust`, `baomu_waist`, and `baomu_hip`.
