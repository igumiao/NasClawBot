# M-Team Genie 中“搜索资源并下载”的实现分析

## 目标

这份文档用于拆解 `telegram/mt_helper.py` 里最关键的一条链路：

`搜索关键词 -> 展示资源结果 -> 选择资源 -> 选择下载分类 -> 交给 qBittorrent 下载`

适合给另一个项目里的 Codex 当参考资料，用来复用它的设计思路，而不是逐行照搬代码。

## 先说结论

这个项目的核心思路不是“机器人自己把 `.torrent` 文件下载到本地再上传给下载器”，而是：

1. 用 M-Team API 搜索资源。
2. 从搜索结果里拿到 `torrent id`。
3. 再用 M-Team API 为这个 `id` 生成一次性下载 URL。
4. 把这个 URL 直接交给 qBittorrent Web API 的 `torrents_add(urls=...)`。

也就是说，`Telegram Bot` 更像是一个“编排层 / 交互层”，真正的下载动作由 qBittorrent 执行。

## 核心代码位置

主要都在 [`telegram/mt_helper.py`](/D:/Agent/MTeam-Genie/telegram/mt_helper.py)：

- `MTeamManager`：封装 M-Team API
  - `get_torrent_details()` 约第 150 行
  - `get_torrent_download_url()` 约第 169 行
  - `search_torrents_by_keyword()` 约第 200 行
- `generate_qb_torrent_name_for_mt()`：生成 qB 里的任务名，约第 265 行
- `QBittorrentManager.add_mteam_torrent()`：真正把资源加入 qB，约第 499 行
- `display_search_results_page()`：搜索并展示结果，约第 1195 行
- `handle_search_result_selection()`：从搜索结果里选中某个资源，约第 1365 行
- `handle_add_category_selection()`：选完分类后触发真正下载，约第 878 行
- `direct_add_torrent_command()`：跳过搜索、直接按 M-Team ID 下载，约第 1538 行

## 架构分层

它实际上拆成了 3 层：

### 1. 交互层：Telegram 会话状态机

负责和用户对话，记录当前步骤。

典型状态：

- `ASK_SEARCH_KEYWORDS`
- `SHOWING_SEARCH_RESULTS`
- `SELECTING_ADD_CATEGORY`

它通过 `python-telegram-bot` 的 `ConversationHandler` 管理多步流程。

### 2. 站点访问层：`MTeamManager`

只负责调用 M-Team API，不关心 Telegram，也不关心 qBittorrent。

它封装了 3 个关键能力：

- 根据关键词搜索资源
- 根据资源 ID 拉详情
- 根据资源 ID 生成下载 URL

### 3. 下载器适配层：`QBittorrentManager`

只负责和 qBittorrent 通信。

这里最关键的是 `add_mteam_torrent()`，它把上游拿到的 M-Team 资源 ID 转成 qBittorrent 下载任务。

## 搜索到下载的完整调用链

### 1. 用户输入关键词

入口：

- `ask_search_keywords()`
- `received_search_keywords()`

处理方式：

- 用户输入关键词后，代码把它写进 `context.user_data`：
  - `search_keywords`
  - `search_mode`
- 然后进入 `display_search_results_page(update, context, page_num=0)`

这里说明作者把“会话状态”存放在 Telegram 上下文里，而不是数据库里。

### 2. 调用 M-Team 搜索 API

在 `display_search_results_page()` 里，真正的搜索是：

```python
results_data = await asyncio.to_thread(
    mteam_manager.search_torrents_by_keyword,
    keyword=keywords,
    page_number=page_num + 1
)
```

这里用了 `asyncio.to_thread(...)`，因为 `requests` 是阻塞式 HTTP 客户端。作者不想阻塞 Telegram Bot 的事件循环，所以把同步请求丢到线程里执行。

对应的底层 API 在 `MTeamManager.search_torrents_by_keyword()`：

```python
url = f"{self.config.MT_HOST}/api/torrent/search"
payload = {
    "mode": search_mode,
    "keyword": keyword,
    "categories": [],
    "pageNumber": page_number,
    "pageSize": page_size
}
response = self.session.post(url, json=payload, timeout=30)
```

