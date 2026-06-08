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


@pytest.mark.asyncio
async def test_call_tool_raises_when_not_connected():
    """未连接时调用 raise。"""
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    with pytest.raises(McpConnectionError, match="not connected"):
        await conn.call_tool("search", {})


# ── McpConnection.health ─────────────────────

@pytest.mark.asyncio
async def test_health_true_when_connected():
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    with patch.object(conn, "_session", MagicMock()):
        assert await conn.health() is True


@pytest.mark.asyncio
async def test_health_false_when_not_connected():
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    assert await conn.health() is False


# ── McpConnection.disconnect ─────────────────

@pytest.mark.asyncio
async def test_disconnect_cleans_up_context_stack_and_stdio_cm():
    """disconnect 会正确关闭 session、stream 和 stdio context manager。"""
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    mock_read = AsyncMock()
    mock_write = AsyncMock()
    mock_session = AsyncMock()
    mock_stdio_cm = AsyncMock()

    conn._context_stack = (mock_read, mock_write, mock_session)
    conn._stdio_cm = mock_stdio_cm
    conn._session = mock_session
    conn._tools = [McpToolInfo(name="t1", description="d", input_schema={})]

    await conn.disconnect()

    mock_session.__aexit__.assert_awaited_once()
    mock_read.aclose.assert_awaited_once()
    mock_write.aclose.assert_awaited_once()
    mock_stdio_cm.__aexit__.assert_awaited_once()
    assert conn._session is None
    assert conn._stdio_cm is None
    assert conn._context_stack is None
    assert conn._tools == []


@pytest.mark.asyncio
async def test_disconnect_when_not_connected_is_noop():
    """从未连接时 disconnect 应该是安全的空操作。"""
    conn = McpConnection(
        McpServerConfig(name="tmdb", command="npx", args=[])
    )
    await conn.disconnect()  # Should not raise

    assert conn._session is None
    assert conn._stdio_cm is None
    assert conn._context_stack is None
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


# ── McpPool.call_tool_sync ───────────────────

def test_pool_call_tool_sync_no_loop_fallback():
    """call_tool_sync 在 _loop=None 时降级为 asyncio.run。"""
    conn = McpConnection(McpServerConfig(name="s1", command="echo", args=[]))
    pool = McpPool([])
    pool._connections = {"s1": conn}
    pool._loop = None  # 非 async 上下文（测试路径）

    mock_result = MagicMock()
    with patch.object(conn, "call_tool", AsyncMock(return_value=mock_result)):
        result = pool.call_tool_sync("s1", "search", {"q": "test"})
        assert result is mock_result


def test_pool_call_tool_sync_unknown_server():
    """call_tool_sync 对未知 server raise。"""
    pool = McpPool([])
    pool._loop = None
    with pytest.raises(McpConnectionError, match="not connected"):
        pool.call_tool_sync("unknown", "search", {})


def test_mcp_pool_captures_loop_in_async_context():
    """在 async 上下文中构造时 McpPool 捕获 running loop。"""
    import asyncio as _asyncio

    async def _create():
        pool = McpPool([])
        return pool._loop

    loop = _asyncio.new_event_loop()
    try:
        captured = loop.run_until_complete(_create())
        assert captured is loop
    finally:
        loop.close()


# ── McpPool.stop_all ─────────────────────────

@pytest.mark.asyncio
async def test_pool_stop_all_disconnects_all_servers():
    conn1 = McpConnection(McpServerConfig(name="a", command="echo", args=[]))
    conn2 = McpConnection(McpServerConfig(name="b", command="echo", args=[]))
    pool = McpPool([conn1, conn2])

    with patch.object(conn1, "disconnect", AsyncMock()) as d1:
        with patch.object(conn2, "disconnect", AsyncMock()) as d2:
            await pool.stop_all()
            d1.assert_awaited_once()
            d2.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_stop_all_one_failure_does_not_block_others():
    conn1 = McpConnection(McpServerConfig(name="a", command="echo", args=[]))
    conn2 = McpConnection(McpServerConfig(name="b", command="echo", args=[]))
    pool = McpPool([conn1, conn2])

    with patch.object(conn1, "disconnect", AsyncMock(side_effect=Exception("fail"))):
        with patch.object(conn2, "disconnect", AsyncMock()) as d2:
            await pool.stop_all()
            d2.assert_awaited_once()  # conn2 still gets disconnected
