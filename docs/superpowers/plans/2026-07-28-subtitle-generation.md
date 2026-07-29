# 本地视频字幕生成接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入本地 Whisper 翻译模型，为固定字幕输入目录中的视频生成 SRT、VTT、LRC 字幕，不修改视频和模型目录。

**Architecture:** 新增独立的字幕生成服务负责配置校验、`infer.exe` 子进程调用和输出验证。BackendService 暴露同步 HTTP 接口，主界面通过现有异步任务队列调用该接口；模型进程工作目录固定为模型根目录。

**Tech Stack:** Python 3、`subprocess.run`、现有 HTTP backend、PyQt5 GUI、现有 GUI task queue、pytest/unittest。

## Global Constraints

- 不修改 `D:\software\software_for_chickenrice` 下任何文件。
- 不调用 `.bat` 文件，避免 `pause` 阻塞。
- 当前阶段不调用 ffmpeg，不覆盖已有视频或字幕。
- 默认输出 `srt,vtt,lrc`，默认设备为 `cuda`。
- 默认输入目录为 `user_data/translation_videos`，可通过 `TRANSLATION_INPUT_DIR` 修改。
- 字幕生成成功后按视频编号创建子目录，并将视频与字幕移动到该目录；目标冲突时不覆盖。

---

### Task 1: 字幕生成服务

**Files:**
- Create: `code/app/core/translation_config.py`
- Create: `code/app/services/translation/subtitle_generation_service.py`
- Test: `code/tests/test_subtitle_generation_service.py`

**Interfaces:**
- `TranslationConfig.from_environment()` 返回模型路径、可执行文件、设备、输出格式和覆盖策略。
- `SubtitleGenerationService.generate_from_directory()` 递归发现固定目录中的视频，并返回 `input_dir`, `results`, `success_count`, `failed_count`。

- [ ] 写失败测试：验证服务使用模型根目录作为 `cwd`、构造 GPU 视频参数、检查生成的字幕文件，并将非零退出码报告为失败。
- [ ] 运行定向测试，确认因新模块不存在而失败。
- [ ] 实现配置解析、路径校验、命令调用和逐文件输出验证。
- [ ] 运行服务测试，确认通过。

### Task 2: Backend API

**Files:**
- Modify: `code/app/backend/service.py`
- Modify: `code/app/backend/server.py`
- Modify: `code/app/backend/client.py`
- Test: `code/tests/test_backend_subtitle_generation.py`

**Interfaces:**
- `BackendService.generate_subtitles()` 调用字幕服务。
- `POST /translation/subtitles` 不依赖视频路径参数。
- `BackendClient.generate_subtitles()` 调用该接口并使用长请求超时。

- [ ] 写失败测试：验证 backend 路由转发视频路径并返回逐文件结果。
- [ ] 运行测试确认路由和 client 方法缺失。
- [ ] 添加 backend service、HTTP 路由和 client 方法。
- [ ] 运行 backend 定向测试。

### Task 3: 主界面操作

**Files:**
- Modify: `code/app/gui/main_window.py`
- Modify: `code/app/gui/i18n.py`
- Test: `code/tests/test_main_window_startup.py` or a focused subtitle action test

**Interfaces:**
- 新增独立的“生成字幕”按钮，不依赖本地扫描结果。
- 后台使用固定字幕目录作为视频输入。
- 使用现有 `start_async_task` 进入任务列表，完成后显示成功/失败数量。

- [ ] 写失败测试：验证字幕操作收集扫描结果中的真实文件路径并调用 client。
- [ ] 运行测试确认按钮行为缺失。
- [ ] 接入按钮、任务回调和中文界面文本。
- [ ] 运行 GUI 定向测试。

### Task 4: 全量验证

**Files:**
- Modify: `.env.example` only if configuration documentation is needed.

- [ ] 运行字幕服务、backend、GUI 相关测试。
- [ ] 运行 Python 编译检查和 `git diff --check`。
- [ ] 只读执行 `infer.exe --help` 验证模型入口仍可调用。
- [ ] 检查工作区差异，确保没有写入模型目录。
