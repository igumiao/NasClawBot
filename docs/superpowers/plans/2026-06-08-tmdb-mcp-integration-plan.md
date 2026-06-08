# TMDB MCP 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 NasClawBot 引入通用 MCP 客户端能力，首个接入 Laksh-star/mcp-server-tmdb，让 Agent 能查询电影/剧集/演员数据，并将 IMDb ID 桥接到 mteam_search。

**Architecture:** hello_agents/tools/mcp/ 提供框架层 MCP 客户端+桥接（`McpConnection`/`McpPool`/`McpBridgeTool`），app/ 提供配置和生命周期管理。MCP 工具通过 `McpBridgeTool` 包装为 HelloAgents `Tool` 实例，与现有 9 个内置工具在同一 ToolRegistry/Filter/Gate 下运行。

**Tech Stack:** `mcp>=1.8.0` (modelcontextprotocol/python-sdk), `asyncio`, `pytest` + `unittest.mock`

---

### Task 1: 依赖与配置基础

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py:60-82`
- Create: `app/mcp_config.py`
- Modify: `.env` (手动编辑，不在 git 中)

- [ ] **Step 1: 添加 `mcp` 依赖**

```bash
.venv/bin/pip install "mcp>=1.8.0"
```

在 `pyproject.toml` 的 `dependencies` 列表中新增：

```toml
"mcp>=1.8.0,<2.0",
```

- [ ] **Step 2: 添加 `tmdb_api_key` 到 Settings**

在 `app/config.py` 的 `Settings` 类中新增一行字段：

```python
tmdb_api_key: str = Field(default_factory=lambda: _get_env("TMDB_API_KEY", ""))
```

- [ ] **Step 3: 创建 `app/mcp_config.py`**

```python
"""TMDB MCP server 配置 — 本期单 server，后续扩展为 .mcp.json 读取。"""

import logging
from hello_agents.tools.mcp.client import McpServerConfig
from app.config import get_settings

logger = logging.getLogger(__name__)

# 精选注册工具（控制上下文窗口开销）
TMDB_TOOLS_ALLOW = [
    "search_movies",
    "get_movie_details",
    "search_tv_shows",
    "search_person",
    "get_recommendations",
    "get_trending",
]


def load_mcp_servers() -> list[McpServerConfig]:
    """返回本期配置的 MCP server 列表。"""
    settings = get_settings()
    api_key = settings.tmdb_api_key.strip()

    if not api_key:
        logger.info("TMDB_API_KEY 未配置，跳过 TMDB MCP server")
        return []

    return [
        McpServerConfig(
            name="tmdb",
            command="npx",
            args=["-y", "mcp-server-tmdb"],
            env={"TMDB_API_KEY": api_key},
        )
    ]
```

- [ ] **Step 4: 写配置测试**

```bash
mkdir -p tests/test_mcp
```

创建 `tests/test_mcp/__init__.py`（空文件）。

创建 `tests/test_mcp/test_mcp_config.py`：

```python
"""Tests for app.mcp_config."""

from unittest.mock import MagicMock, patch

from app.mcp_config import TMDB_TOOLS_ALLOW, load_mcp_servers


def test_tmdb_tools_allow_is_curated_subset():
    """精选工具只包含 6 个核心工具，控制上下文开销。"""
    assert len(TMDB_TOOLS_ALLOW) == 6
    assert "search_movies" in TMDB_TOOLS_ALLOW
    assert "get_movie_details" in TMDB_TOOLS_ALLOW
    assert "search_tv_shows" in TMDB_TOOLS_ALLOW
    assert "search_person" in TMDB_TOOLS_ALLOW
    assert "get_recommendations" in TMDB_TOOLS_ALLOW
    assert "get_trending" in TMDB_TOOLS_ALLOW


