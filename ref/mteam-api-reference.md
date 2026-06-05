# M-Team API Reference

基于 swagger 文档、一线实测、以及 `mt-helper-search-download-analysis.md` 整理。
最后更新：2026-06-04。

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
| `keyword` | string (≤100) | 否 | 搜索关键词。可以为空字符串 `""` 或不传，此时返回全站最新（配合其他过滤器使用）。 |
| `mode` | string | 否 | 搜索模式，默认 `normal`。取值见下方。 |
| `pageNumber` | int32 [1, 1000] | 否 | 页码，默认 1。 |
| `pageSize` | int32 [1, 200] | 否 | 每页条数，默认 10。 |
| `sortField` | string | 否 | 排序字段，见下方枚举。 |
| `sortDirection` | string | 否 | 排序方向，`ASC` 或 `DESC`（需配合 `sortField`）。 |
| `discount` | string | 否 | 优惠过滤，见下方枚举。 |
| `categories` | int64[] | 否 | 分类 ID 数组，见分类映射表。 |
| `visible` | int32 | 否 | 可见性过滤，默认 1。 |
| `imdb` | string | 否 | 按 IMDB ID 过滤（如 `tt0145487`）。可独立使用（无需 `keyword`）。与 `keyword` 同时使用时为 **AND** 关系。与 `douban` 同时使用时为 **OR** 关系。 |
| `douban` | string | 否 | 按豆瓣 ID 过滤（如 `1292052`）。可独立使用（无需 `keyword`）。与 `keyword` 同时使用时为 **AND** 关系。与 `imdb` 同时使用时为 **OR** 关系。 |
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
| `normal` | 普通搜索（默认），所有类别 |
| `movie` | 仅电影 |
| `tvshow` | 仅剧集/综艺 |
| `music` | 仅音乐（如 FLAC 无损资源） |
| `adult` | 仅成人内容 |
| `rss` | RSS 模式。**实测返回 code=1 FAIL**，不可用。 |
| `rankings` | 全站热门排行。**忽略 `keyword` 参数**，按置顶/热度排序返回全局结果。 |
| `waterfall` | 瀑布流模式。**实测返回「無權限」**，当前账号不可用。 |
| `all` | **与 `normal` 行为完全一致**，实测无区别。 |

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

> **注意**：`discount` 仅接受**单个值**，不支持逗号拼接多个值。同时 `keyword` 也不支持多关键词 OR 搜索（空格、逗号、管道符均无效），API 将整个字符串作为单一搜索词处理。

### 最小可用请求体

按关键词搜索：
```json
{
  "keyword": "dune",
  "mode": "normal",
  "pageNumber": 1,
  "pageSize": 10,
  "visible": 1
}
```

按 IMDB / 豆瓣 ID 搜索（无需 keyword）：
```json
{
  "imdb": "tt0145487",
  "pageNumber": 1,
  "pageSize": 10
}
```

浏览全站最新：
```json
{
  "pageNumber": 1,
  "pageSize": 10
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
        "id": "1174857",
        "createdDate": "2026-04-30 23:44:01",
        "lastModifiedDate": "2026-04-30 23:44:29",
        "name": "Dune AKA Dune: Part One 2021 1080p POL Blu-ray AVC TrueHD 7.1 Atmos-DVDSEED",
        "smallDescr": "1080p @ 22998 kbps - TrueHD 7.1 Atmos @ 3243 kbps",
        "size": "48271819716",
        "category": "421",
        "source": null,
        "medium": null,
        "standard": "1",
        "videoCodec": "1",
        "audioCodec": "9",
        "team": null,
        "processing": null,
        "countries": ["2", "5"],
        "numfiles": "348",
        "labels": "0",
        "labelsNew": [],
        "msUp": "0",
        "anonymous": true,
        "infoHash": null,
        "imdb": "https://www.imdb.com/title/tt1160419/",
        "imdbRating": "8",
        "douban": "",
        "doubanRating": null,
        "dmmCode": "",
        "dmmInfo": null,
        "author": null,
        "editedBy": null,
        "editDate": null,
        "collection": false,
        "collectionStatus": null,
        "inRss": false,
        "canVote": false,
        "imageList": [
          "https://api.gateway996.com/api/media/redirect?..."
        ],
        "resetBox": null,
        "seeders": null,
        "leechers": null,
        "status": {
          "id": "1174857",
          "createdDate": "2026-04-30 23:44:01",
          "lastModifiedDate": "2026-06-05 12:40:43",
          "pickType": "normal",
          "toppingLevel": "0",
          "toppingEndTime": null,
          "discount": "PERCENT_50",
          "discountEndTime": null,
          "timesCompleted": "212",
          "comments": "0",
          "lastAction": "2026-06-05 12:20:28",
          "lastSeederAction": "2026-06-05 12:20:28",
          "views": "34",
          "hits": "0",
          "support": "0",
          "oppose": "0",
          "status": "NORMAL",
          "seeders": "3",
          "leechers": "0",
          "banned": false,
          "visible": true,
          "promotionRule": null,
          "mallSingleFree": null
        }
      }
    ]
  }
}
```

