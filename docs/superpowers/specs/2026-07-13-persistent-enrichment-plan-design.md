# 持久化补全计划设计

## 目标

让补全计划在程序重启、查看模式切换、网络中断和单批次失败后都能安全暂停并继续执行；任务列表能够展示计划级进度；运行模式能够跨重启保持。

## 已确认规则

1. 数据库是计划和明细状态的唯一真实来源，内存任务队列只负责当前进程的调度和界面展示。
2. 程序退出或异常重启时，计划中遗留的 `running` 状态按未完成处理，恢复为可继续执行的状态，不重复标记已完成明细。
3. 上次运行模式是查看模式时，启动后保持查看模式，未完成计划不自动执行；上次是任务模式时，启动后自动恢复未完成计划。
4. 查看模式切换必须先把计划执行状态写入数据库，再请求停止当前执行器；切回任务模式后从数据库重新排队。
5. 明细完成以明细表的状态为准；计划没有 `pending` 或 `running` 明细时才可以标记完成。

## 状态模型

计划状态：

- `running`：当前计划正在执行或等待下一批。
- `paused`：因查看模式、用户停止、程序退出或网络异常暂停。
- `completed`：所有计划明细均已处理。
- `failed`：计划达到重试上限或发生不可恢复错误。

明细状态：

- `pending`：等待执行。
- `running`：已被某次执行领取，带有执行时间和尝试次数。
- `completed`：本明细已完成，包含成功或业务上确定的无结果处理。
- `failed`：本次执行失败，保留错误信息；未达到重试上限时下一次运行前恢复为 `pending`。

每次领取明细必须使用数据库事务，并且只允许从 `pending` 领取。程序启动恢复时，所有遗留 `running` 明细恢复为 `pending`，这样异常退出不会造成永久占用；已经是 `completed` 的明细不重新执行。

## 数据库设计

保留现有四类明细临时表：`video_enrichment_batch_items`、`code_prefix_enrichment_batch_items`、`actor_enrichment_batch_items`、`actor_birthday_enrichment_batch_items`。为计划表增加：

- `paused_reason`：暂停原因。
- `last_error`：最近一次错误。
- `updated_at`：最近状态更新时间。
- `last_started_at`：最近一次执行开始时间。

为每类明细表增加：

- `attempt_count`：领取执行次数。
- `claimed_at`：最近一次领取时间。
- `started_at`：最近一次实际开始时间。
- `updated_at`：最近状态更新时间。

现有 `completed_batch_count` 在每批完成后更新；它表示已完成的批次数，最多为 `batch_count_limit`，不因为空批次或暂停错误增加。

数据库层提供以下操作：

- `list_resumable_enrichment_plans()`：返回 `running/paused` 且仍有未完成明细的计划。
- `recover_running_enrichment_plans()`：将遗留计划和明细中的 `running` 恢复为 `paused/pending`。
- `claim_enrichment_batch_items(plan_id, task_kind, batch_limit)`：事务领取下一批 `pending` 明细并写入 `running`、`claimed_at`、`started_at`、`attempt_count`。
- `update_enrichment_plan_progress(plan_id, completed_batch_count, status, paused_reason, last_error)`：原子更新计划状态和批次进度。
- `get_enrichment_plan_progress(plan_id, task_kind)`：返回批次、待处理、执行中、完成、失败数量。

## 执行和恢复流程

1. 用户下达补全任务时只进入 GUI 队列，不写计划明细。
2. 队列真正开始任务前创建计划；创建后立即查询计划进度并显示计划编号。
3. 每批开始前领取明细，补全服务只处理已领取的明细。
4. 批次结束时按结果更新明细状态，并在同一流程中更新计划进度。
5. 没有 `pending/running` 明细时完成计划；还有明细时根据批次数和运行模式决定继续、等待或暂停。
6. 查看模式切换时先持久化 `paused` 和暂停原因，再发送停止请求。当前批次返回后不得把计划标记为 `completed`。
7. 切回任务模式或程序以任务模式启动时，查询可恢复计划并重新创建 GUI 队列记录，继续使用原 `plan_id`。
8. 任务失败时保留明细错误和尝试次数；未达到上限则计划保持 `paused` 或 `running` 等待重试，达到上限才标记 `failed`。

## 运行模式持久化

新增 `config/user/runtime_settings.json`，使用以下结构：

```json
{
  "run_mode": "task"
}
```

启动时读取并规范化为 `task` 或 `view`，缺失或损坏时默认 `task`。每次切换模式成功后立即原子写入。模式设置先于恢复计划加载，确保查看模式不会触发后台补全。

## 任务列表显示

任务记录增加 `plan_id` 和计划进度字段：

- 计划编号。
- 当前批次/总批次。
- 待处理数量。
- 完成数量。
- 失败数量。
- 暂停原因。

任务列表每秒刷新时从内存记录展示；计划任务同时从数据库读取最新进度，避免后台执行和窗口打开状态不同步。普通查看任务没有计划编号时显示空值，不改变现有查看任务行为。

## 错误和并发处理

- 数据库领取使用条件更新，不能重复领取同一明细。
- 恢复时只处理遗留 `running`，不覆盖 `completed`、`failed` 的历史记录。
- 计划更新失败时保留明细结果并记录错误，下一次启动继续从明细状态恢复。
- 查看模式下只暂停补全和维护任务，查看、快照读取等任务仍可执行。

## 测试范围

增加以下回归测试：

1. 计划和四类明细表创建时包含新增字段。
2. 领取同一批明细只能成功一次，且写入开始时间和尝试次数。
3. 完成一批会更新 `completed_batch_count` 和待处理/完成/失败统计。
4. 遗留 `running` 计划恢复后不会重复处理已完成明细。
5. 查看模式切换后计划持久化为暂停，切回任务模式可以重新入队。
6. 任务模式和查看模式能够跨重启保存并读取。
7. 任务列表显示计划编号、批次和失败/暂停原因。

