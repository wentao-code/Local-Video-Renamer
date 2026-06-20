# Fouroursons Actor Birthday Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `演员生日 / 并火` enrichment workflow that fills actor birthday/profile fields and stores Fouroursons source state and person ids.

**Architecture:** Extend the enrichment dialog and backend router with a new target/source pair, add Fouroursons-specific actor enrichment state in the database, then implement a dedicated actor-profile enrichment service plus scraper that builds prioritized candidate queues and writes profile fields into the actor library. Keep this workflow separate from AVFan/JAVTXT actor-movie enrichment.

**Tech Stack:** Python, PyQt5, sqlite3, requests/Playwright-style existing scraper patterns, unittest/pytest

---

### File Structure

**Create:**
- `app/scraper/fouroursons_actor_scraper.py`
- `app/services/enrichment/actor_fouroursons_enrichment.py`
- `tests/test_fouroursons_actor_enrichment.py`
- `tests/test_enrichment_dialog_actor_birthday.py`

**Modify:**
- `app/core/enrichment_targets.py`
- `app/core/enrichment_sources.py`
- `app/gui/enrichment_dialog.py`
- `app/gui/i18n.py`
- `app/gui/i18n_patch.py`
- `app/services/enrichment/__init__.py`
- `app/services/enrichment/library_enrichment_service.py`
- `app/backend/client.py`
- `app/backend/service.py`
- `app/backend/server.py`
- `app/data/database_handler.py`
- `app/services/library/canglangge_candidate_service.py`

---

### Task 1: Add Fouroursons Target/Source And Dialog Behavior

**Files:**
- Modify: `app/core/enrichment_targets.py`
- Modify: `app/core/enrichment_sources.py`
- Modify: `app/gui/enrichment_dialog.py`
- Modify: `app/gui/i18n.py`
- Modify: `app/gui/i18n_patch.py`
- Test: `tests/test_enrichment_dialog_actor_birthday.py`

- [ ] **Step 1: Write the failing dialog tests**

Add tests that assert:

- `演员生日` target exists
- selecting it forces source to `并火`
- combo group/buttons are hidden
- normal single/batch controls remain visible

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- import failure or missing target/source/dialog behavior

- [ ] **Step 3: Add the new target/source constants and dialog logic**

Implement:

- new target constant such as `ACTOR_BIRTHDAY_TARGET = 'actor_birthday'`
- new source key such as `FOUROURSONS_SOURCE = 'fouroursons'`
- dialog radio for `演员生日`
- source group restricted to `并火`
- combo group hidden when `演员生日` is selected
- combo action buttons hidden when `演员生日` is selected
- cooldown hidden or disabled for the Fouroursons target/source

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- PASS

---

### Task 2: Extend Actor Schema And Persistence For Fouroursons

**Files:**
- Modify: `app/data/database_handler.py`
- Test: `tests/test_fouroursons_actor_enrichment.py`

- [ ] **Step 1: Write the failing persistence tests**

Add tests that assert:

- `actors` supports `height`, `bust`, `waist`, `hip`
- `actor_enrichments` supports `fouroursons_person_id`, `fouroursons_enrichment_status`, `fouroursons_last_error`, `fouroursons_last_enriched_at`
- saving Fouroursons enrichment updates only Fouroursons columns
- absent scraped fields do not overwrite existing actor values

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py -q
```

Expected:

- missing columns or missing persistence helpers

- [ ] **Step 3: Implement minimal schema and persistence helpers**

Add migrations/helpers in `VideoDatabase` for:

- ensuring actor profile columns exist
- reading actor enrichment records with Fouroursons fields
- saving Fouroursons actor enrichment state
- updating actor profile fields with “present values only”

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py -q
```

Expected:

- PASS

---

### Task 3: Add Fouroursons Scraper And Candidate Queue Logic

**Files:**
- Create: `app/scraper/fouroursons_actor_scraper.py`
- Create: `app/services/enrichment/actor_fouroursons_enrichment.py`
- Modify: `app/services/library/canglangge_candidate_service.py`
- Test: `tests/test_fouroursons_actor_enrichment.py`

- [ ] **Step 1: Extend the failing enrichment tests**

Add tests for:

- priority order:
  - `沧浪阁无生日`
  - actor library `无生日`
  - actor library `有生日但无并火 id`
- deduplication across tiers
- `无搜索结果` actors excluded from future runs
- direct-open by saved person id
- no-result on zero exact matches
- first result used when multiple exact matches exist

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py -q
```

Expected:

- missing scraper/service/candidate-selection behavior

- [ ] **Step 3: Implement the scraper**

Implement a focused scraper with methods to:

- open search results for an actor name
- collect exact-match result links
- open the first exact match when one or more exist
- open a saved `/person/<id>` page directly
- parse page fields for birthday, age, height, bust, waist, hip
- extract the person id from the final page URL

- [ ] **Step 4: Implement the Fouroursons actor enrichment service**

Implement a dedicated service that:

- builds prioritized actor candidates
- skips actors with terminal Fouroursons no-result state
- uses saved Fouroursons id for direct-open when present
- otherwise searches and applies strict exact-match logic
- writes success/failure/no-result state
- updates actor profile fields without blanking existing values

- [ ] **Step 5: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py -q
```

Expected:

- PASS

---

### Task 4: Wire The New Target Into Enrichment Routing

**Files:**
- Modify: `app/services/enrichment/__init__.py`
- Modify: `app/services/enrichment/library_enrichment_service.py`
- Modify: `app/backend/client.py`
- Modify: `app/backend/service.py`
- Modify: `app/backend/server.py`
- Test: `tests/test_fouroursons_actor_enrichment.py`
- Test: `tests/test_enrichment_dialog_actor_birthday.py`

- [ ] **Step 1: Add backend-facing failing tests**

Add tests that assert:

- the backend accepts the new target/source
- routing selects the Fouroursons actor enrichment service
- batch/single dialog values remain valid for the new target

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- missing routing or invalid target/source handling

- [ ] **Step 3: Implement routing**

Wire the new target/source through:

- enrichment target/source constants
- library enrichment router
- backend single-task dispatch
- client payload compatibility

The Fouroursons target should support single and batch execution, but never combo execution.

- [ ] **Step 4: Re-run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- PASS

---

### Task 5: Run Regression Verification

**Files:**
- Test only

- [ ] **Step 1: Run the new focused suites**

Run:

```bash
python -m pytest tests/test_fouroursons_actor_enrichment.py tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- all pass

- [ ] **Step 2: Run the broader regression command**

Run:

```bash
python -m pytest tests/test_actor_profile_update_service.py tests/test_library_inline_add_viewers.py tests/test_canglangge_candidate_service.py tests/test_canglangge_viewer.py tests/test_backend_reuse.py tests/test_fouroursons_actor_enrichment.py tests/test_enrichment_dialog_actor_birthday.py -q
```

Expected:

- all pass

---

### Self-Review

**Spec coverage:** The plan covers the new enrichment target/source, combo hiding, candidate priority, exact-match search, first-match behavior for multiple exact results, direct-open by saved id, terminal no-result handling, actor profile persistence, Fouroursons source-state persistence, and single/batch routing.

**Placeholder scan:** No `TODO`, `TBD`, or vague “handle later” steps remain. Each task names files, test focus, and verification commands.

**Type consistency:** The plan consistently uses `ACTOR_BIRTHDAY_TARGET`, `FOUROURSONS_SOURCE`, `fouroursons_person_id`, `fouroursons_enrichment_status`, `fouroursons_last_error`, and `fouroursons_last_enriched_at` as the core target/source/state names.