def test_load_mcp_servers_empty_when_no_api_key():
    """无 TMDB_API_KEY 时返回空列表。"""
    with patch("app.mcp_config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(tmdb_api_key="  ")
        result = load_mcp_servers()
        assert result == []


def test_load_mcp_servers_returns_tmdb_config():
    """有 API key 时返回单个 TMDB 配置。"""
    with patch("app.mcp_config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(tmdb_api_key="test-key-123")
        result = load_mcp_servers()
        assert len(result) == 1
        config = result[0]
        assert config.name == "tmdb"
        assert config.command == "npx"
        assert config.args == ["-y", "mcp-server-tmdb"]
        assert config.env == {"TMDB_API_KEY": "test-key-123"}
```

- [ ] **Step 5: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_mcp/test_mcp_config.py -v
```

预期: `ModuleNotFoundError: No module named 'hello_agents.tools.mcp.client'`

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml app/config.py app/mcp_config.py tests/test_mcp/
git commit -m "feat: add mcp dependency, tmdb_api_key setting, and mcp_config"
```

---

### Task 2: hello_agents/tools/mcp/__init__.py

**Files:**
- Create: `hello_agents/tools/mcp/__init__.py`

- [ ] **Step 1: 创建包文件**

```bash
mkdir -p hello_agents/tools/mcp
```

创建 `hello_agents/tools/mcp/__init__.py`：

```python
"""MCP (Model Context Protocol) 客户端与 HelloAgents 桥接层。

提供:
- McpServerConfig / McpToolInfo: 配置与工具元数据
- McpConnection: 单 MCP server 进程生命周期
- McpPool: 多 server 连接池
- McpBridgeTool: MCP 工具 → HelloAgents Tool
- register_mcp_tools(): 一键注册到 ToolRegistry
"""

from .client import McpConnection, McpPool, McpServerConfig, McpToolInfo, McpConnectionError
from .bridge import McpBridgeTool, register_mcp_tools

__all__ = [
    "McpServerConfig",
    "McpToolInfo",
    "McpConnection",
    "McpPool",
    "McpConnectionError",
    "McpBridgeTool",
    "register_mcp_tools",
]
```

- [ ] **Step 2: 提交**

```bash
git add hello_agents/tools/mcp/__init__.py
git commit -m "feat: add hello_agents/tools/mcp package init"
```

---

### Task 3: MCP Client 层

**Files:**
- Create: `hello_agents/tools/mcp/client.py`
- Create: `tests/test_mcp/test_client.py`

- [ ] **Step 1: 创建测试文件，写第一个测试（McpServerConfig 和 McpToolInfo）**

创建 `tests/test_mcp/test_client.py`：

```python
"""Tests for hello_agents.tools.mcp.client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.tools.mcp.client import (
    McpConnection,
    McpConnectionError,
    McpPool,
    McpServerConfig,
    McpToolInfo,
)


# ── McpServerConfig ──────────────────────────

def test_mcp_server_config_defaults():
    config = McpServerConfig(name="test", command="echo", args=["hello"])
    assert config.name == "test"
    assert config.command == "echo"
    assert config.args == ["hello"]
    assert config.env == {}
    assert config.timeout == 30.0


# ── McpToolInfo ──────────────────────────────

def test_mcp_tool_info_stores_schema():
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "搜索关键词"}},
        "required": ["query"],
    }
    info = McpToolInfo(name="search", description="搜索电影", input_schema=schema)
    assert info.name == "search"
    assert info.description == "搜索电影"
    assert info.input_schema == schema


# ── McpConnection.connect ────────────────────

@pytest.mark.asyncio
async def test_connect_discovers_and_caches_tools():
    """connect 调用 list_tools 并缓存结果。"""
    mock_tool = MagicMock()
    mock_tool.name = "search_movies"
    mock_tool.description = "Search movies by title"
    mock_tool.inputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "搜索关键词"}},
        "required": ["query"],
    }

    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=["-y", "mcp-server-tmdb"])
    )

    with patch.object(conn, "_session") as mock_session:
        mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[mock_tool]))
        mock_session.initialize = AsyncMock()

        await conn.connect()

        tools = conn.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "search_movies"
        mock_session.initialize.assert_awaited_once()
        mock_session.list_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_connection_failure_raises():
    """连接失败抛出 McpConnectionError。"""
    conn = McpConnection(
        McpServerConfig(name="bad", command="nonexistent_cmd", args=[])
    )
    with patch("hello_agents.tools.mcp.client.stdio_client") as mock_stdio:
        mock_stdio.side_effect = Exception("command not found")

        with pytest.raises(McpConnectionError, match="Failed to connect"):
            await conn.connect()


# ── McpConnection.call_tool ──────────────────

@pytest.mark.asyncio
async def test_call_tool_delegates_to_session():
    """call_tool 委托给 ClientSession.call_tool。"""
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=["-y", "mcp-server-tmdb"])
    )

    mock_result = MagicMock()
    mock_result.content = [MagicMock(text="results here", type="text")]

    with patch.object(conn, "_session") as mock_session:
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        result = await conn.call_tool("search_movies", {"query": "Inception"})

        assert result is mock_result
        mock_session.call_tool.assert_awaited_once_with(
            "search_movies", {"query": "Inception"}
        )


# ── McpConnection.health ─────────────────────

@pytest.mark.asyncio
async def test_health_true_when_connected():
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    with patch.object(conn, "_session", MagicMock()):
        assert await conn.health() is True


def test_health_false_when_not_connected():
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    # conn._session 为 None（未连接）
    import asyncio
    assert asyncio.run(conn.health()) is False


# ── McpConnection.disconnect ─────────────────

@pytest.mark.asyncio
async def test_disconnect_closes_session():
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    mock_session = MagicMock()
    conn._session = mock_session

    await conn.disconnect()

    assert conn._session is None
    assert conn._tools == []


# ── McpPool.start_all ───────────────────────

@pytest.mark.asyncio
async def test_pool_start_all_connects_all_servers():
    conn1 = McpConnection(
        McpServerConfig(name="a", command="echo", args=[])
    )
    conn2 = McpConnection(
        McpServerConfig(name="b", command="echo", args=[])
    )
    with patch.object(conn1, "connect", AsyncMock()):
        with patch.object(conn2, "connect", AsyncMock()):
            pool = McpPool([conn1, conn2])
            results = await pool.start_all()

            assert results == {"a": True, "b": True}
            conn1.connect.assert_awaited_once()
            conn2.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_start_all_marks_failed():
    conn1 = McpConnection(
        McpServerConfig(name="ok", command="echo", args=[])
    )
    conn2 = McpConnection(
        McpServerConfig(name="bad", command="nonexistent", args=[])
    )
    with patch.object(conn1, "connect", AsyncMock()):
        with patch.object(conn2, "connect", AsyncMock(side_effect=McpConnectionError("fail"))):
            pool = McpPool([conn1, conn2])
            results = await pool.start_all()

            assert results == {"ok": True, "bad": False}


# ── McpPool.get_tools ───────────────────────

def test_pool_get_tools_aggregates_all_connections():
    pool = McpPool([])
    conn = McpConnection(McpServerConfig(name="a", command="echo", args=[]))
    conn._tools = [
        McpToolInfo(name="t1", description="d1", input_schema={}),
        McpToolInfo(name="t2", description="d2", input_schema={}),
    ]
    pool._connections = {"a": conn}

    tools = pool.get_tools()
    assert len(tools) == 2
    assert tools[0] == ("a", conn._tools[0])
    assert tools[1] == ("a", conn._tools[1])


def test_pool_get_tools_filters_by_server():
    pool = McpPool([])
    conn_a = McpConnection(McpServerConfig(name="a", command="echo", args=[]))
    conn_a._tools = [McpToolInfo(name="t1", description="d1", input_schema={})]
    conn_b = McpConnection(McpServerConfig(name="b", command="echo", args=[]))
    conn_b._tools = [McpToolInfo(name="t2", description="d2", input_schema={})]
    pool._connections = {"a": conn_a, "b": conn_b}

    tools = pool.get_tools(server_name="a")
    assert len(tools) == 1
    assert tools[0][0] == "a"


# ── McpPool.call_tool ────────────────────────

@pytest.mark.asyncio
async def test_pool_call_tool_routes_correctly():
    conn = McpConnection(McpServerConfig(name="s1", command="echo", args=[]))
    pool = McpPool([])
    pool._connections = {"s1": conn}

    with patch.object(conn, "call_tool", AsyncMock()) as mock_call:
        await pool.call_tool("s1", "search", {"q": "test"})
        mock_call.assert_awaited_once_with("search", {"q": "test"})


@pytest.mark.asyncio
async def test_pool_call_tool_unknown_server_raises():
    pool = McpPool([])
    with pytest.raises(McpConnectionError, match="not connected"):
        await pool.call_tool("unknown", "search", {})
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_mcp/test_client.py -v
```

预期: `ImportError` — `hello_agents.tools.mcp.client` 模块不存在。

- [ ] **Step 3: 实现 `hello_agents/tools/mcp/client.py`**

```python
"""通用 MCP 客户端 — STDIO transport 封装。

管理 MCP server 子进程生命周期，提供工具发现和调用。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────


@dataclass
class McpServerConfig:
    """一个 MCP server 的连接配置。"""
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class McpToolInfo:
    """MCP 工具元数据（connect 时从 list_tools 获取）。"""
    name: str
    description: str
    input_schema: dict  # JSON Schema


class McpConnectionError(Exception):
    """MCP 连接或调用失败。"""


# ── 单连接 ────────────────────────────────────


class McpConnection:
    """一个 MCP server 子进程的生命周期管理。

    使用 mcp Python SDK 的 stdio_client + ClientSession。
    """

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._context_stack: object | None = None
        self._tools: list[McpToolInfo] = []

    async def connect(self) -> None:
        """启动子进程，建立 STDIO 连接，初始化 session，发现工具。"""
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env,
        )

        try:
            # stdio_client 返回 (read_stream, write_stream) context manager
            # ClientSession 使用这些 streams 进行双向通信
            read, write = await stdio_client(server_params).__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()

            list_result = await session.list_tools()
            self._tools = [
                McpToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                )
                for tool in list_result.tools
            ]

            self._session = session
            self._context_stack = (read, write, session)

            logger.info(
                "MCP server '%s' connected — %d tools discovered",
                self.config.name,
                len(self._tools),
            )
        except Exception as exc:
            raise McpConnectionError(
                f"Failed to connect to MCP server '{self.config.name}': {exc}"
            ) from exc

    async def call_tool(self, name: str, arguments: dict) -> object:
        """调用已连接的 MCP server 上的工具。"""
        if self._session is None:
            raise McpConnectionError(
                f"MCP server '{self.config.name}' is not connected"
            )
        return await self._session.call_tool(name, arguments)

    def list_tools(self) -> list[McpToolInfo]:
        """返回缓存的工具列表（connect 时获取）。"""
        return list(self._tools)

    async def health(self) -> bool:
        """检查连接是否存活。"""
        return self._session is not None

    async def disconnect(self) -> None:
        """关闭 ClientSession 和底层 transport。"""
        if self._context_stack is not None:
            read, write, session = self._context_stack
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await read.aclose()
            except Exception:
                pass
            try:
                await write.aclose()
            except Exception:
                pass
        self._session = None
        self._context_stack = None
        self._tools = []


