"""Tests for app.mcp_config."""

from unittest.mock import MagicMock, patch

import pytest


def test_tmdb_tools_allow_has_correct_structure():
    """Verify TMDB_TOOLS_ALLOW is a curated list of 6 core tools."""
    # Import may fail until hello_agents.tools.mcp.client exists (Task 3).
    # We verify the file is syntactically valid and the list is correct.
    try:
        from app.mcp_config import TMDB_TOOLS_ALLOW
    except ImportError as e:
        if "hello_agents.tools.mcp" in str(e):
            pytest.skip("Waiting for Task 3 — hello_agents.tools.mcp.client not yet created")
        raise

    assert len(TMDB_TOOLS_ALLOW) == 6
    assert "search_movies" in TMDB_TOOLS_ALLOW
    assert "get_movie_details" in TMDB_TOOLS_ALLOW
    assert "search_tv_shows" in TMDB_TOOLS_ALLOW
    assert "search_person" in TMDB_TOOLS_ALLOW
    assert "get_recommendations" in TMDB_TOOLS_ALLOW
    assert "get_trending" in TMDB_TOOLS_ALLOW


def test_config_file_is_syntactically_valid():
    """Verify app/mcp_config.py has valid Python syntax."""
    import ast
    from pathlib import Path

    config_path = Path(__file__).resolve().parents[2] / "app" / "mcp_config.py"
    source = config_path.read_text()
    try:
        ast.parse(source)
    except SyntaxError as e:
        pytest.fail(f"app/mcp_config.py has syntax error: {e}")
