# 持久化任务暂停与恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为任务列表增加协作式暂停/继续，并将具备恢复描述的任务持久化到 SQLite，使应用重启后可以恢复字幕任务和补全计划。

**Architecture:** `GuiTaskQueue` 继续负责当前进程内的 FIFO 调度；新增 `gui_task_records` SQLite 表和持久化适配器记录每次状态变化。可恢复任务通过 `resume_kind + resume_payload` 注册恢复工厂，启动时将上次运行中的任务转为暂停并重新入队；没有恢复描述的临时任务显示为不可恢复。

**Tech Stack:** Python 3, PyQt5, SQLite, `unittest`, 现有 `DatabaseHandler` 和 GUI 任务队列。

## Global Constraints

- 暂停不强制冻结或杀死正在运行的 `infer.exe`、FFmpeg 或其他外部调用。
- 当前工作单元结束后才进入 `已暂停`，后续等待任务不启动。
- 字幕任务按单个视频编号保存恢复参数，并继续复用现有字幕/FFprobe/FFmpeg 检查逻辑。
- 不修改或回滚工作区中与本功能无关的既有修改。

---

### Task 1: 建立持久化任务表和适配器

**Files:**
- Modify: `code/app/data/database_handler.py`
- Create: `code/app/data/repositories/gui_task_repo.py`
- Test: `code/tests/test_gui_task_repository.py`

**Interfaces:**
- Produces `DatabaseHandler.save_gui_task(record_dict) -> dict`.
- Produces `DatabaseHandler.update_gui_task(task_id, **changes) -> dict | None`.
- Produces `DatabaseHandler.list_gui_tasks(statuses=None) -> list[dict]`.
- Produces `DatabaseHandler.mark_running_gui_tasks_paused(reason) -> int`.

- [ ] **Step 1: Write failing repository tests**

测试创建临时数据库，验证保存、更新、JSON 参数往返、按状态查询，以及启动恢复把 `running` 改为 `paused`。

- [ ] **Step 2: Run repository tests and confirm the expected missing-method failure**

Run: `python -m unittest tests.test_gui_task_repository` from `D:\pycharm_pro\Local-Video-Renamer\code`.

- [ ] **Step 3: Add `gui_task_records` schema and repository methods**

使用现有数据库初始化事务创建表，JSON 字段统一使用 UTF-8；更新方法只更新传入列并维护 `updated_at`，查询结果转换为普通字典。

- [ ] **Step 4: Run repository tests**

Run: `python -m unittest tests.test_gui_task_repository`; expected result is all tests passing.

### Task 2: 将队列状态同步到 SQLite

**Files:**
- Modify: `code/app/gui/task_queue.py`
- Test: `code/tests/test_task_queue.py`

**Interfaces:**
- `TaskRecord` gains `resume_kind`, `resume_payload`, `resumable`, `paused_at`, and `non_resumable_reason`.
- `GuiTaskQueue.configure_persistence(database_handler)` attaches the repository without changing tests that use an in-memory queue.
- `enqueue(..., resume_kind='', resume_payload=None, resumable=False)` stores the descriptor.
- `request_pause`, `mark_completed`, `mark_failed`, `mark_partial`, `mark_deleted`, retry transitions, and resume transitions persist the resulting state.
- `resume_task(task_id) -> bool` and `resume_tasks(task_ids) -> int` clear pause state and put records back into FIFO waiting order.

- [ ] **Step 1: Add failing queue tests**

Cover running-task pause request followed by `mark_completed`, direct pause of a waiting task, resume FIFO behavior, and persistence calls containing the final status.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest tests.test_task_queue.GuiTaskQueueTest.test_pause_request_persists_after_work_unit tests.test_task_queue.GuiTaskQueueTest.test_resume_paused_task`.

- [ ] **Step 3: Implement persistence hooks and resume operations**

Use one private `_persist_record(record)` helper. A running task with `pause_requested` is reinserted at the front only after its worker result is handled. Resume only accepts `TASK_STATUS_PAUSED` and `resumable` records.

- [ ] **Step 4: Run all queue tests**

Run: `python -m unittest tests.test_task_queue`; expected result is all tests passing.

### Task 3: Add resumable task registry and startup recovery

**Files:**
- Create: `code/app/gui/task_resume_registry.py`
- Modify: `code/app/gui/backend_task_worker.py`
- Modify: `code/app/gui/main_window.py`
- Test: `code/tests/test_task_resume_registry.py`
- Test: `code/tests/test_task_queue.py`

**Interfaces:**
- `TaskResumeRegistry.register(kind, factory)` registers a factory receiving `(payload, host)` and returning a callable.
- `TaskResumeRegistry.build(record, host) -> callable | None` validates JSON and factory lookup.
- `recover_persisted_tasks(host) -> list[TaskRecord]` marks stale running rows paused, rebuilds resumable callbacks, and marks unknown descriptors non-resumable.

- [ ] **Step 1: Write failing registry and startup recovery tests**

Test valid factory reconstruction, malformed payload handling, unknown kind becoming non-resumable, and stale running rows becoming paused.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest tests.test_task_resume_registry`.