# ── 连接池 ────────────────────────────────────


class McpPool:
    """管理多个 McpConnection。"""

    def __init__(self, connections: list[McpConnection]) -> None:
        self._connections: dict[str, McpConnection] = {
            c.config.name: c for c in connections
        }

    async def start_all(self) -> dict[str, bool]:
        """并发连接所有 server，返回每 server 成功/失败状态。"""
        coros = {
            name: conn.connect()
            for name, conn in self._connections.items()
        }
        results: dict[str, bool] = {}
        for name, coro in coros.items():
            try:
                await coro
                results[name] = True
            except McpConnectionError as exc:
                logger.warning("MCP server '%s' connection failed: %s", name, exc)
                results[name] = False
        return results

    async def stop_all(self) -> None:
        """关闭所有连接。"""
        for name, conn in self._connections.items():
            try:
                await conn.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting MCP server '%s': %s", name, exc)

    def get_tools(
        self, server_name: str | None = None
    ) -> list[tuple[str, McpToolInfo]]:
        """返回 (server_name, McpToolInfo) 对。

        server_name 不为 None 时只返回该 server 的工具。
        """
        result: list[tuple[str, McpToolInfo]] = []
        for name, conn in self._connections.items():
            if server_name is not None and name != server_name:
                continue
            for tool in conn.list_tools():
                result.append((name, tool))
        return result

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> object:
        """找到对应 connection，调用 tool。"""
        conn = self._connections.get(server_name)
        if conn is None:
            raise McpConnectionError(
                f"MCP server '{server_name}' is not connected"
            )
        return await conn.call_tool(tool_name, arguments)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_mcp/test_client.py -v
