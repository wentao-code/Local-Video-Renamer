# Local-Video-Renamer

Python 3.13 + PyQt5 本地视频重命名管理工具。

## 项目结构

```
Local_Video_gui.py          # GUI 主入口 → app.gui.main_window
backend_server.py           # HTTP 后端入口
app/
├── gui/                    # PyQt5 界面 (main_window, queen_library_viewer, ...)
├── core/                   # 数据模型、配置、文件名规则
├── services/               # 业务逻辑层
│   ├── queen_library_service.py  # 女王库独立服务
│   ├── enrichment/         # 数据丰富
│   ├── local_video/        # 本地视频导入/扫描/重命名
│   ├── library/            # 演员库、番号前缀库
│   ├── ladder/             # 天梯排行
│   └── detail/             # 详情页服务
├── scraper/                # 爬虫 (avfan, javtxt, queen_search)
├── data/repositories/      # SQLite 数据仓库
├── backend/                # HTTP API (service.py + server.py + client.py)
└── tools/                  # 调试工具
tests/                      # pytest 测试
```

## 数据库

- **主库**: `video_database.db` — 视频、演员、番号前缀等所有主数据
- **女王库**: 独立 `queen_library.db` (`QUEEN_LIBRARY_DB_FILE`)
  - `queen_keywords` — 手动添加的搜索关键词
  - `queen_videos` — 抓取到的视频记录 (keyword_id, raw_title, queen_name, video_title, detail_url, content_type, content_level)
  - `queen_import_logs` — 每次搜索的导入日志
  - `queen_profiles` — 女王基础信息 (body_type, style, face, age_group, like_level)
  - `queen_crawl_queue_log` — 每次批量抓取的队列处理记录 (keyword, source, scanned/imported/skipped_count)
- SQLite 默认不开 FOREIGN KEY 约束

## 女王库关键逻辑 (2026-07-09 修改)

### 关键词持久化规则

- `search_keyword()` 手动搜索 → 关键词**始终保存**到 `queen_keywords`
- `refresh_all()` 批量抓取 → `build_refresh_keywords()` 生成队列 = 已有关键词 + 自动拼接"套路直播_女王名"
- `_search_and_import_keyword(save_keyword=False)` → 自动拼接的关键词**不入库**，keyword_id 用 0
- `_resolve_keyword_id(cursor, keyword, save_keyword)` → save_keyword=False 时仅 lookup，不存在返回 0

### 抓取队列表

`queen_crawl_queue_log` — 每次 refresh_all() 启动时清空，每处理完一个关键词写入一行：
| keyword | source(关键词库/自动生成) | scanned_count | imported_count | skipped_count |

### 女王详情页链接指示灯

`QueenDetailWindow` 表格最后一列：黄灯(`#f0c040`)=detail_url 有值，红灯(`#d04040`)=无值。16×16 圆形 QLabel，`_build_detail_indicator()` 静态方法。

## 关键常量

- `QUEEN_RECORD_PREFIX = '套路直播_'`
- `QUEEN_VIDEO_CONTENT_TYPES = ('辱骂', '聊天', '调教')`
- `QUEEN_VIDEO_CONTENT_LEVELS = ('S', 'A', 'B', 'C')`

## 运行测试

```bash
python -m pytest tests/test_queen_library_service.py tests/test_queen_library_viewer.py -v
```
