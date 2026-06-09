"""Tests for TavilySearchTool."""

from unittest.mock import MagicMock

import pytest

from app.adapters.tavily import TavilyError
from app.tools.tavily_search import TavilySearchTool


def test_tavily_search_schema_exposes_small_parameter_surface():
    schema = TavilySearchTool(MagicMock()).to_openai_schema()["function"]["parameters"]

    assert schema["required"] == ["query"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"query", "max_results", "time_range"}
    assert schema["properties"]["time_range"]["enum"] == ["day", "week", "month", "year"]


def test_tavily_search_calls_adapter_and_returns_compact_results():
    adapter = MagicMock()
    adapter.search.return_value = {
        "query": "Darth Maul animation",
        "results": [
            {
                "title": "Star Wars animation news",
                "url": "https://example.test/star-wars",
                "content": "A new Darth Maul animated series is discussed.",
                "score": 0.92,
            }
        ],
        "usage": {"credits": 1},
    }
    tool = TavilySearchTool(adapter)

    response = tool.run({
        "query": "Darth Maul animation",
        "max_results": 5,
        "time_range": "month",
    })

    adapter.search.assert_called_once_with(
        "Darth Maul animation",
        max_results=5,
        time_range="month",
    )
    assert response.status.value == "success"
    assert response.data["returned_count"] == 1
    assert response.data["usage_credits"] == 1
    assert response.data["results"][0]["title"] == "Star Wars animation news"


def test_tavily_search_caps_max_results_at_ten():
    adapter = MagicMock()
    adapter.search.return_value = {
        "query": "Dune",
        "results": [{"title": f"Result {index}"} for index in range(12)],
    }
    tool = TavilySearchTool(adapter)

    response = tool.run({"query": "Dune", "max_results": 50})

    adapter.search.assert_called_once_with("Dune", max_results=10, time_range=None)
    assert response.data["returned_count"] == 10


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"query": ""},
        {"query": "Dune", "max_results": 0},
        {"query": "Dune", "time_range": "recent"},
        {"query": "Dune", "include_answer": True},
        None,
    ],
)
def test_tavily_search_rejects_invalid_parameters(parameters):
    response = TavilySearchTool(MagicMock()).run(parameters)

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_tavily_search_adapter_error_returns_tool_error():
    adapter = MagicMock()
    adapter.search.side_effect = TavilyError("network failed")

    response = TavilySearchTool(adapter).run({"query": "Dune"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "TAVILY_ERROR"