几个要点：

- 认证靠请求头里的 `x-api-key`
- 搜索接口是 `POST /api/torrent/search`
- 请求体是 JSON
- 当前实现没有传具体分类过滤，`categories` 是空数组
- 分页参数由 `pageNumber/pageSize` 控制

### 3. 搜索结果被格式化，而不是原样透传

`search_torrents_by_keyword()` 不直接把 M-Team 原始响应交给 Telegram 层，而是先转成自己的统一结构：

```python
{
  "torrents": [
    {
      "id": "...",
      "name": "...",
      "display_text": "...",
      "api_details": {...}
    }
  ],
  "total_results": ...,
  "current_page_api": ...,
  "total_pages_api": ...
}
```

这一步很重要，因为它把“站点原始数据”和“上层交互要展示的数据”隔开了。

对于 agent 项目来说，这种中间层结构非常值得保留。以后你就算换站点、换下载器，也不需要把 UI 层一起重写。

### 4. 搜索结果页只负责“选资源”，不直接下载

`display_search_results_page()` 会做两件事：

1. 把格式化后的结果存入：

```python
context.user_data["last_search_results"] = results_data
```

2. 为每条结果生成一个按钮：

```python
callback_data=f"{SEARCH_SELECT_PREFIX}{t['id']}"
```

也就是按钮里只放 `M-Team ID`，而不放整份对象。

这是一个很稳妥的设计：

- 回调数据短，适合 Telegram 限制
- 真正的结果详情仍然保存在会话态里
- 后续下载只依赖 `id`，不会和展示文本强耦合

### 5. 用户选中资源后，不是立刻下载，而是先选 qB 分类

入口：

- `handle_search_result_selection()`

它做的事情：

1. 从按钮回调里拿到 `mt_id`
2. 保存到 `context.user_data["add_mt_id"]`
3. 从 `last_search_results` 里反查选中的资源名，只用于提示用户
4. 调用 `_get_category_selection_buttons()`，动态读取 qB 现有分类
5. 让用户再选一次目标分类

这说明作者把“资源选择”和“下载参数选择”拆成了两个阶段。

对 NAS agent 很有参考价值，因为 agent 很可能也需要在这里插入额外决策：

- 下载到哪个目录
- 用哪个下载器
- 是否打标签
- 是否暂停下载
- 是否属于某个媒体库

### 6. 真正的下载发生在 `handle_add_category_selection()`

用户选完分类后，才会进入统一的下载入口：

```python
success, message = await qb_manager.add_mteam_torrent(mt_id, selected_category)
```

也就是说：

- 从搜索结果点下载
- 从手动输入 ID 添加

最后都会汇合到 `QBittorrentManager.add_mteam_torrent()`

这也是这个文件里最值得迁移的设计之一：把“多种入口”统一收口到一个下载编排函数。

## `add_mteam_torrent()` 的关键步骤

### 1. 先查详情，不直接下载

第一步不是拿下载链接，而是：

```python
api_details = await asyncio.to_thread(self.mteam_manager.get_torrent_details, mteam_id_str)
```

调用：

- `POST /api/torrent/detail`

原因很明显：

- 用于校验这个 ID 是否有效
- 取标题信息，后续生成 qB 任务名
- 给用户返回更友好的提示文案

### 2. 根据详情生成稳定的 qB 任务名

函数：

- `generate_qb_torrent_name_for_mt()`

它会把任务名整理成类似下面这种结构：

```text
[123456][电视剧][Some.Title.2024]
```

这个命名非常关键，因为后续很多管理动作都依赖它：

- `find_torrent_hash_by_mteam_id()` 通过正则 `^\[(\d+)]` 从任务名里反查 M-Team ID
- 修改分类、删除任务，都是先靠这个映射找到 qB 的 torrent hash

也就是说，这个项目实际上没有额外建“资源站 ID <-> 下载器任务 ID”的数据库，而是把映射编码进任务名里。

这是一个非常轻量、但很实用的设计。

### 3. 再向 M-Team 申请下载 URL

下一步才是：

