# QBittorrent Agent 能力扩展设计

日期: 2026-06-08

## 概述

将 qBittorrent 的限速、查询、控制等能力暴露为 Agent 工具，同时优化下载体验（预设 category、可选 save_path）。

## 一、Adapter 层新增

`app/adapters/qbittorrent.py` 新增两个方法：

### `set_global_speed_limits(upload_limit=None, download_limit=None) -> dict`

- 设置 qB 全局传输限速
- 参数单位: **bytes/s**，`None` 表示不修改该项
- 返回 `{"ok": True, "upload_limit": ..., "download_limit": ...}`

### `set_torrent_speed_limits(torrent_hash, upload_limit=None, download_limit=None) -> dict`

- 设置单种子传输限速
- 参数单位: **bytes/s**，`None` 表示不修改该项
- 返回 `{"ok": True, "torrent_hash": ..., "upload_limit": ..., "download_limit": ...}`

## 二、新增 Tool 清单

| 工具名 | 类型 | 审批 | 功能 |
|--------|------|------|------|
| `qb_list_torrents` | 只读 | 直接执行 | 查询种子列表 |
| `qb_get_torrent` | 只读 | 直接执行 | 查询单种子详情 |
| `qb_list_categories` | 只读 | 直接执行 | 查询 qB 中已有分类 |
| `qb_control_torrent` | 操作 | 需审批 | pause/resume/recheck/reannounce/delete |
| `qb_set_global_speed` | 操作 | 需审批 | 设置全局上下行限速 |
| `qb_set_torrent_speed` | 操作 | 需审批 | 设置单种子上下行限速 |

### 参数设计

**`qb_list_torrents`**：
- `category` (可选 string) — 按分类筛选
- `tag` (可选 string) — 按标签筛选
- `status_filter` (可选 string) — `downloading`/`seeding`/`paused` 等
- `sort` (可选 string) — 排序字段
- `limit` (可选 int) — 返回条数上限

**`qb_get_torrent`**：
- `torrent_hash` (必填 string)

**`qb_list_categories`**：无参数

**`qb_control_torrent`**：
- `torrent_hash` (必填 string)
- `action` (必填 string) — `pause`/`resume`/`recheck`/`reannounce`/`delete`
- `delete_files` (可选 bool, 默认 false) — 仅 delete 时有效

**`qb_set_global_speed`**：
- `upload_limit` (可选 int, bytes/s)
- `download_limit` (可选 int, bytes/s)

**`qb_set_torrent_speed`**：
- `torrent_hash` (必填 string)
- `upload_limit` (可选 int, bytes/s)
- `download_limit` (可选 int, bytes/s)

## 三、`qb_add_torrent` 修改

| 参数 | 变化 | 说明 |
|------|------|------|
| `torrent_id` | 不变 | 必填 |
| `qb_category` | 改为可选 | 预设值: 电影、电视剧、综艺、动漫、纪录片，LLM 自主匹配 |
| `save_path` | 新增 | 可选 string，不传则用 qB 默认路径 |

## 四、Filter / Gate 配置

### Filter（工具白名单）

```python
Filter(allow=[
    "mteam_search",
    "member_profile",
    "qb_add_torrent",
    "qb_list_torrents",
    "qb_get_torrent",
    "qb_list_categories",
    "qb_control_torrent",
    "qb_set_global_speed",
    "qb_set_torrent_speed",
])
```

### Gate（审批规则）

```python
Gate(confirm=[
    lambda call: call.tool_name == "qb_add_torrent",
    lambda call: call.tool_name == "qb_control_torrent",
    lambda call: call.tool_name == "qb_set_global_speed",
    lambda call: call.tool_name == "qb_set_torrent_speed",
])
```

只读工具不加规则 → 自动 `ALLOW`。

## 五、Approval 风险等级

三种风险等级: `READONLY` / `SIDE_EFFECT` / `DESTRUCTIVE`

| 工具 | 风险 | 摘要 |
|------|------|------|
| `qb_add_torrent` | `SIDE_EFFECT` | 提交种子到 qB（暂停状态） |
| `qb_control_torrent` (pause/resume/recheck/reannounce) | `SIDE_EFFECT` | 控制种子操作 |
| `qb_control_torrent` (delete) | `DESTRUCTIVE` | 删除种子及数据 |
| `qb_set_global_speed` | `SIDE_EFFECT` | 修改全局带宽限制 |
| `qb_set_torrent_speed` | `SIDE_EFFECT` | 修改单种子带宽限制 |

`qb_control_torrent` 动态判断风险：`action == "delete"` → `DESTRUCTIVE`，其余 → `SIDE_EFFECT`。

## 六、涉及文件

| 文件 | 变更 |
|------|------|
| `app/adapters/qbittorrent.py` | 新增 `set_global_speed_limits`、`set_torrent_speed_limits` |
| `app/tools/qb_list_torrents.py` | 新增 |
| `app/tools/qb_get_torrent.py` | 新增 |
| `app/tools/qb_list_categories.py` | 新增 |
| `app/tools/qb_control_torrent.py` | 新增 |
| `app/tools/qb_set_global_speed.py` | 新增 |
| `app/tools/qb_set_torrent_speed.py` | 新增 |
| `app/tools/qb_add_torrent.py` | 修改：category 预设值 + save_path |
| `app/tools/__init__.py` | 导出新工具 |
| `app/agent/runner.py` | 注册新工具、更新 Filter/Gate |
| `app/agent/approvals.py` | 动态风险判断支持 |
| `tests/` | 新 adapter 方法 + 新 tool 测试 |