```

预期: 全部 13 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add hello_agents/tools/mcp/client.py tests/test_mcp/test_client.py
git commit -m "feat: add MCP client layer — McpConnection, McpPool"
```

---

### Task 4: MCP Bridge 层

**Files:**
- Create: `hello_agents/tools/mcp/bridge.py`
- Create: `tests/test_mcp/test_bridge.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_mcp/test_bridge.py`：

```python
"""Tests for hello_agents.tools.mcp.bridge."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.tools.base import ToolParameter, ToolResponse
from hello_agents.tools.filter import Filter
from hello_agents.tools.gate import Gate
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.mcp.bridge import McpBridgeTool, register_mcp_tools
from hello_agents.tools.mcp.client import McpConnection, McpConnectionError, McpPool, McpServerConfig, McpToolInfo


# ── McpBridgeTool.get_parameters ──────────────

def test_bridge_tool_converts_simple_schema():
    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
        },
        "required": ["query"],
    }
    tool_info = McpToolInfo(name="search", description="搜索电影", input_schema=schema)
    pool = MagicMock(spec=McpPool)
    tool = McpBridgeTool(pool, "tmdb", tool_info)

    params = tool.get_parameters()
    assert len(params) == 1
    assert params[0].name == "query"
    assert params[0].type == "string"
    assert params[0].description == "搜索关键词"
    assert params[0].required is True


def test_bridge_tool_optional_params_not_in_required():
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索"},
            "year": {"type": "integer", "description": "年份"},
        },
        "required": ["query"],
    }
    tool_info = McpToolInfo(name="search", description="搜索", input_schema=schema)
    pool = MagicMock(spec=McpPool)
    tool = McpBridgeTool(pool, "tmdb", tool_info)

    params = tool.get_parameters()
    assert len(params) == 2
    assert {p.name for p in params if p.required} == {"query"}
    assert {p.name for p in params if not p.required} == {"year"}


def test_bridge_tool_naming_convention():
    """命名格式: mcp_{server}_{tool_name}"""
    tool_info = McpToolInfo(name="search_movies", description="d", input_schema={})
    pool = MagicMock(spec=McpPool)
    tool = McpBridgeTool(pool, "tmdb", tool_info)
    assert tool.name == "mcp_tmdb_search_movies"
    assert tool.description == "d"


# ── McpBridgeTool.run (sync) ──────────────────

def test_bridge_tool_run_success():
    pool = MagicMock(spec=McpPool)
    mock_result = MagicMock()
    mock_result.content = [MagicMock(text="movie data here", type="text")]

    async def async_call_tool(*args, **kwargs):
        return mock_result
    pool.call_tool = async_call_tool

    tool_info = McpToolInfo(name="search_movies", description="d", input_schema={
        "type": "object", "properties": {}, "required": [],
    })
    tool = McpBridgeTool(pool, "tmdb", tool_info)
    response = tool.run({})

    assert response.status.value == "success"
    assert "movie data here" in response.text
    assert response.data["server"] == "tmdb"


def test_bridge_tool_run_connection_error():
    pool = MagicMock(spec=McpPool)

    async def raise_error(*args, **kwargs):
        raise McpConnectionError("not connected")
    pool.call_tool = raise_error

    tool_info = McpToolInfo(name="search_movies", description="d", input_schema={
        "type": "object", "properties": {}, "required": [],
    })
    tool = McpBridgeTool(pool, "tmdb", tool_info)
    response = tool.run({})

    assert response.status.value == "error"
    assert "MCP_CONNECTION_ERROR" in response.error.code
    assert "不可用" in response.text


# ── register_mcp_tools ────────────────────────

def test_register_mcp_tools_registers_all():
    pool = MagicMock(spec=McpPool)
    tool_info = McpToolInfo(name="search", description="d", input_schema={"type": "object", "properties": {}, "required": []})
    pool.get_tools.return_value = [("tmdb", tool_info)]

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry)

    assert count == 1
    assert "mcp_tmdb_search" in getattr(registry, "_tools", {})


def test_register_mcp_tools_with_allow_filter():
    pool = MagicMock(spec=McpPool)
    pool.get_tools.return_value = [
        ("tmdb", McpToolInfo(name="search_movies", description="d", input_schema={"type": "object", "properties": {}, "required": []})),
        ("tmdb", McpToolInfo(name="get_trending", description="d", input_schema={"type": "object", "properties": {}, "required": []})),
    ]

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry, allow=["search_movies"])

    assert count == 1
    assert "mcp_tmdb_search_movies" in getattr(registry, "_tools", {})


def test_register_mcp_tools_empty_pool():
    pool = MagicMock(spec=McpPool)
    pool.get_tools.return_value = []

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry)

    assert count == 0


def test_register_mcp_tools_with_tool_filter():
    """传入 tool_filter 时，MCP 工具名自动加入白名单。"""
    pool = MagicMock(spec=McpPool)
    tool_info = McpToolInfo(name="search", description="d", input_schema={"type": "object", "properties": {}, "required": []})
    pool.get_tools.return_value = [("tmdb", tool_info)]

    registry = ToolRegistry()
    tool_filter = Filter(allow=["mteam_search"])

    count = register_mcp_tools(pool, registry, tool_filter=tool_filter)

    assert count == 1
    # 验证 MCP 工具名在 filter 白名单中
    assert tool_filter.apply(["mcp_tmdb_search"]) == ["mcp_tmdb_search"]
```

