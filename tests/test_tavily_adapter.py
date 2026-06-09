"""Tests for Tavily adapter."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.adapters.tavily import TavilyAdapter, TavilyError


def _mock_httpx(json_data, *, status_code=200):
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.json.return_value = json_data
    mock_resp.status_code = status_code

    mock_cli = MagicMock()
    mock_cli.__enter__.return_value = mock_cli
    mock_cli.post.return_value = mock_resp

    return patch("httpx.Client", return_value=mock_cli), mock_cli


def _adapter(**kwargs):
    defaults = {"api_key": "tvly-test-key"}
    defaults.update(kwargs)
    return TavilyAdapter(**defaults)


def test_tavily_search_posts_expected_payload():
    patcher, mock_cli = _mock_httpx({"query": "Darth Maul animation", "results": []})

    with patcher:
        result = _adapter().search("Darth Maul animation", max_results=6, time_range="month")

    assert result["query"] == "Darth Maul animation"
    mock_cli.post.assert_called_once()
    args, kwargs = mock_cli.post.call_args
    assert args[0] == "https://api.tavily.com/search"
    payload = kwargs["json"]
    assert payload["api_key"] == "tvly-test-key"
    assert payload["query"] == "Darth Maul animation"
    assert payload["search_depth"] == "basic"
    assert payload["include_answer"] is False
    assert payload["include_images"] is False
    assert payload["include_raw_content"] is False
    assert payload["max_results"] == 6
    assert payload["time_range"] == "month"


def test_tavily_search_not_configured_returns_empty_response():
    result = _adapter(api_key="").search("Dune")

    assert result["query"] == "Dune"
    assert result["results"] == []
    assert result["usage"]["credits"] == 0


def test_tavily_search_http_error_raises_tavily_error():
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=mock_resp,
    )
    mock_cli = MagicMock()
    mock_cli.__enter__.return_value = mock_cli
    mock_cli.post.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_cli):
        with pytest.raises(TavilyError):
            _adapter().search("Dune")
