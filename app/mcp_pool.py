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