- [ ] **Step 2: 运行测试验证失败**

```bash
.venv/bin/python -m pytest tests/test_mcp/test_bridge.py -v
```

预期: `ImportError` — `hello_agents.tools.mcp.bridge` 模块不存在。

- [ ] **Step 3: 实现 `hello_agents/tools/mcp/bridge.py`**

```python
"""MCP 工具 → HelloAgents Tool 桥接层。

把 MCP server 发现的每个工具包装为 HelloAgents Tool 实例，
通过 McpPool 统一调用。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging

from hello_agents.tools.base import Tool, ToolParameter, ToolResponse
from hello_agents.tools.filter import Filter
from hello_agents.tools.gate import Gate
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.mcp.client import McpConnectionError, McpPool, McpToolInfo

logger = logging.getLogger(__name__)


class McpBridgeTool(Tool):
    """把单个 MCP 工具包装成 HelloAgents Tool。

    工具命名: mcp_{server_name}_{tool_name}
    """

    def __init__(self, pool: McpPool, server_name: str, tool_info: McpToolInfo) -> None:
        self._pool = pool
        self._server = server_name
        self._tool_info = tool_info
        super().__init__(
            name=f"mcp_{server_name}_{tool_info.name}",
            description=tool_info.description,
        )
        self._parameters = self._parse_schema(tool_info.input_schema)

    def get_parameters(self) -> list[ToolParameter]:
        return self._parameters

    def _parse_schema(self, schema: dict) -> list[ToolParameter]:
        """将 MCP JSON Schema 转换为 ToolParameter 列表。"""
        properties = schema.get("properties", {})
        required_names: set[str] = set(schema.get("required", []))

        params: list[ToolParameter] = []
        for name, prop in properties.items():
            params.append(ToolParameter(
                name=name,
                type=prop.get("type", "string"),
                description=prop.get("description", f"参数 {name}"),
                required=name in required_names,
            ))
        return params

    async def arun(self, parameters: dict) -> ToolResponse:
        """异步原生路径 — FastAPI 上下文走这条。"""
        try:
            result = await self._pool.call_tool(
                self._server, self._tool_info.name, parameters
            )
        except McpConnectionError as e:
            return ToolResponse.error(
                code="MCP_CONNECTION_ERROR",
                message=f"MCP server '{self._server}' 不可用: {e}",
            )
        return self._to_response(result)

    def run(self, parameters: dict) -> ToolResponse:
        """同步回退路径 — 测试或非 async 上下文。"""
        try:
            return asyncio.run(self.arun(parameters))
        except RuntimeError:
            # 已有 running event loop（不应在生产中发生，防御性处理）
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.arun(parameters))
                return future.result()

    @staticmethod
    def _to_response(result: object) -> ToolResponse:
        """从 MCP CallToolResult 提取文本内容。"""
        content = getattr(result, "content", [])
        text_parts = [
            c.text
            for c in content
            if hasattr(c, "text") and getattr(c, "type", None) == "text"
        ]
        structured = getattr(result, "structuredContent", None)
        return ToolResponse.success(
            text="\n".join(text_parts) if text_parts else json.dumps(structured or {}),
            data={"structured": structured},
        )


def register_mcp_tools(
    pool: McpPool,
    registry: ToolRegistry,
    tool_filter: Filter | None = None,
    tool_gate: Gate | None = None,
    allow: list[str] | None = None,
) -> int:
    """从 pool 所有健康连接中收集工具，包装为 McpBridgeTool 并注册。

    Args:
        pool: MCP 连接池
        registry: HelloAgents ToolRegistry
        tool_filter: 如果传入，自动将所有注册的 MCP 工具名加入白名单
        tool_gate: 本期不使用（MCP 工具只读），预留接口
        allow: 按 MCP tool name 筛选，None = 全部注册

    Returns:
        注册的工具数量
    """
    allow_set: set[str] | None = set(allow) if allow is not None else None
    count = 0
    mcp_tool_names: list[str] = []

    for server_name, tool_info in pool.get_tools():
        if allow_set is not None and tool_info.name not in allow_set:
            logger.debug("Skipping MCP tool '%s/%s' (not in allow list)", server_name, tool_info.name)
            continue

        bridge = McpBridgeTool(pool, server_name, tool_info)
        registry.register_tool(bridge)
        mcp_tool_names.append(bridge.name)
        count += 1

    if tool_filter is not None and mcp_tool_names:
        # 将 MCP 工具名加入现有 filter 白名单
        existing = set(tool_filter.apply(list(getattr(registry, "_tools", {}).keys())))
        existing.update(mcp_tool_names)
        tool_filter._predicate = lambda name, s=existing: name in s

    logger.info("Registered %d MCP tools", count)
    return count
```

