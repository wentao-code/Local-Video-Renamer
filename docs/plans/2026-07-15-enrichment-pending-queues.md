# 补全任务来源队列改造计划

## 目标

将补全候选与主数据分离到固定的来源待补全表中，任务执行只消费对应队列表；同时消除候选计算 N+1、GUI 主线程阻塞、无效自动重试和客户端断开导致的二次异常。

## 队列表

- `pending_video_javtxt`、`pending_video_avfan`
- `pending_code_prefix_avfan`、`pending_code_prefix_javtxt`、`pending_code_prefix_supplement`
- `pending_actor_avfan`、`pending_actor_javtxt`、`pending_actor_supplement`
- `pending_actor_binghuo`、`pending_actor_baomu`

每张表保存任务/计划标识、顺序、来源所需的检索键、补全模式和状态。不同任务通过计划标识隔离，不动态创建物理表。

## 规则

1. 视频：具体番号进入 JAVTXT；JAVTXT 无结果或无演员时进入 AVFan，模式为完整补全或仅演员。
2. 演员：演员名进入 AVFan；其影片具体番号进入 JAVTXT；JAVTXT 无结果或无演员时进入 AVFan 补充。
3. 番号：番号前缀进入 AVFan；其影片具体番号进入 JAVTXT；JAVTXT 无结果或无演员时进入 AVFan 补充。
4. 演员资料：演员名先进入并火；无结果，或生日、身高、胸围、腰围、臀围、罩杯任一缺失时进入保木。

## 实施顺序

1. 先添加失败测试，覆盖表路由、批量候选、阶段规则、GUI 异步和断开连接。
2. 增加来源表结构和兼容旧计划的路由元数据。
3. 用批量 SQL 一次生成计划候选并写入对应来源表。
4. 调整执行器，使其只领取计划对应来源表中的项目。
5. 后台线程创建计划；明确不可重试错误；安全忽略回写时的连接断开。
6. 运行针对性测试和完整测试集。
