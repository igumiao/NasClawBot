# M-Team API 实测与接入笔记（NasClawBot）

更新时间：2026-04-25  
适用项目：`D:\Agent\NasClawBot`

这份文档是当前项目的一线实测记录，目标是回答接入实现最关心的问题：

1. `/api/torrent/search`、`/api/torrent/detail`、`/api/torrent/genDlToken` 到底怎么调。
2. 请求体该用 JSON 还是 form-data。
3. 关键字段（`id/title/size/seeders`）真实在哪一层。
4. `genDlToken` 返回的是完整下载链接还是半成品 token。

---

## 1. 一句话结论

标准下载链路是：

`search(JSON) -> 选中 id -> detail(form-data id) -> genDlToken(form-data id) -> qB torrents/add(urls=download_url)`

关键结论：

- `search` 必须走 JSON body。
- `detail` 和 `genDlToken` 必须走 form-data（字段名是 `id`）。
- `x-api-key` 是必需头。
- `genDlToken.data` 返回的是完整可下载 URL，可直接交给 qB。

---

## 2. 端点与请求格式（实测）

| Endpoint | Method | Body 形态 | 结果 |
| --- | --- | --- | --- |
| `/api/torrent/search` | POST | `json=payload` | 成功（`code=0`） |
| `/api/torrent/search` | POST | `data=payload` | 失败（参数错误） |
| `/api/torrent/detail` | POST | `data={"id": "..."}` | 成功（`code=0`） |
| `/api/torrent/detail` | POST | `json={"id": "..."}` | 失败（参数错误） |
| `/api/torrent/genDlToken` | POST | `data={"id": "..."}` | 成功（`code=0`） |
| `/api/torrent/genDlToken` | POST | `json={"id": "..."}` | 失败（参数错误） |

额外注意：

- `detail/genDlToken` 使用 form-data 时，不要强塞 `content-type: application/json`。
- `id` 可传字符串或数字；`tid` 字段名不可替代 `id`。

---

## 3. Header 要求（实测）

必需头：

- `x-api-key: <MTEAM_API_KEY>`

行为：

- 不带 key：`{"code":1,"message":"非法用戶端"}`
- 错 key：`{"code":1,"message":"key無效"}`
- 正确 key：正常返回 `code=0`

---

## 4. 请求体建议（MVP）

### 4.1 Search 最小可用请求体

以下是当前项目推荐的 MVP 搜索体：

```json
{
  "keyword": "dune",
  "pageNumber": 1,
  "pageSize": 10,
  "mode": "normal",
  "visible": 1,
  "categories": []
}
```

说明：

- `keyword` 是核心。
- `pageNumber/pageSize` 建议显式带上，方便前后端行为稳定。
- `mode` 建议固定 `"normal"`。
- `visible=1` 会让结果更贴近期望可见资源。
- `categories` 默认 `[]` 表示不过滤，后续可按媒体类型加过滤。

### 4.2 先不启用的字段

文档里出现的高级筛选字段很多（`imdb`、`douban`、`sources`、`mediums`、`labelsNew`、`sortField` 等），一期先不启用，避免增加不必要不确定性。

---

## 5. 返回结构与字段定位

### 5.1 Search 响应结构（实测）

顶层：

- `code`
- `message`
- `data`

分页：

- `data.pageNumber`
- `data.pageSize`
- `data.total`
- `data.totalPages`

列表：

- `data.data[]`

常用字段：

- `id`
- `name`
- `size`
- `category`

### 5.2 Detail 响应结构（实测）

顶层仍是 `code/message/data`。  
资源活跃信息更稳定地在 `data.status` 下：

- `data.status.seeders`
- `data.status.leechers`
- `data.status.timesCompleted`
- `data.status.discount`

说明：

- 在 `search` 列表里，`seeders/leechers` 常见为 `null`。
- 需要做“速度优先”排序时，应在候选确认前用 `detail` 获取 `status`。

