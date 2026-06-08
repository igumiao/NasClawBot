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


from app.tools.tmdb_details import TMDBDetailsTool


class TestTMDBDetailsTool:
    def test_requires_tmdb_id_and_media_type(self):
        tool = TMDBDetailsTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["tmdb_id"].required is True
        assert params["media_type"].required is True
        assert set(params["media_type"].enum) == {"movie", "tv"}

    def test_run_movie_details(self):
        mock_adapter = MagicMock()
        mock_adapter.movie_details.return_value = {
            "id": 693134,
            "title": "沙丘2",
            "original_title": "Dune: Part Two",
            "overview": "保罗·厄崔迪的传奇故事继续上演。",
            "release_date": "2024-03-01",
            "runtime": 166,
            "genres": [
                {"id": 878, "name": "科幻"},
                {"id": 12, "name": "冒险"},
            ],
            "vote_average": 8.2,
            "vote_count": 3500,
            "external_ids": {"imdb_id": "tt15239678"},
        }
        tool = TMDBDetailsTool(mock_adapter)
        response = tool.run({"tmdb_id": 693134, "media_type": "movie"})

        mock_adapter.movie_details.assert_called_once_with(693134)
        assert response.status.value == "success"
        detail = response.data["detail"]
        assert detail["title"] == "沙丘2"
        assert detail["imdb_id"] == "tt15239678"
        assert detail["media_type"] == "movie"
        assert detail["runtime"] == 166
        assert len(detail["genres"]) == 2

    def test_run_tv_details(self):
        mock_adapter = MagicMock()
        mock_adapter.tv_details.return_value = {
            "id": 1399,
            "name": "权力的游戏",
            "original_name": "Game of Thrones",
            "overview": "维斯特洛大陆的权力斗争。",
            "first_air_date": "2011-04-17",
            "last_air_date": "2019-05-19",
            "in_production": False,
            "number_of_seasons": 8,
            "number_of_episodes": 73,
            "seasons": [
                {"season_number": 1, "name": "第 1 季", "episode_count": 10, "air_date": "2011-04-17"},
                {"season_number": 8, "name": "第 8 季", "episode_count": 6, "air_date": "2019-04-14"},
            ],
            "last_episode_to_air": {
                "season_number": 8, "episode_number": 6, "name": "铁王座",
                "air_date": "2019-05-19",
            },
            "next_episode_to_air": None,
            "genres": [
                {"id": 10765, "name": "Sci-Fi & Fantasy"},
                {"id": 18, "name": "剧情"},
            ],
            "vote_average": 8.5,
            "vote_count": 15000,
            "external_ids": {"imdb_id": "tt0944947"},
        }
        tool = TMDBDetailsTool(mock_adapter)
        response = tool.run({"tmdb_id": 1399, "media_type": "tv"})

        mock_adapter.tv_details.assert_called_once_with(1399)
        detail = response.data["detail"]
        assert detail["title"] == "权力的游戏"
        assert detail["imdb_id"] == "tt0944947"
        assert detail["media_type"] == "tv"
        assert detail["number_of_seasons"] == 8
        assert detail["number_of_episodes"] == 73
        assert detail["first_air_date"] == "2011-04-17"
        assert detail["last_air_date"] == "2019-05-19"
        assert detail["in_production"] is False
        assert len(detail["seasons"]) == 2
        assert detail["seasons"][0]["season_number"] == 1
        assert detail["seasons"][0]["air_date"] == "2011-04-17"
        assert detail["seasons"][1]["season_number"] == 8
        assert detail["last_episode_to_air"]["season_number"] == 8
        assert detail["last_episode_to_air"]["name"] == "铁王座"
        assert "next_episode_to_air" not in detail  # None → omitted

    def test_tv_details_includes_seasons_array_with_dates(self):
        """Per-season dates let the LLM identify which season is the latest."""
        mock_adapter = MagicMock()
        mock_adapter.tv_details.return_value = {
            "id": 117648,
            "name": "克拉克森的农场",
            "original_name": "Clarkson's Farm",
            "overview": "...",
            "first_air_date": "2021-06-11",
            "last_air_date": "2026-06-03",
            "in_production": True,
            "number_of_seasons": 5,
            "number_of_episodes": 40,
            "seasons": [
                {"season_number": 1, "name": "第 1 季", "episode_count": 8, "air_date": "2021-06-11"},
                {"season_number": 2, "name": "第 2 季", "episode_count": 8, "air_date": "2023-02-10"},
                {"season_number": 3, "name": "第 3 季", "episode_count": 8, "air_date": "2024-05-03"},
                {"season_number": 4, "name": "第 4 季", "episode_count": 8, "air_date": "2025-05-23"},
                {"season_number": 5, "name": "第 5 季", "episode_count": 8, "air_date": "2026-06-03"},
            ],
            "last_episode_to_air": {
                "season_number": 5, "episode_number": 4, "name": "更新",
                "air_date": "2026-06-03",
            },
            "next_episode_to_air": {
                "season_number": 5, "episode_number": 5, "name": "斩首",
                "air_date": "2026-06-10",
            },
            "genres": [],
            "vote_average": 8.6,
            "vote_count": 300,
            "external_ids": {"imdb_id": "tt10541088"},
        }
        tool = TMDBDetailsTool(mock_adapter)
        response = tool.run({"tmdb_id": 117648, "media_type": "tv"})

        detail = response.data["detail"]
        # Key fields for LLM to determine latest season
        assert detail["last_air_date"] == "2026-06-03"
        assert detail["in_production"] is True
        assert len(detail["seasons"]) == 5
        # Latest season
        latest = detail["seasons"][-1]
        assert latest["season_number"] == 5
        assert latest["air_date"] == "2026-06-03"
        # Latest episode
        assert detail["last_episode_to_air"]["season_number"] == 5
        # Next episode
        assert detail["next_episode_to_air"]["air_date"] == "2026-06-10"

    def test_tv_details_excludes_season_zero_specials(self):
        """Season 0 (specials) should be filtered out of the seasons array."""
        mock_adapter = MagicMock()
        mock_adapter.tv_details.return_value = {
            "id": 1399,
            "name": "权力的游戏",
            "overview": "...",
            "first_air_date": "2011-04-17",
            "last_air_date": "2019-05-19",
            "in_production": False,
            "number_of_seasons": 8,
            "number_of_episodes": 73,
            "seasons": [
                {"season_number": 0, "name": "特别篇", "episode_count": 10, "air_date": "2010-12-05"},
                {"season_number": 1, "name": "第 1 季", "episode_count": 10, "air_date": "2011-04-17"},
            ],
            "last_episode_to_air": None,
            "next_episode_to_air": None,
            "genres": [],
            "vote_average": 8.5,
            "vote_count": 15000,
            "external_ids": {},
        }
        tool = TMDBDetailsTool(mock_adapter)
        response = tool.run({"tmdb_id": 1399, "media_type": "tv"})

        seasons = response.data["detail"]["seasons"]
        assert len(seasons) == 1
        assert seasons[0]["season_number"] == 1

    def test_rejects_invalid_media_type(self):
        tool = TMDBDetailsTool(MagicMock())
        response = tool.run({"tmdb_id": 123, "media_type": "person"})
        assert response.status.value == "error"

    def test_rejects_invalid_tmdb_id(self):
        tool = TMDBDetailsTool(MagicMock())
        response = tool.run({"tmdb_id": 0, "media_type": "movie"})
        assert response.status.value == "error"

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.movie_details.side_effect = Exception("Boom")
        tool = TMDBDetailsTool(mock_adapter)
        response = tool.run({"tmdb_id": 999, "media_type": "movie"})
        assert response.status.value == "error"


