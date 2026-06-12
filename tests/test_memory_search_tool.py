"""Tests for MemorySearchTool."""

from pathlib import Path

import pytest

from app.services.markdown_memory_store import MarkdownMemoryStore
from app.tools.memory_search import MemorySearchTool


def test_memory_search_schema_exposes_readonly_search_surface():
    schema = MemorySearchTool().to_openai_schema()["function"]["parameters"]

    assert schema["required"] == ["query"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"query", "kind", "limit"}
    assert schema["properties"]["kind"]["enum"] == [
        "index",
        "user_profile",
        "knowledge",
    ]


def test_memory_search_returns_tool_response_hits(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "# Playback\nPrefer remux for Dune.\n",
        encoding="utf-8",
    )
    tool = MemorySearchTool(MarkdownMemoryStore(tmp_path))

    response = tool.run({"query": "DUNE", "kind": "knowledge", "limit": 3})

    assert response.status.value == "success"
    assert response.data["returned_count"] == 1
    assert response.data["hits"] == [
        {
            "kind": "knowledge",
            "line_number": 2,
            "section": "Playback",
            "text": "Prefer remux for Dune.",
            "score": 1.0,
            "match_type": "body",
            "context": [
                {
                    "line_number": 1,
                    "text": "# Playback",
                },
                {
                    "line_number": 2,
                    "text": "Prefer remux for Dune.",
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"query": ""},
        {"query": "Dune", "kind": "unknown"},
        {"query": "Dune", "limit": 0},
        {"query": "Dune", "extra": True},
        None,
    ],
)
def test_memory_search_rejects_invalid_parameters(parameters):
    response = MemorySearchTool().run(parameters)

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_memory_search_caps_limit_at_twenty(tmp_path: Path):
    (tmp_path / "knowledge.md").write_text(
        "\n".join(f"alpha {index}" for index in range(25)),
        encoding="utf-8",
    )
    tool = MemorySearchTool(MarkdownMemoryStore(tmp_path))

    response = tool.run({"query": "alpha", "limit": 99})

    assert response.status.value == "success"
    assert response.data["limit"] == 20
    assert response.data["returned_count"] == 20