```python
download_url = await asyncio.to_thread(self.mteam_manager.get_torrent_download_url, mteam_id_str)
```

底层接口：

- `POST /api/torrent/genDlToken`

返回的不是文件内容，而是一个 token 化的下载地址。当前实现又对这个地址做了一次加工：

- 强制 `https=1`
- 根据环境变量设置 `ipv6=1/0`
- 用 `MT_HOST` 的域名信息重组最终 URL

这意味着项目作者希望：

- 下载协议尽量走 HTTPS
- 是否使用 IPv6 由环境变量控制
- 尽量避免接口返回的 URL 与当前站点配置不一致

### 4. 添加前先查重

在真正 `torrents_add` 前，代码会先执行：

```python
existing_hash = await self.find_torrent_hash_by_mteam_id(mteam_id_str)
```

查重方式不是比对下载 URL，也不是比对 infohash，而是：

- 遍历 qB 中现有任务
- 从任务名里解析前缀 `[mteam_id]`
- 如果已经存在相同 ID，就直接返回“已存在”

这是这个项目非常鲜明的取舍：

- 优点：实现简单，不需要额外存表
- 缺点：强依赖命名规范

如果你后面做 NAS agent，希望支持多个下载器或人工改名，建议把这个映射单独存起来，而不是只依赖任务名。

### 5. 最后才调用 qBittorrent Web API 添加任务

真正的下载动作在这里：

```python
res = self.client.torrents_add(
    urls=download_url,
    category=actual_category,
    rename=qb_name,
    tags=self.config.QBIT_DEFAULT_TAGS_FOR_MT,
    paused=False,
    sequential=True,
    first_last_piece_prio=True
)
```

要点：

- 传给 qB 的是 `urls=download_url`
- 没有把 `.torrent` 文件下载到 bot 本地
- 同时设置了：
  - 分类
  - 重命名后的任务名
  - 标签
  - 顺序下载 `sequential=True`
  - 首尾块优先 `first_last_piece_prio=True`

所以“搜索资源然后下载”的本质其实是：

`M-Team 搜索 API + M-Team 下载 token API + qBittorrent Web API`

## 项目里真正可迁移的设计模式

如果你要在 NAS agent 项目里复用，我建议重点参考下面这些模式。

### 1. 搜索和下载严格分层

推荐保留成两个独立动作：

- `search_resources(keyword) -> SearchResult[]`
- `download_resource(resource_id, target_profile)`

不要把“搜到结果后立刻下载”写死在同一个函数里。

### 2. 用统一的资源站抽象，而不是把 Telegram/UI 逻辑写进下载逻辑

可以抽象成：

```text
SiteAdapter
  - search(keyword)
  - get_detail(id)
  - get_download_url(id)
```

当前项目里的 `MTeamManager` 就已经很接近这个抽象了。

### 3. 用统一的下载器抽象

可以抽象成：

```text
DownloaderAdapter
  - list_categories()
  - add_torrent_url(url, category, rename, tags, options)
  - find_by_external_id(external_id)
```

当前项目里的 `QBittorrentManager` 就是 qB 版本的实现。

### 4. 给资源定义稳定的外部 ID

这里的稳定外部 ID 就是 `M-Team torrent id`。

它贯穿了整个流程：

- 搜索结果按钮
- 详情获取
- token 下载链接获取
- 任务命名
- 去重
- 后续修改分类和删除

这点很重要。Agent 项目如果没有这个“统一主键”，后续会很难做可追踪管理。

### 5. 不一定要自己下载 torrent 文件

这个项目最省事的一点就在这里：

- 机器人只负责拿到可下载 URL
- 下载器自己去拉取

对 NAS 场景尤其合适，因为：

- agent 进程不需要缓存 `.torrent` 文件
- 减少中转
- 降低权限和文件管理复杂度

### 6. 会话态只保存最小必要信息

当前代码保存的是：

- `search_keywords`
- `last_search_results`
- `add_mt_id`

这类轻量状态足够支撑多步交互。

如果换成 agent，也可以对应成：

- 当前查询词
- 当前候选列表
- 当前选中的资源 ID
- 当前目标下载配置

## 可直接迁移到 NAS agent 的伪代码