from app.tools.tmdb_discover import TMDBDiscoverTool


class TestTMDBDiscoverTool:
    def test_requires_media_type(self):
        tool = TMDBDiscoverTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["media_type"].required is True
        assert set(params["media_type"].enum) == {"movie", "tv"}

    def test_optional_filters_have_defaults(self):
        tool = TMDBDiscoverTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        for name in ("sort_by", "with_genres", "year", "vote_average_gte", "vote_count_gte"):
            assert params[name].required is False, f"{name} should be optional"

    def test_run_discover_movie_uses_correct_adapter_method(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.return_value = {
            "page": 1,
            "results": [
                {"id": 693134, "title": "沙丘2", "overview": "...",
                 "release_date": "2024-03-01", "vote_average": 8.2, "vote_count": 3500},
            ],
            "total_results": 1,
        }
        tool = TMDBDiscoverTool(mock_adapter)
        response = tool.run({
            "media_type": "movie",
            "sort_by": "vote_average.desc",
            "with_genres": "878",
            "year": 2024,
            "vote_count_gte": 200,
        })
        mock_adapter.discover_movie.assert_called_once()
        call_kwargs = mock_adapter.discover_movie.call_args[1]
        assert call_kwargs["sort_by"] == "vote_average.desc"
        assert call_kwargs["with_genres"] == "878"
        assert call_kwargs["primary_release_year"] == 2024
        assert call_kwargs["vote_count.gte"] == 200
        assert response.status.value == "success"

    def test_run_discover_tv_uses_correct_adapter_method(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_tv.return_value = {
            "page": 1,
            "results": [
                {"id": 1399, "name": "权力的游戏", "overview": "...",
                 "first_air_date": "2011-04-17", "vote_average": 8.5, "vote_count": 15000},
            ],
            "total_results": 1,
        }
        tool = TMDBDiscoverTool(mock_adapter)
        response = tool.run({
            "media_type": "tv",
            "sort_by": "popularity.desc",
            "year": 2011,
        })
        mock_adapter.discover_tv.assert_called_once()
        call_kwargs = mock_adapter.discover_tv.call_args[1]
        assert call_kwargs["first_air_date_year"] == 2011
        assert response.status.value == "success"

    def test_limits_results_to_5(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.return_value = {
            "page": 1,
            "results": [{"id": i, "title": f"Movie {i}"} for i in range(10)],
            "total_results": 10,
        }
        tool = TMDBDiscoverTool(mock_adapter)
        response = tool.run({"media_type": "movie"})
        assert len(response.data["candidates"]) == 5

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.discover_movie.side_effect = Exception("Fail")
        tool = TMDBDiscoverTool(mock_adapter)
        response = tool.run({"media_type": "movie"})
        assert response.status.value == "error"


from app.tools.tmdb_trending import TMDBTrendingTool


class TestTMDBTrendingTool:
    def test_optional_parameters(self):
        tool = TMDBTrendingTool(MagicMock())
        params = {p.name: p for p in tool.get_parameters()}
        assert params["media_type"].required is False
        assert params["time_window"].required is False
        assert set(params["media_type"].enum) == {"all", "movie", "tv", "person"}
        assert set(params["time_window"].enum) == {"day", "week"}

    def test_run_with_defaults(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [
                {"id": 693134, "title": "沙丘2", "media_type": "movie",
                 "overview": "...", "popularity": 100.5, "vote_average": 8.2},
            ],
            "total_results": 20,
        }
        tool = TMDBTrendingTool(mock_adapter)
        response = tool.run({})
        mock_adapter.trending_all.assert_called_once_with("day")
        assert response.status.value == "success"
        candidates = response.data["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["tmdb_id"] == 693134

    def test_filters_by_media_type(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [
                {"id": 1, "title": "Movie", "media_type": "movie"},
                {"id": 2, "name": "TV Show", "media_type": "tv"},
                {"id": 3, "title": "Another Movie", "media_type": "movie"},
            ],
            "total_results": 3,
        }
        tool = TMDBTrendingTool(mock_adapter)
        response = tool.run({"media_type": "tv"})
        candidates = response.data["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["media_type"] == "tv"

    def test_limits_results_to_5(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.return_value = {
            "page": 1,
            "results": [{"id": i, "media_type": "movie"} for i in range(10)],
            "total_results": 10,
        }
        tool = TMDBTrendingTool(mock_adapter)
        response = tool.run({})
        assert len(response.data["candidates"]) == 5

    def test_rejects_invalid_time_window(self):
        tool = TMDBTrendingTool(MagicMock())
        response = tool.run({"time_window": "month"})
        assert response.status.value == "error"

    def test_handles_adapter_error(self):
        mock_adapter = MagicMock()
        mock_adapter.trending_all.side_effect = Exception("Boom")
        tool = TMDBTrendingTool(mock_adapter)
        response = tool.run({})
        assert response.status.value == "error"