- [ ] **Step 4: 运行测试验证通过**

```bash
.venv/bin/python -m pytest tests/test_mcp/test_bridge.py -v
```

预期: 全部 8 个测试 PASS。

- [ ] **Step 5: 提交**

```bash
git add hello_agents/tools/mcp/bridge.py tests/test_mcp/test_bridge.py
git commit -m "feat: add MCP bridge — McpBridgeTool, register_mcp_tools"
```

---

### Task 5: App 生命周期 + Runner 集成

**Files:**
- Create: `app/mcp_pool.py` (模块级单例)
- Modify: `app/main.py` (lifespan)
- Modify: `app/api/chat_routes.py` (传递 mcp_pool)
- Modify: `app/agent/runner.py` (接收 mcp_pool, prompt 更新)

- [ ] **Step 1: 创建 `app/mcp_pool.py` 模块级单例**

```python
"""MCP 连接池单例 — 进程级生命周期管理。

startup 时初始化一次，所有请求共享同一个 McpPool。
"""

from __future__ import annotations

import logging

from app.mcp_config import TMDB_TOOLS_ALLOW, load_mcp_servers
from hello_agents.tools.mcp.client import McpConnection, McpPool

logger = logging.getLogger(__name__)

_mcp_pool: McpPool | None = None


def get_mcp_pool() -> McpPool | None:
    """返回已初始化的 McpPool，未初始化返回 None。"""
    return _mcp_pool


async def init_mcp_pool() -> McpPool | None:
    """启动所有 MCP server 连接，设置全局单例。"""
    global _mcp_pool

    configs = load_mcp_servers()
    if not configs:
        logger.info("No MCP servers configured, skipping")
        return None

    connections = [McpConnection(cfg) for cfg in configs]
    _mcp_pool = McpPool(connections)

    results = await _mcp_pool.start_all()
    ok = sum(1 for v in results.values() if v)
    fail = len(results) - ok
    logger.info("MCP pool started: %d ok, %d failed", ok, fail)

    return _mcp_pool


async def shutdown_mcp_pool() -> None:
    """关闭所有 MCP server 连接。"""
    global _mcp_pool
    if _mcp_pool is not None:
        await _mcp_pool.stop_all()
        _mcp_pool = None
        logger.info("MCP pool shut down")
```

