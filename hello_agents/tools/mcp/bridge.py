"""MCP 工具 → HelloAgents Tool 桥接层。

把 MCP server 发现的每个工具包装为 HelloAgents Tool 实例，
通过 McpPool 统一调用。
"""

from __future__ import annotations

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
                description=prop.get("description", f"Parameter: {name}"),
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
        except Exception as e:
            logger.exception("Unexpected error calling MCP tool '%s/%s'", self._server, self._tool_info.name)
            return ToolResponse.error(
                code="MCP_TOOL_ERROR",
                message=f"MCP tool call failed: {e}",
            )
        return self._to_response(result)

    def run(self, parameters: dict) -> ToolResponse:
        """同步回退路径 — 通过 call_tool_sync 桥接到主 event loop。

        FastAPI 在线程池中运行同步路由，MCP transport streams 绑定在主 loop。
        call_tool_sync 使用 run_coroutine_threadsafe 跨越线程边界。
        """
        try:
            result = self._pool.call_tool_sync(
                self._server, self._tool_info.name, parameters
            )
        except McpConnectionError as e:
            return ToolResponse.error(
                code="MCP_CONNECTION_ERROR",
                message=f"MCP server '{self._server}' 不可用: {e}",
            )
        except Exception as e:
            logger.exception("Unexpected error calling MCP tool '%s/%s'", self._server, self._tool_info.name)
            return ToolResponse.error(
                code="MCP_TOOL_ERROR",
                message=f"MCP tool call failed: {e}",
            )
        return self._to_response(result)

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
        tool_gate: 每工具 Gate 覆盖，未传时默认 ALLOW（读写工具由上层 runner 决定）
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
        # Compose with existing predicate — preserve original allow list
        old_pred = tool_filter._predicate
        names_set = set(mcp_tool_names)
        tool_filter._predicate = lambda name, op=old_pred, ns=names_set: op(name) or name in ns

    logger.info("Registered %d MCP tools", count)
    return count
