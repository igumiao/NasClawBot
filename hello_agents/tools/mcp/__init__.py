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