- [ ] **Step 2: 修改 `app/main.py` — 添加 lifespan**

```python
"""FastAPI app bootstrap for the current MVP.

This module wires routes and static frontend assets into a single app instance.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat_routes import build_router
from app.config import get_settings
from app.logging_config import configure_logging
from app.mcp_pool import init_mcp_pool, shutdown_mcp_pool


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application lifespan — startup MCP connections, shutdown cleanly."""
    await init_mcp_pool()
    yield
    await shutdown_mcp_pool()


def create_app() -> FastAPI:
    """Create and configure the application object."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, lifespan=_lifespan)

    app.include_router(build_router())

    frontend_dir = _frontend_dir()
    frontend_dist = frontend_dir / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    return app


app = create_app()
```

- [ ] **Step 3: 修改 `app/api/chat_routes.py` — runner 创建时传递 mcp_pool**

修改 `chat_agent` 路由中的 runner 创建（第 124 行附近）：

```python
from app.mcp_pool import get_mcp_pool

# 在 chat_agent 函数中:
runner = NasClawAgentRunner(
    checkpoint_store=_agent_checkpoint_store(),
    mcp_pool=get_mcp_pool(),
)
```

同样修改 `approve_agent` 和 `deny_agent` 路由中的 runner 创建（第 215 和 236 行附近），添加 `mcp_pool=get_mcp_pool()` 参数。

