# 排除网页影片缓存表实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将黑名单和筛选器排除的网页影片移入独立缓存表，只参与已抓取去重，不再进入界面、候选和补全链路。

**Architecture:** 在现有 SQLite 数据库中新增 `excluded_code_prefix_movies` 和 `excluded_actor_movies` 两张镜像表。抓取写入时按黑名单和筛选规则分流；所有去重查询批量联合活动表与排除表；历史数据通过可重复执行的后台批量迁移移动。`processed_videos` 保持不变。

**Tech Stack:** Python 3、SQLite WAL、现有 `VideoDatabase`、pytest/unittest。

## Global Constraints

- 排除记录只用于已抓取去重，不进入补全任务。
- 不迁移 `processed_videos`。
- 分流、迁移、恢复和删除使用同一数据库事务。
- 不引入 MySQL、ORM 或新的运行时依赖。
- 所有批量去重必须使用集合查询，不能增加逐条 SQL 查询。

---

### Task 1: 建立排除缓存表和基础读写接口

**Files:**
- Modify: `code/app/data/database_handler.py`
- Test: `code/tests/test_excluded_web_movie_cache.py`

**Produces:**
- `excluded_code_prefix_movies` 和 `excluded_actor_movies` 表。
- `_is_code_prefix_movie_excluded(prefix, code)`、`_is_actor_movie_excluded(actor_name, code)`。
- `list_excluded_code_prefix_movie_keys(prefixes, codes)` 和 `list_excluded_actor_movie_keys(actor_names, codes)` 批量接口。
- 活动表与排除表的镜像序列化、插入和唯一约束。

- [ ] 写失败测试：初始化创建两张表、排除记录按业务主键去重、批量 key 查询返回正确集合。
- [ ] 运行 `pytest tests/test_excluded_web_movie_cache.py -q`，确认因接口缺失或表不存在失败。
- [ ] 实现表结构、索引和批量查询。
- [ ] 运行测试确认通过。

### Task 2: 将新抓取网页影片分流到活动表或排除表

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/services/enrichment/code_prefix_enrichment.py`
- Modify: `code/app/services/enrichment/code_prefix_javtxt_enrichment.py`
- Modify: `code/app/services/enrichment/actor_enrichment.py`
- Modify: `code/app/services/enrichment/actor_javtxt_enrichment.py`
- Test: `code/tests/test_excluded_web_movie_cache.py`

**Consumes:** Task 1 的表和批量 key 接口。

**Produces:** `replace_code_prefix_movies`、`replace_actor_movies` 在同一事务内按排除规则分流；排除记录不会进入活动表。

- [ ] 写失败测试：番号/演员黑名单和筛选规则命中的新记录进入排除表，未命中的记录进入活动表。
- [ ] 写失败测试：活动表替换不会删除已有排除表记录。
- [ ] 运行新增测试确认失败。
- [ ] 修改两个 replace 方法，复用现有字段标准化和状态合并逻辑后分流写入。
- [ ] 确认源实体状态仍会保存，但排除影片不创建或更新补全状态。
- [ ] 运行相关 enrichment 测试和新增测试确认通过。

### Task 3: 修改抓取去重、候选和补全边界

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/services/enrichment/*.py`（仅实际调用点）
- Modify: `code/app/backend/service.py`
- Test: `code/tests/test_excluded_web_movie_cache.py`
- Test: 相关候选和补全测试文件

**Produces:** 活动表与排除表联合去重；排除表不进入任何候选、补全计划或补全执行结果。

- [ ] 写失败测试：已存在于排除表的番号/演员影片不会再次生成抓取候选。
- [ ] 写失败测试：排除记录不会被 `list_plan_candidate_items`、候选库或补全计划返回。
- [ ] 实现批量联合 key 查询和候选过滤，保持所有外部抓取行为不变。
- [ ] 删除或避免排除记录的补全状态传播。
- [ ] 运行候选、补全计划和 enrichment 回归测试。

### Task 4: 历史数据批量迁移

**Files:**
- Modify: `code/app/data/database_handler.py`
- Modify: `code/app/backend/service.py`
- Modify: `code/app/backend/server.py`（如需增加后台迁移接口）
- Test: `code/tests/test_excluded_web_movie_cache.py`

**Produces:** 可重复执行、分批、事务安全的活动表到排除表迁移。

- [ ] 写失败测试：迁移黑名单和筛选命中的历史记录，非命中记录保持在活动表。
- [ ] 写失败测试：排除表已有记录时重复迁移不产生重复，模拟写入失败时活动表记录不丢失。
- [ ] 实现 `migrate_excluded_web_movies(batch_size=500)`，返回 `moved_code_prefix_movies`、`moved_actor_movies`、`skipped`、`errors`。
- [ ] 将迁移放入后台任务或显式管理接口，不放入后端启动关键路径。
- [ ] 运行迁移测试并检查实际数据库只读统计，确认不执行迁移演练之外的写入。

### Task 5: 完成验证

**Files:**
- Modify only files required by regressions caused by this feature.

- [ ] 运行排除缓存、候选、补全计划、黑名单、数据库和后端启动测试。
- [ ] 检查活动表/排除表联合去重的 SQL 查询计划，确认没有 N+1。
- [ ] 运行完整 pytest 回归测试。
- [ ] 运行 `git diff --check` 并检查工作区差异。
