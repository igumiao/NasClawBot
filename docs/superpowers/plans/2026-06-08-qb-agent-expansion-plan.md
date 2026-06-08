# QBittorrent Agent 能力扩展 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Agent 新增 6 个 qBittorrent 工具（查询/控制/限速），扩展 qb_add_torrent 支持预设 category 和 save_path，并更新 Filter/Gate/Approval 配置。

**Architecture:** 遵循现有三层模式：Adapter 封装 qB API → Tool 封装业务逻辑 → Runner 注册工具并配置 Filter/Gate。每个工具一个独立文件，统一继承 `Tool` 基类。

**Tech Stack:** Python 3, qbittorrentapi, hello_agents Tool/ToolParameter/ToolResponse, pytest + monkeypatch

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `app/adapters/qbittorrent.py` | 修改 | 新增 `set_global_speed_limits`、`set_torrent_speed_limits` |
| `app/tools/qb_list_torrents.py` | 新建 | 查询种子列表工具 |
| `app/tools/qb_get_torrent.py` | 新建 | 查询单种子详情工具 |
| `app/tools/qb_list_categories.py` | 新建 | 查询分类列表工具 |
| `app/tools/qb_control_torrent.py` | 新建 | 种子控制工具（pause/resume/delete 等） |
| `app/tools/qb_set_global_speed.py` | 新建 | 全局限速工具 |
| `app/tools/qb_set_torrent_speed.py` | 新建 | 单种子限速工具 |
| `app/tools/qb_add_torrent.py` | 修改 | category 预设值 + save_path 参数 |
| `app/tools/__init__.py` | 修改 | 导出 6 个新工具 |
| `app/agent/runner.py` | 修改 | 注册新工具、更新 Filter/Gate、更新 system prompt |
| `app/agent/approvals.py` | 修改 | `risk_for_tool()` 支持动态风险判断 |
| `tests/test_qb_adapter.py` | 修改 | 新增 adapter 方法测试 |
| `tests/test_qb_tools.py` | 新建 | 新增工具测试 |

---

### Task 1: Adapter — set_global_speed_limits

**Files:**
- Modify: `app/adapters/qbittorrent.py` (在 `generate_mteam_torrent_name` 之前插入)
- Modify: `tests/test_qb_adapter.py` (在文件末尾追加)

- [ ] **Step 1: 编写 set_global_speed_limits 测试**

在 `tests/test_qb_adapter.py` 末尾追加：

```python
def test_qb_set_global_speed_limits_sets_transfer_properties(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        @property
        def transfer(self):
            return self

        def __setattr__(self, name, value):
            if name in ("upload_limit", "download_limit"):
                captured[name] = value
            else:
                super().__setattr__(name, value)

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.set_global_speed_limits(upload_limit=10485760, download_limit=52428800)

    assert captured.get("upload_limit") == 10485760, "upload_limit should be set on transfer"
    assert captured.get("download_limit") == 52428800, "download_limit should be set on transfer"
    assert result == {"ok": True, "upload_limit": 10485760, "download_limit": 52428800}


def test_qb_set_global_speed_limits_partial_update(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        @property
        def transfer(self):
            return self

        def __setattr__(self, name, value):
            if name in ("upload_limit", "download_limit"):
                captured[name] = value
            else:
                super().__setattr__(name, value)

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.set_global_speed_limits(upload_limit=20971520)

    assert captured.get("upload_limit") == 20971520, "upload_limit should be set"
    assert "download_limit" not in captured, "download_limit should not be set when None"
    assert result == {"ok": True, "upload_limit": 20971520, "download_limit": None}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_adapter.py::test_qb_set_global_speed_limits_sets_transfer_properties tests/test_qb_adapter.py::test_qb_set_global_speed_limits_partial_update -v
```

期望：`AttributeError: 'QBittorrentAdapter' object has no attribute 'set_global_speed_limits'`

- [ ] **Step 3: 实现 set_global_speed_limits**

在 `app/adapters/qbittorrent.py` 的 `generate_mteam_torrent_name` 方法之前插入：

```python
    def set_global_speed_limits(
        self,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Set global transfer speed limits in bytes/s. None means no change."""
        client = self.login()
        if client is None:
            return {"ok": False, "status": "not_configured", "upload_limit": upload_limit, "download_limit": download_limit}

        if upload_limit is not None:
            client.transfer.upload_limit = upload_limit
        if download_limit is not None:
            client.transfer.download_limit = download_limit

        logger.info(
            "qB global speed limits set upload_limit=%s download_limit=%s",
            upload_limit,
            download_limit,
        )
        return {"ok": True, "upload_limit": upload_limit, "download_limit": download_limit}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_adapter.py::test_qb_set_global_speed_limits_sets_transfer_properties tests/test_qb_adapter.py::test_qb_set_global_speed_limits_partial_update -v
```

期望：2 passed

- [ ] **Step 5: Commit**

```bash
git add app/adapters/qbittorrent.py tests/test_qb_adapter.py
git commit -m "feat: add set_global_speed_limits to QBittorrentAdapter"
```

---

### Task 2: Adapter — set_torrent_speed_limits

**Files:**
- Modify: `app/adapters/qbittorrent.py` (在 `set_global_speed_limits` 之后插入)
- Modify: `tests/test_qb_adapter.py` (在末尾追加)

- [ ] **Step 1: 编写 set_torrent_speed_limits 测试**

在 `tests/test_qb_adapter.py` 末尾追加：

