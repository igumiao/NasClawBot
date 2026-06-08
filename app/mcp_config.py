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