> **重要**: 所有动态状态数据（`seeders`、`leechers`、`discount`、`timesCompleted`）**仅在 `status` 子对象中**，顶层同名字段始终为 `null`。`status.discount` 反映实时优惠状态，顶层无此数据。静态元数据（`name`、`size`、`category`、`imdb`、`douban`）放在顶层。

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

## 10. `/api/member/base` — 单个用户基本信息

**Method**: `POST`
**Content-Type**: `application/json`
**参数**: query string

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int64 | 是 | 用户 UID。不传返回 `{"code":1,"message":"參數錯誤"}`。 |

**请求示例**：
```
POST /api/member/base?id=361187
Content-Type: application/json
```

**响应结构**：
```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": {
    "uid": "361187",
    "username": "IGUMIAO",
    "enabled": true,
    "role": "6",
    "country": "8",
    "donor": false,
    "donorUntil": null,
    "warned": false,
    "warnedUntil": null,
    "avatarUrl": null,
    "title": null,
    "respAt": "2026-06-04 21:26:00",
    "lastBrowse": "2026-06-04 21:22:47"
  }
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | string | 用户 ID |
| `username` | string | 用户名 |
| `enabled` | boolean | 账号是否启用 |
| `role` | string | 角色 ID（`"6"` = 普通用户，`"3"` = ？） |
| `country` | string | 国家/地区 ID |
| `donor` | boolean | 是否为捐赠者 |
| `donorUntil` | string\|null | 捐赠到期时间 |
| `warned` | boolean | 是否被警告 |
| `warnedUntil` | string\|null | 警告到期时间 |
| `avatarUrl` | string\|null | 头像 URL |
| `title` | string\|null | 用户头衔 |
| `respAt` | string | 最近响应时间 |
| `lastBrowse` | string | 最近浏览时间 |

> **注意**：传入不存在的 ID 返回 `{"code":"0","message":"SUCCESS","data":{}}`（空 data 对象），不会报错。

---

## 11. `/api/member/bases` — 批量查询用户基本信息

**Method**: `POST`
**Content-Type**: `application/json`（JSON body）

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ids` | int64[] | 是 | 用户 UID 数组。body 格式：`{"ids": [361187, 300084]}`。 |

**请求示例**：
```
POST /api/member/bases
Content-Type: application/json

{"ids": [361187, 300084]}
```

**响应结构**：
```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": {
    "361187": {
      "uid": "361187",
      "username": "IGUMIAO",
      "enabled": true,
      "role": "6",
      "country": "8",
      "donor": false,
      "donorUntil": null,
      "warned": false,
      "warnedUntil": null,
      "avatarUrl": null,
      "title": null,
      "respAt": "2026-06-04 21:26:34",
      "lastBrowse": "2026-06-04 21:22:47"
    },
    "300084": {
      "uid": "300084",
      "username": "xnwyzxk",
      ...
    }
  }
}
```

> `data` 是一个以 UID 字符串为 key 的字典，每个 value 的字段结构与 `/api/member/base` 完全一致。传入的 ID 中如果某些不存在，对应 key 不会出现在返回的 `data` 中。

---

## 12. `/api/member/profile` — 用户完整资料