```python
def test_qb_set_torrent_speed_limits_sets_per_torrent_limits(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_set_upload_limit(self, **kwargs):
            captured["upload"] = kwargs

        def torrents_set_download_limit(self, **kwargs):
            captured["download"] = kwargs

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.set_torrent_speed_limits(
        torrent_hash="abc123",
        upload_limit=5242880,
        download_limit=20971520,
    )

    assert captured["upload"] == {"torrent_hashes": "abc123", "limit": 5242880}
    assert captured["download"] == {"torrent_hashes": "abc123", "limit": 20971520}
    assert result == {"ok": True, "torrent_hash": "abc123", "upload_limit": 5242880, "download_limit": 20971520}


def test_qb_set_torrent_speed_limits_partial(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_set_upload_limit(self, **kwargs):
            captured["upload"] = kwargs

        def torrents_set_download_limit(self, **kwargs):
            captured["download"] = kwargs

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.set_torrent_speed_limits(torrent_hash="abc123", download_limit=10485760)

    assert "upload" not in captured
    assert captured["download"] == {"torrent_hashes": "abc123", "limit": 10485760}
    assert result == {"ok": True, "torrent_hash": "abc123", "upload_limit": None, "download_limit": 10485760}


def test_qb_set_torrent_speed_limits_rejects_empty_hash():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    with pytest.raises(ValueError, match="torrent_hash must not be empty"):
        adapter.set_torrent_speed_limits(torrent_hash="  ", upload_limit=1024)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_sets_per_torrent_limits tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_partial tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_rejects_empty_hash -v
```

期望：`AttributeError: 'QBittorrentAdapter' object has no attribute 'set_torrent_speed_limits'`

- [ ] **Step 3: 实现 set_torrent_speed_limits**

在 `app/adapters/qbittorrent.py` 的 `set_global_speed_limits` 方法之后插入：

```python
    def set_torrent_speed_limits(
        self,
        torrent_hash: str,
        upload_limit: int | None = None,
        download_limit: int | None = None,
    ) -> dict[str, Any]:
        """Set per-torrent speed limits in bytes/s. None means no change."""
        clean_hash = torrent_hash.strip()
        if not clean_hash:
            raise ValueError("torrent_hash must not be empty")

        client = self.login()
        if client is None:
            return {
                "ok": False,
                "status": "not_configured",
                "torrent_hash": clean_hash,
                "upload_limit": upload_limit,
                "download_limit": download_limit,
            }

        if upload_limit is not None:
            client.torrents_set_upload_limit(torrent_hashes=clean_hash, limit=upload_limit)
        if download_limit is not None:
            client.torrents_set_download_limit(torrent_hashes=clean_hash, limit=download_limit)

        logger.info(
            "qB torrent speed limits set hash=%s upload_limit=%s download_limit=%s",
            clean_hash,
            upload_limit,
            download_limit,
        )
        return {
            "ok": True,
            "torrent_hash": clean_hash,
            "upload_limit": upload_limit,
            "download_limit": download_limit,
        }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_sets_per_torrent_limits tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_partial tests/test_qb_adapter.py::test_qb_set_torrent_speed_limits_rejects_empty_hash -v
```

期望：3 passed

- [ ] **Step 5: Commit**

```bash
git add app/adapters/qbittorrent.py tests/test_qb_adapter.py
git commit -m "feat: add set_torrent_speed_limits to QBittorrentAdapter"
```

---

### Task 3: Tool — qb_list_torrents

**Files:**
- Create: `app/tools/qb_list_torrents.py`
- Create: `tests/test_qb_tools.py` (第一个测试)

- [ ] **Step 1: 编写测试**

新建 `tests/test_qb_tools.py`：

```python
"""Tests for qBittorrent Agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tools.qb_list_torrents import QBListTorrentsTool


def test_qb_list_torrents_returns_serialized_rows():
    qb = MagicMock()
    qb.list_torrents.return_value = [
        {
            "hash": "abc123",
            "name": "Dune Part Two",
            "category": "movie",
            "tags": ["mteam"],
            "state": "downloading",
            "progress": 0.75,
            "download_speed": 10485760,
            "upload_speed": 524288,
            "eta": 1800,
            "save_path": "/downloads/movie",
            "size": 123456,
            "total_size": 654321,
        }
    ]

    tool = QBListTorrentsTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert len(response.data["torrents"]) == 1
    assert response.data["torrents"][0]["hash"] == "abc123"


def test_qb_list_torrents_forwards_filters():
    qb = MagicMock()
    qb.list_torrents.return_value = []

    tool = QBListTorrentsTool(qb)
    tool.run({"category": "movie", "status_filter": "downloading", "limit": 10})

    qb.list_torrents.assert_called_once_with(
        category="movie", status_filter="downloading", limit=10
    )


def test_qb_list_torrents_parameters():
    qb = MagicMock()
    tool = QBListTorrentsTool(qb)
    params = {p.name: p for p in tool.get_parameters()}

    assert "category" in params
    assert params["category"].required is False
    assert "limit" in params
    assert params["limit"].type == "integer"
    assert params["limit"].required is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_list_torrents'`

- [ ] **Step 3: 实现 QBListTorrentsTool**

新建 `app/tools/qb_list_torrents.py`：

