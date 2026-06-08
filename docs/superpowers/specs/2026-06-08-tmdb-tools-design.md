# TMDB 工具集设计文档

日期: 2026-06-08
状态: 已确认

## 概述

为 NasClawBot Agent 系统新增 TMDB (The Movie Database) API v3 工具集。目的是利用 TMDB 影视元数据来增强 M-Team 搜索体验：通过 TMDB 获取准确的影视名称和 IMDb ID，再用 mteam_search 的 `imdb` 参数精准搜索资源。

## 动机

- 用户输入的中文片名/剧名在 M-Team 上可能匹配不到最佳结果
- TMDB 可以返回标准化的影视信息（中文标题、原名、IMDb ID、评分等）
- 通过工具链组合 (tmdb_search → tmdb_details → mteam_search) 提升搜索准确度
- 观察多个工具对 Agent 推理路径的影响

## 架构

```
app/adapters/tmdb.py       ← TMDBAdapter（HTTP 层，language=zh-CN）
app/tools/tmdb_search.py   ← tmdb_search 工具
app/tools/tmdb_details.py  ← tmdb_details 工具
app/tools/tmdb_discover.py ← tmdb_discover 工具
app/tools/tmdb_trending.py ← tmdb_trending 工具
tests/test_tmdb_adapter.py
tests/test_tmdb_tools.py
```

修改文件:
- `app/config.py` — 新增 `tmdb_api_key`
- `app/tools/__init__.py` — 导出 4 个 TMDB 工具
- `app/agent/runner.py` — 注册工具 + 更新 system prompt + 更新 Filter

## TMDBAdapter

### 构造

```python
TMDBAdapter(api_key: str, base_url: str = "https://api.themoviedb.org")
```

### 方法

| 方法 | TMDB 端点 | 说明 |
|------|-----------|------|
| `search_multi(query, page, include_adult)` | `GET /3/search/multi` | 统一搜索电影/电视剧/人物 |
| `movie_details(movie_id)` | `GET /3/movie/{id}` | 电影详情，自动 append `external_ids` |
| `tv_details(series_id)` | `GET /3/tv/{id}` | 电视剧详情，自动 append `external_ids` |
| `discover_movie(**filters)` | `GET /3/discover/movie` | 电影发现 |
| `discover_tv(**filters)` | `GET /3/discover/tv` | 电视剧发现 |
| `trending_all(time_window)` | `GET /3/trending/all/{window}` | 热门趋势 |
| `health()` | `GET /3/authentication` | 连接健康检查 |

### 关键行为

- 所有请求自动附加 `language=zh-CN` 查询参数（中文返回）
- 所有请求附加 `api_key` 查询参数
- HTTP 客户端: `httpx`（与 mteam adapter 一致）
- 错误处理: HTTP 错误或 JSON 解析失败抛出自定义异常

## 四个工具

### tmdb_search

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词（中文或英文） |
| `media_type` | string | 否 | `movie` / `tv` / `person`，省略返回全部 |

内部调用 `search_multi`，按 `media_type` 过滤结果。返回最多 5 条。

### tmdb_details

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tmdb_id` | integer | 是 | TMDB 媒体 ID |
| `media_type` | string | 是 | `movie` 或 `tv` |

返回中文标题、概述、上映/首播日期、评分、类型、IMDb ID（来自 external_ids）。

### tmdb_discover

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `media_type` | string | 是 | `movie` 或 `tv` |
| `sort_by` | string | 否 | 排序方式，默认 `popularity.desc` |
| `with_genres` | string | 否 | 类型 ID，逗号分隔 |
| `year` | integer | 否 | 年份过滤 |
| `vote_average_gte` | float | 否 | 最低评分 |
| `vote_count_gte` | integer | 否 | 最低评分人数 |

只暴露最常用参数。返回最多 5 条。

### tmdb_trending

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `media_type` | string | 否 | `all` / `movie` / `tv` / `person`，默认 `all` |
| `time_window` | string | 否 | `day` / `week`，默认 `day` |

返回热门列表，最多 5 条。

## 配置

`.env` 新增:

```bash
TMDB_API_KEY=your_api_key_here
```

`app/config.py` Settings 新增:

```python
tmdb_api_key: str = Field(default_factory=lambda: _get_env("TMDB_API_KEY"))
```

## Agent 集成

### Filter 更新

4 个 TMDB 工具加入白名单（全部只读，不触发 Gate 审批）:

```python
Filter(allow=[
    # 现有 9 个...
    "tmdb_search", "tmdb_details", "tmdb_discover", "tmdb_trending",
])
```

### System Prompt 追加

```
你也可以搜索 TMDB 影视数据库来辅助查找资源：
- tmdb_search: 搜索电影/电视剧/人物，可按 media_type 筛选
- tmdb_details: 获取影视详情（含 IMDb ID，可用于后续 mteam_search 精准搜索）
- tmdb_discover: 按类型、评分、年份等条件发现影视作品
- tmdb_trending: 查看当前热门电影/电视剧/人物趋势

使用 TMDB 找到准确的影视名称和 IMDb ID 后，用 mteam_search 的 imdb 参数精准搜索 M-Team 资源。
```

## 典型 Agent 使用场景

### 场景 1: 精准搜索

```
用户: "帮我找沙丘2"
Agent: tmdb_search(query="沙丘2")
       → Dune: Part Two (id=693134, media_type=movie)
Agent: tmdb_details(tmdb_id=693134, media_type="movie")
       → 中文名: 沙丘2, IMDb: tt15239678, 评分: 7.8, 2024-03-01
Agent: mteam_search(imdb="tt15239678")
       → 精准匹配 M-Team 资源
```

### 场景 2: 发现 + 搜索

```
用户: "有什么好看的科幻片推荐"
Agent: tmdb_discover(media_type="movie", with_genres="878",
                      sort_by="vote_average.desc", vote_count_gte=200)
       → 高分科幻片列表
用户: "下载第一个"
Agent: mteam_search(keyword="<片名>")
       → M-Team 搜索结果
```

### 场景 3: 热门趋势

```
用户: "这周什么剧比较火"
Agent: tmdb_trending(media_type="tv", time_window="week")
       → 本周热门剧集列表
```

## 测试策略

### 单元测试 (test_tmdb_adapter.py)

- Mock httpx 响应，验证 adapter 方法正确构造 URL 和参数
- 验证 `language=zh-CN` 始终出现在请求中
- 验证 `append_to_response=external_ids` 在 details 方法中
- 验证错误响应处理

### 工具测试 (test_tmdb_tools.py)

- 使用 mock adapter 测试每个工具的 run() 方法
- 验证参数校验逻辑
- 验证返回结果的 ToolResponse 格式

### 集成注意事项

- 测试中不调用真实 TMDB API（使用 mock）
- 可在 CI 之外手动测试连接健康检查

## 安全

- TMDB 工具全部只读，不触发 Gate 审批流
- `include_adult` 固定为 `false`
- `api_key` 只从环境变量读取，不暴露在日志/响应中