**Method**: `POST`
**Content-Type**: `application/json`
**参数**: query string

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `uid` | int64 | 否 | 目标用户 UID。**不传则返回当前 API key 所属用户自己的完整资料。** |

**请求示例**：
```
POST /api/member/profile?uid=361187
Content-Type: application/json
```

**响应结构**（顶层）：
```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": {
    "id": "361187",
    "createdDate": "2025-06-17 11:47:56",
    "lastModifiedDate": "2026-06-04 21:14:18",
    "username": "IGUMIAO",
    "email": "xnwyzxh@gmail.com",
    "status": "CONFIRMED",
    "enabled": true,
    "ip": "43.255.191.8",
    "country": "8",
    "gender": "OTHER",
    "privacy": "LOW",
    "language": null,
    "allowDownload": true,
    "parked": false,
    "parentId": "300084",
    "invites": "0",
    "role": "6",
    "seedtime": "942216289",
    "leechtime": "6448187",
    "torrentCommentCount": "0",
    "seekCommentCount": "0",
    "forumCommentCount": "0",
    "ipCount": "393",
    "friend": false,
    "block": false,
    "anonymous": true,
    "enabledTfa": true,
    "releaseCode": "LYG5aa2u",
    "telegramUserName": null,
    "telegramChatId": null,
    "memberStatus": { ... },
    "memberCount": { ... },
    "config": { ... },
    "authorities": [ ... ]
  }
}
```

### `data.memberStatus` — 会员状态

| 字段 | 类型 | 说明 |
|---|---|---|
| `vip` | boolean | 是否为 VIP |
| `vipUntil` | string\|null | VIP 到期时间 |
| `donor` | boolean | 是否为捐赠者 |
| `donorUntil` | string\|null | 捐赠到期时间 |
| `warned` | boolean | 是否被警告 |
| `warnedUntil` | string\|null | 警告到期时间 |
| `leechWarn` | boolean | 是否因吸血被警告 |
| `leechWarnUntil` | string\|null | 吸血警告到期时间 |
| `noad` | boolean | 是否无广告 |
| `noadUntil` | string\|null | 无广告到期时间 |
| `lastLogin` | string\|null | 最后登录时间 |
| `lastBrowse` | string\|null | 最后浏览时间 |
| `lastTracker` | string\|null | 最后 tracker 活动时间 |

### `data.memberCount` — 流量与积分

| 字段 | 类型 | 说明 |
|---|---|---|
| `bonus` | string | 魔力值（小数，如 `"109387.6"`） |
| `uploaded` | string | 总上传量（字节） |
| `downloaded` | string | 总下载量（字节） |
| `shareRate` | string | 分享率 |
| `charity` | string | 慈善/捐赠积分 |
| `uploadReset` | string | 上传重置次数 |

**分享率计算**：`16449805409136 / 2017218865545 ≈ 8.155`，与返回的 `shareRate` 一致。

### `data.config` — 用户配置

| 字段 | 类型 | 说明 |
|---|---|---|
| `trackerDomain` | string\|null | 自定义 tracker 域名 |
| `downloadDomain` | string\|null | 自定义下载域名 |
| `rssDomain` | string\|null | 自定义 RSS 域名 |
| `blockCategories` | array | 屏蔽的分类 ID 列表 |
| `hideFun` | boolean | 隐藏趣味盒 |
| `showThumbnail` | boolean | 显示缩略图 |
| `timeType` | string | 时间显示类型（如 `"timeAlive"`） |
| `trackerDisableSeedbox` | boolean | Tracker 禁用 Seedbox |

### `data.authorities` — 权限列表

字符串数组，包含用户拥有的权限标识。已知值：
- `USER` — 基础用户
- `USER_TORRENT` — 种子相关权限
- `USER_FUN_POST` — 趣味盒发帖
- `USER_STORE` — 商店
- `USER_INVITE_REG` — 邀请注册
- `USER_OFFER_PUBLISH` — 候选发布
- `USER_ACCOUNT_NEVER_DELETE_PACKED` — 账号永不删除（封存）

> **安全提示**：`profile` 端点返回 `email`、`ip`、`releaseCode` 等敏感字段。在 Agent 上下文中使用时务必过滤，不要将敏感信息暴露给 LLM 或日志。

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
