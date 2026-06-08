"""MCP 连接池单例 — 进程级生命周期管理。

当前无活跃 MCP server。保留框架以备后续接入。
"""

from __future__ import annotations

from hello_agents.tools.mcp.client import McpPool

_mcp_pool: McpPool | None = None


def get_mcp_pool() -> McpPool | None:
    """返回已初始化的 McpPool，未配置时返回 None。"""
    return _mcp_pool


async def init_mcp_pool() -> McpPool | None:
    """启动 MCP server 连接（当前无配置，直接返回 None）。"""
    return None


async def shutdown_mcp_pool() -> None:
    """关闭所有 MCP server 连接。"""
    global _mcp_pool
    if _mcp_pool is not None:
        await _mcp_pool.stop_all()
        _mcp_pool = None
