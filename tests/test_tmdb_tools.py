"""Tests for TMDB tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.tools.tmdb_search import TMDBSearchTool
from hello_agents.tools.response import ToolResponse


class TestTMDBSearchTool:
    def test_requires_query_parameter(self):
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        query_param = next(p for p in params if p.name == "query")
        assert query_param.required is True

    def test_media_type_optional(self):
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        media_param = next(p for p in params if p.name == "media_type")
        assert media_param.required is False

    def test_media_type_has_enum(self):
        tool = TMDBSearchTool(MagicMock())
        params = tool.get_parameters()
        media_param = next(p for p in params if p.name == "media_type")
        assert set(media_param.enum) == {"movie", "tv", "person"}

    def test_run_calls_adapter_and_returns_results(self):
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {
                    "id": 693134,
                    "title": "沙丘2",
                    "media_type": "movie",
                    "overview": "保罗·厄崔迪的传奇故事继续上演。",
                    "release_date": "2024-03-01",
                    "popularity": 100.5,
                    "vote_average": 8.2,
                    "vote_count": 3000,
                },
                {
                    "id": 1399,
                    "name": "权力的游戏",
                    "media_type": "tv",
                    "overview": "维斯特洛大陆的权力斗争。",
                    "first_air_date": "2011-04-17",
                    "popularity": 200.3,
                    "vote_average": 8.5,
                    "vote_count": 15000,
                },
            ],
            "total_results": 2,
        }
        tool = TMDBSearchTool(mock_adapter)
        response = tool.run({"query": "沙丘"})

        mock_adapter.search_multi.assert_called_once_with("沙丘")
        assert response.status.value == "success"
        candidates = response.data["candidates"]
        assert len(candidates) == 2
        assert candidates[0]["tmdb_id"] == 693134
        assert candidates[0]["title"] == "沙丘2"
        assert candidates[0]["media_type"] == "movie"

    def test_filters_by_media_type(self):
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {"id": 1, "title": "Movie A", "media_type": "movie"},
                {"id": 2, "name": "TV Show A", "media_type": "tv"},
                {"id": 3, "title": "Movie B", "media_type": "movie"},
            ],
            "total_results": 3,
        }
        tool = TMDBSearchTool(mock_adapter)
        response = tool.run({"query": "test", "media_type": "movie"})
        candidates = response.data["candidates"]
        assert len(candidates) == 2
        assert all(c["media_type"] == "movie" for c in candidates)

    def test_limits_results_to_5(self):
        mock_adapter = MagicMock()
        mock_adapter.search_multi.return_value = {
            "page": 1,
            "results": [
                {"id": i, "title": f"Movie {i}", "media_type": "movie"}
                for i in range(10)
            ],
            "total_results": 10,
        }
        tool = TMDBSearchTool(mock_adapter)
        response = tool.run({"query": "test"})
        assert len(response.data["candidates"]) == 5

    def test_handles_empty_query(self):
        mock_adapter = MagicMock()
        tool = TMDBSearchTool(mock_adapter)
        response = tool.run({"query": ""})
        assert response.status.value == "error"

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.search_multi.side_effect = Exception("Network error")
        tool = TMDBSearchTool(mock_adapter)
        response = tool.run({"query": "test"})
        assert response.status.value == "error"