```python
"""QBListTorrentsTool — 查询 qBittorrent 种子列表."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBListTorrentsTool(Tool):
    """Query the qBittorrent torrent list with optional filters."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_list_torrents",
            description="查询 qBittorrent 种子列表，可按分类、标签、状态筛选，支持排序和数量限制",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="category",
                type="string",
                description="按分类筛选，如 movie、tvshow、music",
                required=False,
            ),
            ToolParameter(
                name="tag",
                type="string",
                description="按标签筛选，如 mteam",
                required=False,
            ),
            ToolParameter(
                name="status_filter",
                type="string",
                description="按状态筛选: downloading, seeding, paused, queued, checking, error",
                required=False,
            ),
            ToolParameter(
                name="sort",
                type="string",
                description="排序字段，如 name、size、progress、dlspeed、eta",
                required=False,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="返回条数上限，默认返回全部",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        category = parameters.get("category")
        tag = parameters.get("tag")
        status_filter = parameters.get("status_filter")
        sort = parameters.get("sort")
        limit = parameters.get("limit")

        torrents = self._qb.list_torrents(
            category=category,
            tag=tag,
            status_filter=status_filter,
            sort=sort,
            limit=limit,
        )

        if not torrents:
            return ToolResponse.success(
                text="当前没有符合条件的种子任务。",
                data={"torrents": [], "count": 0},
            )

        return ToolResponse.success(
            text=f"共 {len(torrents)} 个种子任务。",
            data={"torrents": torrents, "count": len(torrents)},
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：3 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_list_torrents.py tests/test_qb_tools.py
git commit -m "feat: add QBListTorrentsTool for querying torrent list"
```

---

### Task 4: Tool — qb_get_torrent

**Files:**
- Create: `app/tools/qb_get_torrent.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_get_torrent import QBGetTorrentTool


def test_qb_get_torrent_returns_detail():
    qb = MagicMock()
    qb.get_torrent.return_value = {
        "hash": "abc123",
        "name": "Dune Part Two",
        "category": "movie",
        "state": "downloading",
        "progress": 0.75,
        "download_speed": 10485760,
        "upload_speed": 524288,
        "save_path": "/downloads/movie",
        "size": 123456,
        "total_size": 654321,
        "comment": "from mteam",
        "share_ratio": 1.5,
    }

    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123"})

    assert response.status.value == "success"
    assert response.data["torrent"]["hash"] == "abc123"
    qb.get_torrent.assert_called_once_with("abc123")


def test_qb_get_torrent_not_found():
    qb = MagicMock()
    qb.get_torrent.return_value = None

    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "missing"})

    assert response.status.value == "error"
    assert response.error.code == "NOT_FOUND"


def test_qb_get_torrent_empty_hash():
    qb = MagicMock()
    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "  "})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_get_torrent_returns_detail tests/test_qb_tools.py::test_qb_get_torrent_not_found tests/test_qb_tools.py::test_qb_get_torrent_empty_hash -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_get_torrent'`

- [ ] **Step 3: 实现 QBGetTorrentTool**

新建 `app/tools/qb_get_torrent.py`：

```python
"""QBGetTorrentTool — 查询单个 qBittorrent 种子详情."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBGetTorrentTool(Tool):
    """Query detailed information for a single qBittorrent torrent."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_get_torrent",
            description="查询单个 qBittorrent 种子的详细信息，包括进度、速度、保存路径、分享率等",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_hash",
                type="string",
                description="种子的 info hash",
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        torrent = self._qb.get_torrent(torrent_hash)
        if torrent is None:
            return ToolResponse.error(
                code="NOT_FOUND",
                message=f"未找到种子: {torrent_hash}",
            )

        return ToolResponse.success(
            text=f"种子详情: {torrent.get('name', torrent_hash)}",
            data={"torrent": torrent},
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：6 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_get_torrent.py tests/test_qb_tools.py
git commit -m "feat: add QBGetTorrentTool for single torrent detail"
```

---

### Task 5: Tool — qb_list_categories

**Files:**
- Create: `app/tools/qb_list_categories.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_list_categories import QBListCategoriesTool


def test_qb_list_categories_returns_categories():
    qb = MagicMock()
    qb.list_categories.return_value = {
        "movie": {"savePath": "/downloads/movie"},
        "tvshow": {"savePath": "/downloads/tvshow"},
    }

    tool = QBListCategoriesTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert len(response.data["categories"]) == 2
    assert "movie" in response.data["categories"]


def test_qb_list_categories_empty():
    qb = MagicMock()
    qb.list_categories.return_value = {}

    tool = QBListCategoriesTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert response.data["categories"] == {}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_list_categories_returns_categories tests/test_qb_tools.py::test_qb_list_categories_empty -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_list_categories'`

- [ ] **Step 3: 实现 QBListCategoriesTool**

新建 `app/tools/qb_list_categories.py`：

```python
"""QBListCategoriesTool — 查询 qBittorrent 分类列表."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBListCategoriesTool(Tool):
    """List all categories configured in qBittorrent."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_list_categories",
            description="查询 qBittorrent 中已有的所有分类及其保存路径",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        categories = self._qb.list_categories()
        if not categories:
            return ToolResponse.success(
                text="qBittorrent 中暂无分类。",
                data={"categories": {}},
            )

        names = list(categories.keys())
        return ToolResponse.success(
            text=f"qBittorrent 中共有 {len(names)} 个分类: {', '.join(names)}",
            data={"categories": categories},
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：8 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_list_categories.py tests/test_qb_tools.py
git commit -m "feat: add QBListCategoriesTool for listing qB categories"
```

---

### Task 6: Tool — qb_control_torrent

