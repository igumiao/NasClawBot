"""Unified Agent dependency seam for production and evaluation.

This module defines the single interface through which external services
reach the Agent tool set.  The production factory builds real adapters;
evaluation factories return Recording/Fake implementations so behavioral
trials produce zero real-world side effects.

Tool classes, descriptions, schemas, Filter, Gate, and the system prompt
remain owned by the production runner — only the external environment is
swapped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings


_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"


@dataclass
class AgentToolDependencies:
    """External services consumed by the Agent tool set.

    Every field can be replaced with a Recording/Fake counterpart during
    evaluation runs.  Fields that are ``None`` cause the corresponding
    optional tools (download, task management, MCP) to be skipped.
    """

    mteam: Any
    """M-Team adapter (search, profile, token generation)."""

    qb: Any
    """qBittorrent adapter (list, control, speed)."""

    tmdb: Any
    """TMDB adapter (search, details, discover, trending)."""

    tavily: Any
    """Tavily web-search adapter."""

    memory_store: Any
    """Agent memory store (``MarkdownMemoryStore`` or Fake)."""

    download_automation: Any | None = None
    """``DownloadAutomation`` — when ``None``, download/monitor tools are
    not registered."""

    task_management: Any | None = None
    """Task management service — when ``None``, task list/cancel tools
    are not registered."""

    runtime_task_store: Any | None = None
    """Runtime task store — when ``None``, task event tools are not
    registered and background events are not injected."""

    mcp_pool: Any | None = None
    """MCP tool pool — when ``None``, filesystem MCP tools are not
    registered."""


def create_production_dependencies(settings: Settings) -> AgentToolDependencies:
    """Build the production dependency set from typed *settings*.

    This is the default factory used by ``NasClawAgentRunner`` when no
    explicit ``dependencies`` argument is provided.  It constructs every
    adapter and store with real credentials and network access.
    """
    from app.adapters.mteam import MTeamAdapter
    from app.adapters.qbittorrent import QBittorrentAdapter
    from app.adapters.tavily import TavilyAdapter
    from app.adapters.tmdb import TMDBAdapter
    from app.mcp_pool import get_mcp_pool
    from app.services.download_automation import DownloadAutomation
    from app.services.markdown_memory_store import MarkdownMemoryStore
    from app.services.tmdb_network_store import TMDBNetworkSettingsStore

    mteam = MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )
    qb = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )

    # TMDB with optional proxy override.
    tmdb_network = TMDBNetworkSettingsStore(_SETTINGS_DIR).load()
    tmdb = TMDBAdapter(
        api_key=settings.tmdb_api_key,
        proxy_url=tmdb_network.active_proxy_url,
    )

    tavily = TavilyAdapter(api_key=settings.tavily_api_key)

    # Memory store rooted at the production directory.
    memory_store = MarkdownMemoryStore(
        Path(__file__).resolve().parents[2] / "memory" / "agent-memory",
    )
    memory_store.ensure_template_files()

    # Download automation — requires a runtime task store and scheduler.
    # Created lazily by the runner's existing factory; here we return
    # None to signal that the runner should use its own factories.
    download_automation = None  # runner wires this via its own factory

    task_management = None  # runner wires this via its own factory
    runtime_task_store = None  # runner wires this via its own factory

    mcp_pool = get_mcp_pool()

    return AgentToolDependencies(
        mteam=mteam,
        qb=qb,
        tmdb=tmdb,
        tavily=tavily,
        memory_store=memory_store,
        download_automation=download_automation,
        task_management=task_management,
        runtime_task_store=runtime_task_store,
        mcp_pool=mcp_pool,
    )