- [ ] **Step 3: Implement registry and initialize it during application startup**

Register subtitle and enrichment factories only after backend client and queue are initialized. Recovery must be idempotent by checking `task_id` already present in the queue.

- [ ] **Step 4: Run registry plus startup tests**

Run: `python -m unittest tests.test_task_resume_registry tests.test_main_window_startup`.

### Task 4: Add task-list pause and resume controls

**Files:**
- Modify: `code/app/gui/task_queue_viewer.py`
- Modify: `code/app/gui/main_window.py`
- Test: `code/tests/test_task_queue_viewer.py`

**Interfaces:**
- Viewer adds `btn_pause_resume` and dispatches selected IDs to `request_pause` or `resume_tasks`.
- Button text and enabled state are derived from selected records: running/waiting => pause, paused => resume, mixed/non-resumable => disabled or explanatory status.

- [ ] **Step 1: Write failing UI tests**

Test that a running row exposes pause, a paused resumable row exposes resume, and button actions invoke the queue methods.

- [ ] **Step 2: Run focused viewer tests and confirm failure**

Run: `python -m unittest tests.test_task_queue_viewer`.

- [ ] **Step 3: Implement controls and refresh behavior**

Keep deletion behavior unchanged. Preserve row selection across refresh and show `pause_reason`/`non_resumable_reason` in the existing final column.

- [ ] **Step 4: Run viewer tests**

Run: `python -m unittest tests.test_task_queue_viewer`.

### Task 5: Make subtitle tasks resumable per video

**Files:**
- Modify: `code/app/gui/main_window.py`
- Modify: `code/app/services/translation/subtitle_pipeline_service.py`
- Test: `code/tests/test_main_window_startup.py`
- Test: `code/tests/test_subtitle_pipeline_service.py`

**Interfaces:**
- Each subtitle task is enqueued with `resume_kind='subtitle_pipeline_video'` and payload `{input_dir, video_code, candidate_run_id}`.
- The resume factory calls `backend_client.generate_subtitles_pipeline([video_code], candidate_run_id, manage_candidate_task=False)`.
- The existing serial order remains unchanged; a pause request is observed after the current per-video pipeline returns.

- [ ] **Step 1: Add failing tests for subtitle resume descriptors**

Assert each queue record has one video code in its JSON payload and the rebuilt callback submits only that code.

- [ ] **Step 2: Run focused subtitle tests and confirm failure**

Run: `python -m unittest tests.test_main_window_startup.MainWindowStartupTest.test_subtitle_tasks_include_resume_descriptor tests.test_subtitle_pipeline_service`.

- [ ] **Step 3: Add descriptor when enqueueing subtitle tasks and register the factory**

Do not reuse the candidate preparation task ID as the per-video queue task ID. Preserve existing candidate confirmation and per-video result updates.

- [ ] **Step 4: Run subtitle and queue tests**

Run: `python -m unittest tests.test_main_window_startup tests.test_subtitle_pipeline_service tests.test_task_queue`.

### Task 6: Wire database startup, recovery, and full regression verification

**Files:**
- Modify: `code/Local_Video_gui.py`
- Modify: `code/backend_server.py` only if backend initialization must expose the shared database handler
- Modify: `code/app/backend/service.py` only if startup database access requires a service method
- Test: `code/tests/test_task_persistence_startup.py`

- [ ] **Step 1: Write failing integration tests**

Simulate an application restart with one paused subtitle task and one completed task; assert only the paused resumable task returns to the queue.

- [ ] **Step 2: Implement bootstrap wiring in `code/Local_Video_gui.py`**

Construct the repository from the existing `DatabaseHandler`, configure the global queue, call stale-running recovery once, then register recovered callbacks before scheduling the queue.

- [ ] **Step 3: Run full regression tests and syntax checks**

Run: `python -m unittest discover -s tests`; expected result is zero failures. Run an in-memory `compile()` check for modified Python files to avoid writing locked `__pycache__` files.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check` and `git status --short`; verify only feature files and tests changed in addition to the pre-existing dirty worktree changes.
