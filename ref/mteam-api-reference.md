# M-Team API Reference

基于 swagger 文档、一线实测、以及 `mt-helper-search-download-analysis.md` 整理。
最后更新：2026-05-21。

---

## 通用规则

- **Base URL**: `https://api.m-team.cc`，所有端点路径以 `/api` 开头。
- **认证**: 所有请求必须带 Header `x-api-key: <MTEAM_API_KEY>`。
  - 不带 key → `{"code":1,"message":"非法用戶端"}`
  - 错 key → `{"code":1,"message":"key無效"}`
- **响应格式**: Default返回格式为 `{"code": 0|1, "message": "...", "data": ...}`。`code=0`  表示成功。
- **HTTP Method**: 所有端点均为 `POST`（包括查询类端点）。

---

## 1. `/api/torrent/search` — 搜索种子

**Content-Type**: `application/json`（JSON body，不能用 form-data）

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `keyword` | string (≤100) | 是 | 搜索关键词。**可以为空字符串 `""`，但不能不传这个字段。** |
| `mode` | string | 否 | 搜索模式，默认 `normal`。取值见下方。 |
| `pageNumber` | int32 [1, 1000] | 否 | 页码，默认 1。 |
| `pageSize` | int32 [1, 200] | 否 | 每页条数，默认 10。 |
| `sortField` | string | 否 | 排序字段，见下方枚举。 |
| `sortDirection` | string | 否 | 排序方向，`ASC` 或 `DESC`（需配合 `sortField`）。 |
| `discount` | string | 否 | 优惠过滤，见下方枚举。 |
| `categories` | int64[] | 否 | 分类 ID 数组，见分类映射表。 |
| `visible` | int32 | 否 | 可见性过滤，默认 1。 |
| `imdb` | string | 否 | 按 IMDB ID 过滤（如 `tt0145487`）。 |
| `douban` | string | 否 | 按豆瓣 ID 过滤（如 `1292052`）。 |
| `sources` | int64[] | 否 | 来源 ID 数组（如 BluRay, WEB-DL）。 |
| `mediums` | int64[] | 否 | 介质 ID 数组（如 UHD Blu-ray, BD）。 |
| `standards` | int64[] | 否 | 分辨率标准 ID 数组。 |
| `videoCodecs` | int64[] | 否 | 视频编码 ID 数组。 |
| `audioCodecs` | int64[] | 否 | 音频编码 ID 数组。 |
| `teams` | int64[] | 否 | 制作组 ID 数组。 |
| `processings` | int64[] | 否 | 处理方式 ID 数组（如 Remux, Encode）。 |
| `labels` | int32 | 否 | 标签 ID（旧版）。 |
| `labelsNew` | string[] | 否 | 新版标签字符串数组。 |
| `uploadDateStart` | datetime | 否 | 上传时间范围起始。 |
| `uploadDateEnd` | datetime | 否 | 上传时间范围结束。 |
| `hot` | boolean | 否 | 仅热门种子。 |
| `onlyFav` | boolean | 否 | 仅收藏。 |
| `offer` | boolean | 否 | 仅候选。 |
| `lastId` | int64 | 否 | 游标分页。 |

### `mode` 取值

| 值 | 说明 |
|---|---|
| `normal` | 普通搜索（默认） |
| `movie` | 仅电影 |
| `tvshow` | 仅剧集/综艺 |
| `music` | 仅音乐 |
| `adult` | 仅成人内容 |
| `rss` | RSS 模式 |
| `rankings` | 排行榜模式 |
| `waterfall` | 瀑布流模式 |
| `all` | 全部 |

### `sortField` 取值

| 值 | 说明 |
|---|---|
| `CREATED_DATE` | 按创建时间 |
| `SIZE` | 按文件大小 |
| `SEEDERS` | 按做种数 |
| `LEECHERS` | 按下载中数 |
| `TIMES_COMPLETED` | 按完成次数 |
| `NAME` | 按名称 |

### `discount` 取值

| 值 | 说明 |
|---|---|
| `NORMAL` | 无优惠 |
| `PERCENT_50` | 50% 下载量 |
| `PERCENT_70` | 70% 下载量 |
| `FREE` | 免费 |
| `_2X` | 双倍上传 |
| `_2X_FREE` | 双倍上传 + 免费 |
| `_2X_PERCENT_50` | 双倍上传 + 50% |

### 最小可用请求体

```json
{
  "keyword": "dune",
  "mode": "normal",
  "pageNumber": 1,
  "pageSize": 10,
  "visible": 1
}
```

### 响应结构

```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": {
    "pageNumber": 1,
    "pageSize": 10,
    "total": 123,
    "totalPages": 13,
    "data": [
      {
        "id": "1172412",
        "name": "Outlander 2026 S08 ...",
        "smallDescr": "...",
        "size": "20895219507",
        "category": "402",
        "seeders": 18,
        "leechers": 21,
        "...": "..."
      }
    ]
  }
}
```

> **注意**: 列表中的 `seeders`/`leechers` 可能为 `null`。需要精确做种数时，应在确认前用 `/api/torrent/detail` 获取 `data.status.seeders`。

### 获取 filter 参数的合法 ID