- [ ] **Step 4: 修改 `app/agent/runner.py` — 接收 mcp_pool 并注册 MCP 工具**

在 `NasClawAgentRunner.__init__` 中添加参数：

```python
def __init__(
    self,
    checkpoint_store: ConversationCheckpointStore,
    llm_factory: Callable[..., Any] | None = None,
    mteam_adapter_factory: Callable[..., MTeamAdapter] | None = None,
    qb_adapter_factory: Callable[..., QBittorrentAdapter] | None = None,
    max_steps: int = 4,
    agent_config_overrides: dict[str, Any] | None = None,
    tool_filter: Filter | None = None,
    tool_gate: Gate | None = None,
    approval_summary_enabled: bool = True,
    mcp_pool: Any | None = None,  # ← 新增
):
    ...
    self.mcp_pool = mcp_pool
```

在 `_build_agent` 方法末尾，注册完内置工具后，添加：

```python
# 注册 MCP 工具
if self.mcp_pool:
    from hello_agents.tools.mcp.bridge import register_mcp_tools
    from app.mcp_config import TMDB_TOOLS_ALLOW
    register_mcp_tools(
        self.mcp_pool,
        registry,
        tool_filter=self.tool_filter,
        tool_gate=self.tool_gate,
        allow=TMDB_TOOLS_ALLOW,
    )
```

更新 `AGENT_SESSION_PROMPT`，在现有的 qB 管理段落后新增：

```python
你也可以查询外部影视数据源（通过 MCP 连接 TMDB）:
- 搜索电影/剧集: mcp_tmdb_search_movies, mcp_tmdb_search_tv_shows
- 查看详情: mcp_tmdb_get_movie_details
- 搜索演员/导演: mcp_tmdb_search_person
- 获取推荐: mcp_tmdb_get_recommendations
- 热门趋势: mcp_tmdb_get_trending
这些工具均为只读，直接执行，结果可能包含 IMDb ID，可用于后续 mteam_search 精准搜索。
```

- [ ] **Step 5: 运行全部测试验证**

```bash
.venv/bin/python -m pytest -q
```

预期: 所有已有测试和新增 MCP 测试均 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/mcp_pool.py app/main.py app/api/chat_routes.py app/agent/runner.py
git commit -m "feat: integrate MCP pool into app lifecycle and runner"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 运行完整测试套件**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall app hello_agents -q
```

预期: 所有测试 PASS，编译无错误。

- [ ] **Step 2: 验证服务启动（无 TMDB_API_KEY 场景）**

```bash
.venv/bin/python -c "
from app.main import app
print('App created successfully (MCP skipped gracefully)')
"
```

预期: 输出 "App created successfully..."，日志显示 "TMDB_API_KEY 未配置，跳过 TMDB MCP server"。

- [ ] **Step 3: 提交**

```bash
git commit -m "chore: verify full test suite and graceful MCP skip" --allow-empty
```

---