### 5.3 genDlToken 响应结构（实测）

```json
{
  "code": "0",
  "message": "SUCCESS",
  "data": "https://api.m-team.cc/api/rss/dlv2?sign=...&t=...&tid=...&uid=..."
}
```

`data` 是完整下载 URL。实测直接 `GET` 返回：

- `content-type: application/x-bittorrent`
- `content-disposition: attachment; filename="....torrent"`

因此可直接传给 qB 的 `torrents/add`（`urls=...`）。

---

## 6. 实测样例：id = 1172412

`/detail` 返回关键字段：

- `id`: `1172412`
- `name`: `Outlander 2026 S08 Complete 1080p NF WEB-DL H264 DDP5.1-UBWEB`
- `category`: `402`
- `size`: `20895219507`
- `numfiles`: `8`
- `status.seeders`: `18`
- `status.leechers`: `21`
- `status.timesCompleted`: `47`
- `status.discount`: `PERCENT_50`

`/genDlToken` 返回：

- `code`: `0`
- `message`: `SUCCESS`
- `data`: 完整下载 URL（含 `tid=1172412`）

---

## 7. 分类映射（来自可信项目配置）

来源：你提供的 `MTEAM_CATEGORY_DATA`（来自其他项目）。  
这份映射可作为项目内“category id -> 名称”字典基础。

### 7.1 当前项目建议先启用的分类（精简）

优先用于电影/剧集/动漫最小闭环：

| ID | 名称 | 用途建议 |
| --- | --- | --- |
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

### 7.2 完整分类字典（保留原始参考）

```python
MTEAM_CATEGORY_DATA = {
    "100": "电影", "423": "PC游戏", "427": "电子書", "401": "电影-SD", "434": "Music(无损)",
    "403": "影剧-综艺-SD", "404": "纪录", "405": "动画", "407": "运动", "419": "电影-HD",
    "422": "软件", "402": "影剧-综艺-HD", "448": "TV遊戲", "105": "影剧-综艺", "442": "有聲書",
    "438": "影剧-综艺-BD", "444": "紀錄", "451": "教育影片", "406": "演唱", "420": "电影-DVDiSo",
    "435": "影剧-综艺-DVDiSo", "110": "Music", "409": "Misc(其他)", "421": "电影-Blu-Ray",
    "439": "电影-Remux", "447": "遊戲", "449": "動漫", "450": "其他", "115": "AV(有码)",
    "120": "AV(无码)", "445": "IV", "446": "H-ACG", "410": "AV(有码)-HD Censored",
    "429": "AV(无码)-HD Uncensored", "424": "AV(有码)-SD Censored",
    "430": "AV(无码)-SD Uncensored",
    "426": "AV(无码)-DVDiSo Uncensored", "437": "AV(有码)-DVDiSo Censored",
    "431": "AV(有码)-Blu-Ray Censored", "432": "AV(无码)-Blu-Ray Uncensored",
    "436": "AV(网站)-0Day", "425": "IV(写真影集)", "433": "IV(写真图集)", "411": "H-游戏",
    "412": "H-动漫", "413": "H-漫画", "440": "AV(Gay)-HD"
}
```

---

## 8. 对当前代码实现的落地建议（不含改代码）

1. `search` 调用使用 `json=payload`。
2. `detail/genDlToken` 调用使用 `data={"id": ...}`。
3. `x-api-key` 作为唯一必需认证头。
4. `search` 列表主要用 `id/name/size/category`。
5. 速度相关排序尽量使用 `detail.data.status.seeders/leechers`。
6. `genDlToken.data` 直接交给 qB `torrents/add(urls=...)`。

---

## 9. 本文档与参考代码的关系

本笔记参考了：

- `D:\Agent\MTeam-Genie\telegram\mt_helper.py`
- 本项目真实接口实验结果

优先级说明：

- 若“参考代码”与“真实实验结果”冲突，以真实实验为准。