以下端点无需参数，`POST` 后返回对应的 ID→名称映射：

| 端点 | 用途 |
|---|---|
| `/api/torrent/categoryList` | 分类列表 |
| `/api/torrent/sourceList` | 来源列表 |
| `/api/torrent/mediumList` | 介质列表 |
| `/api/torrent/standardList` | 分辨率标准列表 |
| `/api/torrent/videoCodecList` | 视频编码列表 |
| `/api/torrent/audioCodecList` | 音频编码列表 |
| `/api/torrent/processingList` | 处理方式列表 |
| `/api/torrent/teamList` | 制作组列表 |

---

## 2. `/api/torrent/detail` — 获取种子详情

**Content-Type**: `application/x-www-form-urlencoded`（form-data，**不能用 JSON**）

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string/int | 是 | 种子 ID。可传字符串或数字。**字段名必须是 `id`，不能用 `tid`。** |

### 实测样例：id = 1172412

请求：
```
POST /api/torrent/detail
Content-Type: application/x-www-form-urlencoded

id=1172412
```

返回关键字段：

| 字段 | 值 |
|---|---|
| `id` | `1172412` |
| `name` | `Outlander 2026 S08 Complete 1080p NF WEB-DL H264 DDP5.1-UBWEB` |
| `category` | `402` |
| `size` | `20895219507` (≈19.4 GB) |
| `numfiles` | `8` |
| `status.seeders` | `18` |
| `status.leechers` | `21` |
| `status.timesCompleted` | `47` |
| `status.discount` | `PERCENT_50` |

---

## 3. `/api/torrent/genDlToken` — 生成下载链接

**Content-Type**: `application/x-www-form-urlencoded`（form-data，**不能用 JSON**）

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string/int | 是 | 种子 ID。 |

### 请求与响应

```
POST /api/torrent/genDlToken
Content-Type: application/x-www-form-urlencoded

id=1172412
```

```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": "https://api.m-team.cc/api/rss/dlv2?sign=...&t=...&tid=1172412&uid=..."
}
```

`data` 是完整下载 URL，直接 `GET` 返回 `application/x-bittorrent`。**可直接传给 qBittorrent `torrents/add(urls=...)`，不要落盘。**

---

## 4. `/api/torrent/files` — 种子内文件列表

**Content-Type**: `application/x-www-form-urlencoded`

| 参数 | 类型 | 必填 |
|---|---|---|
| `id` | int64 | 是 |

---

## 5. `/api/torrent/mediaInfo` — 种子媒体信息

**Content-Type**: `application/x-www-form-urlencoded`

| 参数 | 类型 | 必填 |
|---|---|---|
| `id` | int64 | 是 |

返回视频编码、分辨率、音轨等元数据。

---

## 6. `/api/torrent/peers` — 种子 Peer 列表

**Content-Type**: `application/x-www-form-urlencoded`

| 参数 | 类型 | 必填 |
|---|---|---|
| `id` | int64 | 是 |

---

## 7. `/api/media/douban/infoV2` — 豆瓣媒体信息

**Method**: `POST`
**参数**: 均以 query string 传入（`?code=...&refresh=...`）

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `code` | string | 是 | 豆瓣 subject ID（如 `1292052`）。 |
| `refresh` | boolean | 是 | 是否强制刷新缓存。 |

> **实测可用**，返回内容非常丰富（包含豆瓣评分、海报、简介、演职员等），此处不做展开。

---

## 8. `/api/media/douban/elessarV2` — 豆瓣 Elessar 媒体信息

参数同 `/api/media/douban/infoV2`（`code` + `refresh`）。

---

## 9. `/api/media/imdb/info` — IMDB 媒体信息

参数同上述豆瓣端点（`code` 传 IMDB ID，如 `tt0111161`）。

---

## 分类 ID 速查表

以下是当前项目建议启用的精简分类：

| ID | 名称 | 用途 |
|---|---|---|
| `100` | 电影 | 电影总类 |
| `419` | 电影-HD | 电影优先 |
| `421` | 电影-Blu-Ray | 高质量电影 |
| `439` | 电影-Remux | 收藏向电影 |
| `401` | 电影-SD | 电影低清 |
| `402` | 影剧-综艺-HD | 剧集/综艺主力 |
| `438` | 影剧-综艺-BD | 高质量剧集 |
| `403` | 影剧-综艺-SD | 剧集低清 |
| `105` | 影剧-综艺 | 剧集/综艺总类 |
| `405` | 动画 | 动画主类 |
| `449` | 動漫 | 动漫扩展类 |
| `404` | 纪录 | 纪录片 |
| `444` | 紀錄 | 纪录片（另一分类） |

完整 48 项分类字典可调用 `/api/torrent/categoryList` 获取。

---

## 标准下载链路

```
search(JSON) → 选中 id → detail(form-data) → genDlToken(form-data) → qB torrents/add(urls=download_url, paused=true)
```

关键约束：
- search 走 JSON body，detail / genDlToken 走 form-data。
- 不要下载 `.torrent` 文件落盘；genDlToken 返回的 URL 直接喂给 qB。
- 提交 qB 时默认 `paused=true`。
- qB add 成功依据响应文本 `Ok.` / `ok` / `true`，不是 HTTP 200。