**Files:**
- Create: `app/tools/qb_control_torrent.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_control_torrent import QBControlTorrentTool


def test_qb_control_torrent_pause():
    qb = MagicMock()
    qb.control_torrent.return_value = {"ok": True, "status": "pause", "qb_hash": "abc123"}

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "pause"})

    assert response.status.value == "success"
    qb.control_torrent.assert_called_once_with("abc123", action="pause", delete_files=False)


def test_qb_control_torrent_delete_with_files():
    qb = MagicMock()
    qb.control_torrent.return_value = {"ok": True, "status": "delete", "qb_hash": "abc123"}

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "delete", "delete_files": True})

    assert response.status.value == "success"
    qb.control_torrent.assert_called_once_with("abc123", action="delete", delete_files=True)


def test_qb_control_torrent_invalid_action():
    qb = MagicMock()
    qb.control_torrent.side_effect = ValueError("Unsupported torrent action: invalid")

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "invalid"})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"


def test_qb_control_torrent_empty_hash():
    qb = MagicMock()
    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "  ", "action": "pause"})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_control_torrent_pause tests/test_qb_tools.py::test_qb_control_torrent_delete_with_files tests/test_qb_tools.py::test_qb_control_torrent_invalid_action tests/test_qb_tools.py::test_qb_control_torrent_empty_hash -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_control_torrent'`

- [ ] **Step 3: 实现 QBControlTorrentTool**

新建 `app/tools/qb_control_torrent.py`：

```python
"""QBControlTorrentTool — 控制 qBittorrent 种子状态（暂停/恢复/删除等）."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter

_VALID_ACTIONS = {"pause", "resume", "recheck", "reannounce", "delete"}


class QBControlTorrentTool(Tool):
    """Control qBittorrent torrent lifecycle: pause, resume, recheck, reannounce, or delete."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_control_torrent",
            description="控制 qBittorrent 种子状态：暂停、恢复、重新校验、重新汇报 tracker、删除",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_hash",
                type="string",
                description="种子的 info hash",
                required=True,
            ),
            ToolParameter(
                name="action",
                type="string",
                description="操作类型",
                required=True,
                enum=list(_VALID_ACTIONS),
            ),
            ToolParameter(
                name="delete_files",
                type="boolean",
                description="删除时是否同时删除文件（仅 action=delete 时有效）",
                required=False,
                default=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        action = str(parameters.get("action", "")).strip().lower()
        delete_files = bool(parameters.get("delete_files", False))

        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        if action not in _VALID_ACTIONS:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"不支持的操作: {action}，支持的操作: {', '.join(sorted(_VALID_ACTIONS))}",
            )

        try:
            result = self._qb.control_torrent(torrent_hash, action=action, delete_files=delete_files)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        if result.get("ok"):
            action_labels = {
                "pause": "已暂停",
                "resume": "已恢复",
                "recheck": "开始重新校验",
                "reannounce": "已重新汇报 tracker",
                "delete": "已删除",
            }
            label = action_labels.get(action, action)
            return ToolResponse.success(
                text=f"种子 {label}: {torrent_hash}",
                data={"result": result},
            )

        return ToolResponse.error(
            code="EXECUTION_FAILED",
            message=f"操作失败: {result.get('status', 'unknown')}",
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：12 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_control_torrent.py tests/test_qb_tools.py
git commit -m "feat: add QBControlTorrentTool for torrent lifecycle control"
```

---

### Task 7: Tool — qb_set_global_speed

**Files:**
- Create: `app/tools/qb_set_global_speed.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_set_global_speed import QBSetGlobalSpeedTool


def test_qb_set_global_speed_both_limits():
    qb = MagicMock()
    qb.set_global_speed_limits.return_value = {"ok": True, "upload_limit": 10485760, "download_limit": 52428800}

    tool = QBSetGlobalSpeedTool(qb)
    response = tool.run({"upload_limit": 10485760, "download_limit": 52428800})

    assert response.status.value == "success"
    qb.set_global_speed_limits.assert_called_once_with(upload_limit=10485760, download_limit=52428800)


def test_qb_set_global_speed_no_params():
    qb = MagicMock()

    tool = QBSetGlobalSpeedTool(qb)
    response = tool.run({})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_set_global_speed_both_limits tests/test_qb_tools.py::test_qb_set_global_speed_no_params -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_set_global_speed'`

- [ ] **Step 3: 实现 QBSetGlobalSpeedTool**

新建 `app/tools/qb_set_global_speed.py`：

```python
"""QBSetGlobalSpeedTool — 设置 qBittorrent 全局传输限速."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBSetGlobalSpeedTool(Tool):
    """Set qBittorrent global upload/download speed limits."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_set_global_speed",
            description="设置 qBittorrent 全局传输限速。上传和下载限制均为可选，单位 bytes/s。例如 10MB/s = 10485760",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="upload_limit",
                type="integer",
                description="全局上传限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
            ToolParameter(
                name="download_limit",
                type="integer",
                description="全局下载限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        upload_limit = parameters.get("upload_limit")
        download_limit = parameters.get("download_limit")

        if upload_limit is None and download_limit is None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="至少需要指定 upload_limit 或 download_limit 之一。",
            )

        result = self._qb.set_global_speed_limits(
            upload_limit=upload_limit,
            download_limit=download_limit,
        )

        if result.get("ok"):
            parts = []
            if upload_limit is not None:
                parts.append(f"上传限速: {upload_limit} bytes/s ({upload_limit / 1048576:.1f} MB/s)")
            if download_limit is not None:
                parts.append(f"下载限速: {download_limit} bytes/s ({download_limit / 1048576:.1f} MB/s)")
            return ToolResponse.success(
                text=f"全局限速已设置: {'，'.join(parts)}",
                data={"result": result},
            )

        return ToolResponse.error(
            code="EXECUTION_FAILED",
            message=f"设置失败: {result.get('status', 'unknown')}",
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：14 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_set_global_speed.py tests/test_qb_tools.py
git commit -m "feat: add QBSetGlobalSpeedTool for global transfer limits"
```