```python
class SiteAdapter:
    def search(self, keyword: str) -> list[dict]:
        ...

    def get_detail(self, resource_id: str) -> dict | None:
        ...

    def get_download_url(self, resource_id: str) -> str | None:
        ...


class DownloaderAdapter:
    def list_categories(self) -> list[str]:
        ...

    def find_by_external_id(self, external_id: str) -> str | None:
        ...

    def add_torrent_url(self, url: str, *, category: str, rename: str, tags: list[str]) -> bool:
        ...


def orchestrate_search_then_download(site, downloader, keyword, category):
    results = site.search(keyword)
    if not results:
        return {"ok": False, "reason": "no_results"}

    chosen = results[0]  # 真实 agent 中应加一层选择逻辑
    resource_id = chosen["id"]

    detail = site.get_detail(resource_id)
    if not detail:
        return {"ok": False, "reason": "detail_failed"}

    existing = downloader.find_by_external_id(resource_id)
    if existing:
        return {"ok": True, "reason": "already_exists", "task_id": existing}

    download_url = site.get_download_url(resource_id)
    if not download_url:
        return {"ok": False, "reason": "download_url_failed"}

    rename = build_task_name(resource_id, detail, category)
    ok = downloader.add_torrent_url(
        download_url,
        category=category,
        rename=rename,
        tags=["PT", "M-Team"]
    )
    return {"ok": ok, "resource_id": resource_id}
```

## 这个实现的优点

- 结构清晰，搜索层、站点 API 层、下载器层分开
- 所有入口最后统一收敛到一个下载函数
- 不需要本地保存 `.torrent` 文件
- 去重、改分类、删除任务都能围绕 `M-Team ID` 统一管理
- 对 Telegram 这种多步交互场景很友好

## 这个实现的局限

也有几个点在新项目里可以升级：

#### 1. 去重强依赖任务命名

当前依赖任务名前缀 `[mteam_id]`。如果用户手动改名，映射就可能失效。

更稳妥的方式：

- 存数据库
- 存 sidecar metadata
- 或用 qB 标签 / 评论字段存外部 ID

#### 2. `requests + asyncio.to_thread` 是够用，但不算最整洁

如果新项目本身是 async 架构，可以考虑：

- 用 `httpx.AsyncClient`
- 让站点访问层完全异步化

#### 3. 搜索结果只做展示，没有抽象成通用领域对象

现在返回结构已经比原始 API 好很多，但仍然偏 UI 展示。新项目可以再抽象成：

- `ResourceSummary`
- `ResourceDetail`
- `DownloadPlan`

#### 4. 缺少持久化任务索引

如果将来要做：

- 历史搜索
- 已下载记录
- 自动归档
- 跨下载器同步

最好把外部资源 ID 和下载器任务 ID 的映射存下来。

## 额外观察

`mteam/brush.py` 里也复用了同样的 M-Team 下载思路：

- `POST /api/torrent/detail`
- `POST /api/torrent/genDlToken`
- 然后调用 qB 的 `torrents_add`

这说明“先拿详情/下载 URL，再交给 qB”不是 `mt_helper.py` 独有技巧，而是这个项目整体在用的通用模式。

## 给另一个项目里的 Codex 的参考结论

如果你要让另一个项目里的 Codex 参考这个思路，可以直接告诉它：

1. 把“资源站适配器”和“下载器适配器”分开。
2. 搜索结果只保留统一字段：`id/title/size/category/status`。
3. 下载时永远以资源站的稳定 `id` 作为主键。
4. 下载不要先把种子文件落地，本地只负责拿 token URL，然后直接交给 NAS 下载器。
5. 所有入口最终汇总到一个统一的 `add_resource_by_id()` 或 `download_resource()` 方法。
6. 最好不要像当前项目一样只靠任务名做映射，新项目建议补一层持久化索引。

## 一句话总结

`telegram/mt_helper.py` 的本质不是“Telegram 搜种脚本”，而是一个围绕 `M-Team ID` 构建的轻量下载编排器：前面负责搜索和选择，后面负责把资源 ID 转成 qBittorrent 可执行的下载任务。
