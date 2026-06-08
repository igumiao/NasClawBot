"""Tests for hello_agents.tools.mcp.bridge."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hello_agents.tools.base import ToolParameter, ToolResponse
from hello_agents.tools.filter import Filter
from hello_agents.tools.gate import Gate
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.mcp.bridge import McpBridgeTool, register_mcp_tools
from hello_agents.tools.response import ToolStatus
from hello_agents.tools.mcp.client import McpConnectionError, McpPool, McpToolInfo


# ── Helper ────────────────────────────────────

def _make_pool_with_tool(**overrides):
    """Create a McpPool mock pre-configured to return one tool."""
    args = {
        "name": "search_movies",
        "description": "搜索电影",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }
    args.update(overrides)
    tool_info = McpToolInfo(**args)
    pool = MagicMock(spec=McpPool)
    pool.get_tools.return_value = [("tmdb", tool_info)]
    return pool, tool_info


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
    required_names = {p.name for p in params if p.required}
    optional_names = {p.name for p in params if not p.required}
    assert required_names == {"query"}
    assert optional_names == {"year"}


def test_bridge_tool_naming_convention():
    """命名格式: mcp_{server}_{tool_name}"""
    tool_info = McpToolInfo(name="search_movies", description="d", input_schema={})
    pool = MagicMock(spec=McpPool)
    tool = McpBridgeTool(pool, "tmdb", tool_info)
    assert tool.name == "mcp_tmdb_search_movies"
    assert tool.description == "d"


# ── McpBridgeTool.run (sync bridge) ───────────

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

    assert response.status == ToolStatus.ERROR
    assert response.error_info is not None
    assert "MCP_CONNECTION_ERROR" in response.error_info["code"]


def test_bridge_tool_run_structured_content_fallback():
    """When result has no text content, fall back to structuredContent JSON."""
    pool = MagicMock(spec=McpPool)
    mock_result = MagicMock()
    mock_result.content = []  # no text content
    mock_result.structuredContent = {"results": [1, 2, 3]}

    async def async_call_tool(*args, **kwargs):
        return mock_result
    pool.call_tool = async_call_tool

    tool_info = McpToolInfo(name="search", description="d", input_schema={
        "type": "object", "properties": {}, "required": [],
    })
    tool = McpBridgeTool(pool, "tmdb", tool_info)
    response = tool.run({})

    assert response.status.value == "success"
    assert "results" in response.text


# ── register_mcp_tools ────────────────────────

def test_register_mcp_tools_registers_all():
    pool = MagicMock(spec=McpPool)
    tool_info = McpToolInfo(name="search", description="d", input_schema={
        "type": "object", "properties": {}, "required": [],
    })
    pool.get_tools.return_value = [("tmdb", tool_info)]

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry)

    assert count == 1
    assert "mcp_tmdb_search" in getattr(registry, "_tools", {})


def test_register_mcp_tools_with_allow_filter():
    pool = MagicMock(spec=McpPool)
    pool.get_tools.return_value = [
        ("tmdb", McpToolInfo(name="search_movies", description="d", input_schema={
            "type": "object", "properties": {}, "required": [],
        })),
        ("tmdb", McpToolInfo(name="get_trending", description="d", input_schema={
            "type": "object", "properties": {}, "required": [],
        })),
    ]

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry, allow=["search_movies"])

    assert count == 1
    assert "mcp_tmdb_search_movies" in getattr(registry, "_tools", {})
    assert "mcp_tmdb_get_trending" not in getattr(registry, "_tools", {})


def test_register_mcp_tools_empty_pool():
    pool = MagicMock(spec=McpPool)
    pool.get_tools.return_value = []

    registry = ToolRegistry()
    count = register_mcp_tools(pool, registry)

    assert count == 0


def test_register_mcp_tools_with_tool_filter():
    """传入 tool_filter 时，MCP 工具名自动加入白名单。"""
    pool = MagicMock(spec=McpPool)
    tool_info = McpToolInfo(name="search", description="d", input_schema={
        "type": "object", "properties": {}, "required": [],
    })
    pool.get_tools.return_value = [("tmdb", tool_info)]

    registry = ToolRegistry()
    tool_filter = Filter(allow=["mteam_search"])

    count = register_mcp_tools(pool, registry, tool_filter=tool_filter)

    assert count == 1
    assert tool_filter.apply(["mcp_tmdb_search"]) == ["mcp_tmdb_search"]