---

### Task 8: Tool — qb_set_torrent_speed

**Files:**
- Create: `app/tools/qb_set_torrent_speed.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_set_torrent_speed import QBSetTorrentSpeedTool


def test_qb_set_torrent_speed_both_limits():
    qb = MagicMock()
    qb.set_torrent_speed_limits.return_value = {
        "ok": True,
        "torrent_hash": "abc123",
        "upload_limit": 5242880,
        "download_limit": 20971520,
    }

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "abc123", "upload_limit": 5242880, "download_limit": 20971520})

    assert response.status.value == "success"
    qb.set_torrent_speed_limits.assert_called_once_with(
        torrent_hash="abc123", upload_limit=5242880, download_limit=20971520
    )


def test_qb_set_torrent_speed_no_limits():
    qb = MagicMock()

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "abc123"})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"


def test_qb_set_torrent_speed_empty_hash():
    qb = MagicMock()
    qb.set_torrent_speed_limits.side_effect = ValueError("torrent_hash must not be empty")

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "  ", "upload_limit": 1024})

    assert response.status.value == "error"
    assert response.error.code == "INVALID_PARAM"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_set_torrent_speed_both_limits tests/test_qb_tools.py::test_qb_set_torrent_speed_no_limits tests/test_qb_tools.py::test_qb_set_torrent_speed_empty_hash -v
```

期望：`ModuleNotFoundError: No module named 'app.tools.qb_set_torrent_speed'`

- [ ] **Step 3: 实现 QBSetTorrentSpeedTool**

新建 `app/tools/qb_set_torrent_speed.py`：

```python
"""QBSetTorrentSpeedTool — 设置单个种子的传输限速."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBSetTorrentSpeedTool(Tool):
    """Set per-torrent upload/download speed limits."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_set_torrent_speed",
            description="设置单个种子的传输限速。上传和下载限制均为可选，单位 bytes/s。例如 10MB/s = 10485760",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_hash",
                type="string",
                description="种子的 info hash",
                required=True,
            ),
            ToolParameter(
                name="upload_limit",
                type="integer",
                description="上传限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
            ToolParameter(
                name="download_limit",
                type="integer",
                description="下载限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        upload_limit = parameters.get("upload_limit")
        download_limit = parameters.get("download_limit")

        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        if upload_limit is None and download_limit is None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="至少需要指定 upload_limit 或 download_limit 之一。",
            )

        try:
            result = self._qb.set_torrent_speed_limits(
                torrent_hash=torrent_hash,
                upload_limit=upload_limit,
                download_limit=download_limit,
            )
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        if result.get("ok"):
            parts = []
            if upload_limit is not None:
                parts.append(f"上传限速: {upload_limit} bytes/s ({upload_limit / 1048576:.1f} MB/s)")
            if download_limit is not None:
                parts.append(f"下载限速: {download_limit} bytes/s ({download_limit / 1048576:.1f} MB/s)")
            return ToolResponse.success(
                text=f"种子 {torrent_hash} 限速已设置: {'，'.join(parts)}",
                data={"result": result},
            )

        return ToolResponse.error(
            code="EXECUTION_FAILED",
            message=f"设置失败: {result.get('status', 'unknown')}",
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：17 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/qb_set_torrent_speed.py tests/test_qb_tools.py
git commit -m "feat: add QBSetTorrentSpeedTool for per-torrent speed limits"
```

---

### Task 9: 修改 qb_add_torrent — 预设 category + save_path

**Files:**
- Modify: `app/tools/qb_add_torrent.py`
- Modify: `tests/test_qb_tools.py` (追加)

- [ ] **Step 1: 编写测试**

在 `tests/test_qb_tools.py` 末尾追加：

