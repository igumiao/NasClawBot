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
        self._stdio_cm: object | None = None
        self._context_stack: tuple[object, object, ClientSession] | None = None
        self._tools: list[McpToolInfo] = []

    async def connect(self) -> None:
        """启动子进程，建立 STDIO 连接，初始化 session，发现工具。"""
        try:
            if self._session is None:
                server_params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env=self.config.env,
                )
                self._stdio_cm = stdio_client(server_params)
                read, write = await self._stdio_cm.__aenter__()
                session = ClientSession(read, write)
                await session.__aenter__()
                self._session = session
                self._context_stack = (read, write, session)

            await self._session.initialize()

            list_result = await self._session.list_tools()
            self._tools = [
                McpToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                )
                for tool in list_result.tools
            ]

            logger.info(
                "MCP server '%s' connected — %d tools discovered",
                self.config.name,
                len(self._tools),
            )
        except Exception as exc:
            await self.disconnect()
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
        """关闭 ClientSession 和底层 transport，回收子进程。"""
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
        if self._stdio_cm is not None:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._session = None
        self._stdio_cm = None
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
        """顺序连接所有 server，返回每 server 成功/失败状态。"""
        results: dict[str, bool] = {}
        for name, conn in self._connections.items():
            try:
                await conn.connect()
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
