"""MCP 连接池单例 — 进程级生命周期管理。

管理 filesystem MCP server 的启动与关闭，允许 Agent 在指定目录内
进行文件操作（读、写、创建目录、移动/重命名等）。

配置方式（按优先级）:
1. .env 中设置 MCP_FS_ALLOWED_DIRS（逗号分隔多个目录）
2. 未设置时默认使用项目内的 test-media/ 测试目录
3. 设置 MCP_FS_ENABLED=false 完全禁用 MCP

Docker 部署示例:
    容器内路径统一为 /影视，通过 volume 映射到 NAS:
      docker run -v /vol1/1000/影视:/影视 ...
    .env 配置:
      MCP_FS_ALLOWED_DIRS=/影视
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from hello_agents.tools.mcp.client import McpConnection, McpPool, McpServerConfig

logger = logging.getLogger(__name__)

_mcp_pool: McpPool | None = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_allowed_dirs() -> list[str]:
    """解析允许访问的目录列表。"""
    env_value = os.getenv("MCP_FS_ALLOWED_DIRS", "")
    if env_value.strip():
        return [d.strip() for d in env_value.split(",") if d.strip()]
    # 开发环境默认值
    return [str(PROJECT_ROOT / "test-media")]


def get_mcp_pool() -> McpPool | None:
    """返回已初始化的 McpPool，未初始化时返回 None。"""
    return _mcp_pool


async def init_mcp_pool() -> McpPool | None:
    """启动 MCP server 连接。

    当前接入 filesystem MCP server，允许 Agent 在指定目录内
    执行文件操作（read_file、write_file、edit_file、create_directory、
    list_directory、move_file、search_files、get_file_info 等）。

    通过 MCP_FS_ENABLED 环境变量控制开关，默认启用。
    """
    global _mcp_pool

    if os.getenv("MCP_FS_ENABLED", "true").strip().lower() in ("false", "0", "no", "off"):
        logger.info("MCP filesystem disabled via MCP_FS_ENABLED")
        return None

    allowed_dirs = _parse_allowed_dirs()
    logger.info("MCP filesystem allowed dirs: %s", allowed_dirs)

    config = McpServerConfig(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"] + allowed_dirs,
    )

    _mcp_pool = McpPool([McpConnection(config)])
    results = await _mcp_pool.start_all()

    if results.get("filesystem"):
        tools = _mcp_pool.get_tools("filesystem")
        logger.info(
            "MCP filesystem connected — %d tools: %s",
            len(tools),
            [t.name for _, t in tools],
        )
    else:
        logger.warning("MCP filesystem connection failed, Agent 将无法使用文件操作工具")

    return _mcp_pool


async def shutdown_mcp_pool() -> None:
    """关闭所有 MCP server 连接。"""
    global _mcp_pool
    if _mcp_pool is not None:
        await _mcp_pool.stop_all()
        _mcp_pool = None
        logger.info("MCP pool shut down")