```python
from app.tools.qb_add_torrent import QBAddTorrentTool


def test_qb_add_torrent_category_optional_with_presets():
    """qb_category should be optional with preset enum values."""
    tool = QBAddTorrentTool(MagicMock(), MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert params["qb_category"].required is False
    assert params["qb_category"].enum == ["电影", "电视剧", "综艺", "动漫", "纪录片"]


def test_qb_add_torrent_has_save_path_param():
    """save_path should be an optional new parameter."""
    tool = QBAddTorrentTool(MagicMock(), MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert "save_path" in params
    assert params["save_path"].required is False
    assert params["save_path"].type == "string"


def test_qb_add_torrent_passes_save_path_to_adapter():
    """save_path should be forwarded to the adapter's add_torrent_url."""
    mteam = MagicMock()
    mteam.get_torrent_details.return_value = {"title": "Test Movie", "smallDescr": "1080p"}
    mteam.get_torrent_download_url.return_value = "https://example.com/dl/token"
    mteam.is_download_url_torrent.return_value = True

    qb = MagicMock()
    qb.generate_mteam_torrent_name.return_value = "[123][电影][Test.Movie]"
    qb.add_torrent_url.return_value = {"ok": True, "status": "submitted_paused", "qb_hash": None}

    tool = QBAddTorrentTool(mteam, qb)

    response = tool.run({
        "torrent_id": "123",
        "qb_category": "电影",
        "save_path": "/downloads/movies",
    })

    assert response.status.value == "success"

    # Verify save_path was forwarded in the add_torrent_url call
    call_kwargs = qb.add_torrent_url.call_args.kwargs
    assert call_kwargs.get("save_path") == "/downloads/movies"


def test_qb_add_torrent_default_category_when_omitted():
    """When category is omitted, should still proceed."""
    mteam = MagicMock()
    mteam.get_torrent_details.return_value = {"title": "Test"}
    mteam.get_torrent_download_url.return_value = "https://example.com/dl/token"
    mteam.is_download_url_torrent.return_value = True

    qb = MagicMock()
    qb.generate_mteam_torrent_name.return_value = "[123][other][Test]"
    qb.add_torrent_url.return_value = {"ok": True, "status": "submitted_paused", "qb_hash": None}

    tool = QBAddTorrentTool(mteam, qb)
    response = tool.run({"torrent_id": "123"})

    # Should succeed even without explicit category
    assert response.status.value == "success"
    # Category should not be in the payload when omitted
    call_kwargs = qb.add_torrent_url.call_args.kwargs
    assert call_kwargs.get("category") == ""
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py::test_qb_add_torrent_category_optional_with_presets tests/test_qb_tools.py::test_qb_add_torrent_has_save_path_param tests/test_qb_tools.py::test_qb_add_torrent_passes_save_path_to_adapter tests/test_qb_tools.py::test_qb_add_torrent_default_category_when_omitted -v
```

期望：`AssertionError` — category required=True 或缺少 save_path 或缺少 enum

- [ ] **Step 3: 修改 QBAddTorrentTool**

修改 `app/tools/qb_add_torrent.py` 的 `get_parameters()` 和 `run()` 方法。

`get_parameters()` 替换为：

```python
    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_id",
                type="string",
                description="M-Team torrent ID",
                required=True,
            ),
            ToolParameter(
                name="qb_category",
                type="string",
                description="qBittorrent 分类名称。从预设中选择最适合的分类",
                required=False,
                enum=["电影", "电视剧", "综艺", "动漫", "纪录片"],
            ),
            ToolParameter(
                name="save_path",
                type="string",
                description="自定义保存路径（可选）。不传则使用 qBittorrent 默认路径",
                required=False,
            ),
        ]
```

`run()` 方法中，将 `qb_category = str(parameters.get("qb_category", ""))` 保持不变（已正确），在 `self._qb.add_torrent_url(...)` 调用中添加 `save_path` 参数。

将 `add_torrent_url` 调用块替换为：

```python
        add_kwargs: dict[str, Any] = {
            "url": download_url,
            "category": qb_category,
            "rename": rename,
            "tags": ["mteam"],
            "paused": True,
        }
        save_path = str(parameters.get("save_path", "")).strip()
        if save_path:
            add_kwargs["save_path"] = save_path

        add_result = self._qb.add_torrent_url(**add_kwargs)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：21 passed

- [ ] **Step 5: 修改 adapter 支持 category 可选 + save_path 透传**

两个修改点：

**a) `build_add_payload` — 允许 category 为空：**

将 `if not clean_category: raise ValueError(...)` 替换为仅在非空时加入 payload：

```python
        payload: dict[str, Any] = {
            "urls": clean_url,
            "rename": clean_rename,
            "is_paused": paused,
        }
        if clean_category:
            payload["category"] = clean_category
        if clean_tags:
            payload["tags"] = clean_tags
        return payload
```

**b) `add_torrent_url` — 签名添加 `**extra_kwargs` 透传：**

```python
    def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
        **extra_kwargs: Any,
    ) -> dict[str, Any]:
```

在 `payload = self.build_add_payload(...)` 之后，`logger.info(...)` 之前添加：

```python
        payload.update(extra_kwargs)
```

同时更新对应的 adapter 测试，确保 `build_add_payload` 不再对空 category 抛异常。

- [ ] **Step 6: 更新 adapter 测试**

`test_qb_add_payload_rejects_empty_url` 测试仍需确保空 URL 被拒绝。新增一个测试确认空 category 不再抛异常：

```python
def test_qb_add_payload_allows_empty_category():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    payload = adapter.build_add_payload(
        url="https://download.local/token",
        category="",
        rename="[123] Dune",
    )

    assert "category" not in payload, "empty category should be omitted from payload"
    assert payload["urls"] == "https://download.local/token"
```

- [ ] **Step 7: 编译检查 + 运行全量 adapter 测试**

```bash
.venv/bin/python -m compileall app/adapters/qbittorrent.py -q
.venv/bin/python -m pytest tests/test_qb_adapter.py -v
```

期望：全部通过

- [ ] **Step 8: Commit**

```bash
git add app/tools/qb_add_torrent.py app/adapters/qbittorrent.py tests/test_qb_tools.py tests/test_qb_adapter.py
git commit -m "feat: add preset categories and save_path to qb_add_torrent"
```

---

### Task 10: 更新 tools/__init__.py 导出

**Files:**
- Modify: `app/tools/__init__.py`

- [ ] **Step 1: 更新导出**

将 `app/tools/__init__.py` 替换为：

```python
"""NasClawBot tool wrappers.

Each tool wraps an existing adapter operation behind the Tool protocol.
"""

