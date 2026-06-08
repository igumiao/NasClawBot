"""Tests for app.mcp_config."""

from unittest.mock import MagicMock, patch

import pytest


def _try_import():
    """Helper: import from app.mcp_config, skip if Task 3 dependency not ready."""
    try:
        from app.mcp_config import TMDB_TOOLS_ALLOW, load_mcp_servers
        return TMDB_TOOLS_ALLOW, load_mcp_servers
    except ImportError as e:
        if "hello_agents.tools.mcp" in str(e):
            pytest.skip("Waiting for Task 3 — hello_agents.tools.mcp.client not yet created")
        raise


def test_tmdb_tools_allow_has_correct_structure():
    """Verify TMDB_TOOLS_ALLOW is a curated list of 6 core tools."""
    TMDB_TOOLS_ALLOW, _ = _try_import()

    assert len(TMDB_TOOLS_ALLOW) == 6
    assert "search_movies" in TMDB_TOOLS_ALLOW
    assert "get_movie_details" in TMDB_TOOLS_ALLOW
    assert "search_tv_shows" in TMDB_TOOLS_ALLOW
    assert "search_person" in TMDB_TOOLS_ALLOW
    assert "get_recommendations" in TMDB_TOOLS_ALLOW
    assert "get_trending" in TMDB_TOOLS_ALLOW


def test_load_mcp_servers_empty_when_no_api_key():
    """无 TMDB_API_KEY 时返回空列表。"""
    _, load_mcp_servers = _try_import()

    with patch("app.mcp_config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(tmdb_api_key="  ")
        result = load_mcp_servers()
        assert result == []


def test_load_mcp_servers_returns_tmdb_config():
    """有 API key 时返回单个 TMDB 配置。"""
    _, load_mcp_servers = _try_import()

    with patch("app.mcp_config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(tmdb_api_key="test-key-123")
        result = load_mcp_servers()
        assert len(result) == 1
        config = result[0]
        assert config.name == "tmdb"
        assert config.command == "npx"
        assert config.args == ["-y", "mcp-server-tmdb"]
        assert config.env == {"TMDB_API_KEY": "test-key-123"}
