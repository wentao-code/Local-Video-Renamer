# RuleSet and SQLite Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** 将固定视频筛选规则统一封装为 `RuleSet`，并把可表达的基础筛选下推到 SQLite，减少大表数据进入 Python。

**Architecture:** `RuleSet` 负责规则标准化、指纹、SQL 条件编译和残余 Python 判断。数据库查询方法接收可选 `RuleSet`，先用 SQL 过滤，再把结果交给同一个 `RuleSet` 做残余校验；未传规则时保持现有未过滤查询兼容。数据中心和补全候选显式传入对应规则集。

**Tech Stack:** Python 3、SQLite、PyQt5、unittest/pytest。

## Global Constraints

- 保留现有 `VideoFilterService`、数据库方法和测试的兼容调用方式。
- 不把 VR、番号标准化和演员拆分等无法安全表达的规则强行转换为 SQL。
- SQL 只做安全的候选排除，残余 Python 判断继续作为最终语义校验。
- 不引入 NumPy、Numba、C++ 或新的运行时依赖。
- 不修改或重置工作区中已有的用户修改。

---

### Task 1: RuleSet 契约与 SQL 编译测试

**Files:**
- Modify: `code/tests/test_video_filter_service.py`
- Create: `code/tests/test_ruleset_sql_filtering.py`

**Interfaces:**
- `RuleSet.normalize(settings, scope='library') -> RuleSet`
- `RuleSet.compile_sql(table_alias='', scope=None) -> (where_sql, parameters)`
- `RuleSet.apply_residual(rows, scope=None) -> list[dict]`
- `RuleSet.fingerprint() -> str`

- [ ] **Step 1: Write failing tests**

覆盖以下行为：规则去重和指纹稳定；标题/标签普通关键字编译为带参数的 SQL；SQL 使用表别名；SQL 不直接编译 VR 和复杂残余规则；`apply_residual` 保持现有过滤语义；空规则不改变结果。

- [ ] **Step 2: Run the focused tests and confirm expected failure**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_ruleset_sql_filtering.py -q`

Expected: `ImportError` or `AttributeError` because `RuleSet` does not yet exist.

### Task 2: Implement RuleSet and VideoFilterService adapter

**Files:**
- Modify: `code/app/core/video_filter_rules.py`
- Modify: `code/app/services/video/video_filter_service.py`
- Modify: `code/app/services/video/__init__.py` if public export is required
- Test: `code/tests/test_ruleset_sql_filtering.py`

**Interfaces:**
- Preserve `normalize_video_filter_settings`, `should_hide_video_from_library`, and existing function behavior.
- Add `RuleSet` as the single normalized rule object.
- `VideoFilterService.load_ruleset(settings=None, scope='library')` returns the normalized object.
- `filter_library_rows` and `build_pre_enrichment_filter` delegate to `RuleSet`.

- [ ] **Step 1: Add the smallest RuleSet implementation**

Implement immutable normalized rule tuples, stable JSON fingerprinting, SQL literal escaping for `LIKE`, safe code-prefix SQL compilation, and residual calls to the existing matching functions.

- [ ] **Step 2: Run the RuleSet tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_ruleset_sql_filtering.py tests/test_video_filter_service.py -q`

Expected: all focused tests pass.

### Task 3: Database SQL pushdown and indexes

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/tests/test_ruleset_sql_filtering.py`
- Modify: `code/tests/test_list_query_optimizations.py`

**Interfaces:**
- Add optional `rule_set=None` to `list_video_summary_rows`, `list_all_actor_movies`, `list_actor_movies_by_names`, and `list_code_prefix_movies_by_prefixes`.
- Keep existing calls without `rule_set` unchanged.
- Add SQL predicates before `fetchall`, then apply residual filtering to returned rows.

- [ ] **Step 1: Add failing database tests**

Use a temporary SQLite database with matching and nonmatching rows. Assert the result is correct and a supplied `RuleSet` causes the query to include SQL filtering before Python residual handling.

- [ ] **Step 2: Run database tests and confirm failure**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_ruleset_sql_filtering.py tests/test_list_query_optimizations.py -q`

- [ ] **Step 3: Add query helpers and indexes**

Add helpers to combine an existing `WHERE` clause with the RuleSet SQL fragment, escape parameters, and add/verify indexes for processed video status/release, actor movie actor/release/status, and code-prefix movie prefix/release/status.

- [ ] **Step 4: Run focused database tests**

Run the same command and verify all pass.

### Task 4: Wire data center and enrichment candidate reads

**Files:**
- Modify: `code/app/services/library/data_center_service.py`
- Modify: `code/app/backend/service.py`
- Modify: `code/app/data/database_handler.py` if candidate query signatures need the RuleSet
- Modify: relevant tests under `code/tests/`

**Interfaces:**
- Data center summary/analysis reads use one library `RuleSet` for SQL-first reads.
- Video enrichment candidate reads use a pre-enrichment `RuleSet` where applicable.
- Existing snapshot fingerprints continue to include normalized filter settings.

- [ ] **Step 1: Add regression tests for SQL-first data-center reads**

Assert that data-center calls pass a RuleSet to the database and that candidate planning does not fall back to loading the full actor/code-prefix movie table when SQL filtering is available.

- [ ] **Step 2: Wire the RuleSet into data-center and candidate paths**

Use the database query methods with `rule_set`; retain residual filtering for compatibility and complex rules.

- [ ] **Step 3: Run data-center and enrichment tests**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest tests/test_data_center_summary.py tests/test_data_center_analysis_viewer.py tests/test_data_center_dashboard.py tests/test_enrichment_plan_candidates.py tests/test_video_filter_service.py -q`

### Task 5: Full verification

**Files:**
- Verify all modified files and tests.

- [ ] **Step 1: Run syntax checks**

Compile all modified Python files with UTF-8-SIG handling.

- [ ] **Step 2: Run full regression**

Run: `D:\Anaconda3Data\envs_dirs\video_env\python.exe -m pytest -q`

- [ ] **Step 3: Check the diff**

Run: `git diff --check` and inspect `git diff --stat`.