from app.tools.member_profile import MemberProfileTool
from app.tools.mteam_search import MTeamSearchTool
from app.tools.qb_add_torrent import QBAddTorrentTool
from app.tools.qb_list_torrents import QBListTorrentsTool
from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_categories import QBListCategoriesTool
from app.tools.qb_control_torrent import QBControlTorrentTool
from app.tools.qb_set_global_speed import QBSetGlobalSpeedTool
from app.tools.qb_set_torrent_speed import QBSetTorrentSpeedTool

__all__ = [
    "MemberProfileTool",
    "MTeamSearchTool",
    "QBAddTorrentTool",
    "QBListTorrentsTool",
    "QBGetTorrentTool",
    "QBListCategoriesTool",
    "QBControlTorrentTool",
    "QBSetGlobalSpeedTool",
    "QBSetTorrentSpeedTool",
]
```

- [ ] **Step 2: 验证导入**

```bash
.venv/bin/python -c "from app.tools import QBListTorrentsTool, QBGetTorrentTool, QBListCategoriesTool, QBControlTorrentTool, QBSetGlobalSpeedTool, QBSetTorrentSpeedTool; print('OK')"
```

期望：`OK`

- [ ] **Step 3: Commit**

```bash
git add app/tools/__init__.py
git commit -m "feat: export new qB tools from __init__"
```

---

### Task 11: 更新 runner.py — Filter / Gate / 工具注册 / system prompt

**Files:**
- Modify: `app/agent/runner.py`

- [ ] **Step 1: 更新 import**

将第 24 行的 import 替换为：

```python
from app.tools import (
    MemberProfileTool,
    MTeamSearchTool,
    QBAddTorrentTool,
    QBListTorrentsTool,
    QBGetTorrentTool,
    QBListCategoriesTool,
    QBControlTorrentTool,
    QBSetGlobalSpeedTool,
    QBSetTorrentSpeedTool,
)
```

- [ ] **Step 2: 更新 Filter 默认值**

将第 122 行替换为：

```python
        self.tool_filter = tool_filter or Filter(allow=[
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

- [ ] **Step 3: 更新 Gate 默认值**

将第 123 行替换为：

```python
        self.tool_gate = tool_gate or Gate(confirm=[
            lambda call: call.tool_name == "qb_add_torrent",
            lambda call: call.tool_name == "qb_control_torrent",
            lambda call: call.tool_name == "qb_set_global_speed",
            lambda call: call.tool_name == "qb_set_torrent_speed",
        ])
```

- [ ] **Step 4: 在 `_build_agent()` 中注册新工具**

在 `_build_agent()` 方法中，`registry.register_tool(QBAddTorrentTool(...))` 之后追加：

```python
        registry.register_tool(QBListTorrentsTool(qb_adapter))
        registry.register_tool(QBGetTorrentTool(qb_adapter))
        registry.register_tool(QBListCategoriesTool(qb_adapter))
        registry.register_tool(QBControlTorrentTool(qb_adapter))
        registry.register_tool(QBSetGlobalSpeedTool(qb_adapter))
        registry.register_tool(QBSetTorrentSpeedTool(qb_adapter))
```

- [ ] **Step 6: 通用化 `_execute_approved_tool` — 支持所有操作类工具**

替换第 402-415 行的 `_execute_approved_tool` 方法：

```python
    def _execute_approved_tool(self, approval: ApprovalRecord) -> ToolResponse:
        settings = get_settings()
        qb_adapter = self.qb_adapter_factory(
            base_url=settings.qb_base_url,
            username=settings.qb_username,
            password=settings.qb_password,
        )

        tool_name = approval.tool_name
        if tool_name == "qb_add_torrent":
            tool = QBAddTorrentTool(
                self.mteam_adapter_factory(
                    base_url=settings.mteam_base_url,
                    api_key=settings.mteam_api_key,
                ),
                qb_adapter,
            )
        elif tool_name == "qb_control_torrent":
            tool = QBControlTorrentTool(qb_adapter)
        elif tool_name == "qb_set_global_speed":
            tool = QBSetGlobalSpeedTool(qb_adapter)
        elif tool_name == "qb_set_torrent_speed":
            tool = QBSetTorrentSpeedTool(qb_adapter)
        else:
            raise ValueError(f"Cannot execute tool: {tool_name}")

        return tool.run_with_timing(dict(approval.arguments))
```

并将第 235-236 行的硬编码检查替换为通用检查：

```python
        _EXECUTABLE_TOOLS = {"qb_add_torrent", "qb_control_torrent", "qb_set_global_speed", "qb_set_torrent_speed"}
        if approval.tool_name not in _EXECUTABLE_TOOLS:
            raise ValueError(f"Tool '{approval.tool_name}' cannot be executed via approval")
```

- [ ] **Step 7: 更新 system prompt**

修改 `AGENT_SESSION_PROMPT`，在末尾（"回答要简洁"之前）添加新工具的使用指引。将当前 prompt 的最后一段替换为包含新工具的版本。

找到 prompt 中 `qb_add_torrent` 相关行（约第 61-66 行），替换为：

```python
AGENT_SESSION_PROMPT = f"""你是 NasClawBot 的媒体搜索和下载助手。你由 DeepSeek 大语言模型驱动。

你可以使用 mteam_search 搜索候选资源。
mteam_search 默认按最新发布排序；用户明确要求电影、电视剧或音乐时，分别使用 movie、tvshow、music 模式。
用户偏好较小或较大的资源时，分别使用 smallest、largest 排序；用户偏好做种人数多时，使用 most_seeded 排序。
如果已经知道准确的 IMDb 或豆瓣 ID，可以用它缩小搜索范围。优惠状态由搜索结果返回，仅作为候选信息，不作为搜索条件。
当用户询问上传量、下载量、分享率、最近登录时间等个人数据时，可以调用 member_profile 查询。
当用户明确要求下载某个 M-Team torrent id 或上一轮候选资源时，可以调用 qb_add_torrent 提出下载请求。
qb_add_torrent 会先等待用户确认；在用户确认前，不要声称已经下载或已经提交到 qBittorrent。
只有后端审批执行返回成功结果后，才能说下载任务已经提交。

你也可以管理 qBittorrent 中的下载任务：
- 查询种子列表: qb_list_torrents（支持按分类、标签、状态筛选）
- 查看种子详情: qb_get_torrent
- 查看分类: qb_list_categories
- 控制种子: qb_control_torrent（暂停、恢复、重新校验、重新汇报 tracker、删除）
- 全局限速: qb_set_global_speed
- 单种子限速: qb_set_torrent_speed
操作类工具（控制、限速、删除）会等待用户确认后才执行。

如果用户追问上一轮搜索结果，可以结合当前会话历史回答。
当需要搜索时，调用 mteam_search；当需要查询数据时，调用 member_profile；当用户明确要求下载时，调用 qb_add_torrent；当需要管理 qB 任务时，调用对应的 qb_* 工具；当已有信息足够时，直接回答。
回答要简洁，并优先列出标题、分辨率、做种数、大小、优惠状态和 M-Team torrent id。
"""
```

- [ ] **Step 8: 验证编译**

```bash
.venv/bin/python -m compileall app/agent/runner.py -q
```

- [ ] **Step 9: Commit**

```bash
git add app/agent/runner.py
git commit -m "feat: register new qB tools, update Filter/Gate/prompt in runner"
```

---

### Task 12: 更新 approvals.py — 动态风险判断

**Files:**
- Modify: `app/agent/approvals.py`

- [ ] **Step 1: 修改 `risk_for_tool` 支持参数**

将 `risk_for_tool` 函数替换为：

```python
def risk_for_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> ApprovalRisk:
    if tool_name == "qb_add_torrent":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Submit torrent to qBittorrent in paused state",
        )
    if tool_name == "qb_control_torrent":
        action = (arguments or {}).get("action", "")
        if action == "delete":
            return ApprovalRisk(
                level=ApprovalRiskLevel.DESTRUCTIVE,
                summary="Delete torrent and optionally its files from qBittorrent",
            )
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary=f"Control torrent: {action or 'unknown'}",
        )
    if tool_name == "qb_set_global_speed":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Modify global transfer speed limits",
        )
    if tool_name == "qb_set_torrent_speed":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Modify per-torrent speed limits",
        )
    return ApprovalRisk(
        level=ApprovalRiskLevel.SIDE_EFFECT,
        summary="Execute a side-effect tool",
    )
```

- [ ] **Step 2: 检查调用点是否需要传入 arguments**

检查 `runner.py` 中所有调用 `risk_for_tool()` 的地方，确认是否需要传入 `arguments`。

在 runner.py 中搜索 `risk_for_tool`。根据代码，它出现在创建 `create_pending_approval` 的调用链中。需要确认 Gate 的 `ToolCall` 包含 `params`，并在调用 `risk_for_tool` 时传入。

在 runner.py 的 `_create_approval_from_tool_call` 或等效位置（约在 ToolCallingLoop 中暂停时），确保 `risk_for_tool(tool_name, arguments=params)` 传入了参数。

（如果 `risk_for_tool` 的调用在 `ToolCallingLoop` 内部或 `hello_agents` 库中不可修改，则保持 `arguments` 参数为可选，`qb_control_torrent` 在无 arguments 时默认 `SIDE_EFFECT`，这已经是兼容行为。）

- [ ] **Step 3: 验证编译和导入**

```bash
.venv/bin/python -m compileall app/agent/approvals.py -q
.venv/bin/python -c "from app.agent.approvals import risk_for_tool, ApprovalRiskLevel; r = risk_for_tool('qb_control_torrent', {'action': 'delete'}); assert r.level == ApprovalRiskLevel.DESTRUCTIVE; print('OK')"
```

期望：`OK`

- [ ] **Step 4: Commit**

```bash
git add app/agent/approvals.py
git commit -m "feat: add dynamic risk assessment for new qB tools"
```

---

### Task 13: 运行全量测试验证

**Files:** (无修改，仅验证)

- [ ] **Step 1: 运行 adapter 测试**

```bash
.venv/bin/python -m pytest tests/test_qb_adapter.py -v
```

期望：全部通过（含新增的 5 个测试）

- [ ] **Step 2: 运行工具测试**

```bash
.venv/bin/python -m pytest tests/test_qb_tools.py -v
```

期望：21 passed

- [ ] **Step 3: 运行全量测试**

```bash
.venv/bin/python -m pytest -q
```

期望：全部通过，无回归

- [ ] **Step 4: Python 编译检查**

```bash
.venv/bin/python -m compileall app hello_agents -q
```

期望：无报错

- [ ] **Step 5: Commit（如有必要）**

```bash
git add -A
git commit -m "chore: verify full test suite passes after qB expansion"
```
