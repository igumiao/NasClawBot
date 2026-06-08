"""TMDBDiscoverTool — discover TMDB movies and TV shows by filters."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


_VALID_MEDIA_TYPES = frozenset({"movie", "tv"})
_RESULT_LIMIT = 5


class TMDBDiscoverTool(Tool):
    """Discover TMDB movies or TV shows by genre, rating, year, etc."""

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_discover",
            description=(
                "按条件发现 TMDB 影视作品。"
                "可按类型（电影/电视剧）、评分、年份、流派等筛选，"
                "按人气、评分或日期排序。"
                "适合用户要求推荐或浏览某一类别影视时使用。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="media_type",
                type="string",
                description="媒体类型",
                required=True,
                enum=sorted(_VALID_MEDIA_TYPES),
            ),
            ToolParameter(
                name="sort_by",
                type="string",
                description="排序方式，默认 popularity.desc",
                required=False,
            ),
            ToolParameter(
                name="with_genres",
                type="string",
                description="TMDB 类型 ID，逗号分隔",
                required=False,
            ),
            ToolParameter(
                name="year",
                type="integer",
                description="年份过滤",
                required=False,
            ),
            ToolParameter(
                name="vote_average_gte",
                type="number",
                description="最低评分",
                required=False,
            ),
            ToolParameter(
                name="vote_count_gte",
                type="integer",
                description="最低评分人数",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            media_type = self._validate_media_type(parameters.get("media_type"))
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        try:
            filters = self._build_filters(parameters, media_type)
            if media_type == "movie":
                raw = self._adapter.discover_movie(**filters)
            else:
                raw = self._adapter.discover_tv(**filters)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 发现失败: {exc}",
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"发现时发生内部错误: {exc}",
            )

        results = raw.get("results", [])
        candidates = [self._normalize_item(item, media_type) for item in results[:_RESULT_LIMIT]]

        return ToolResponse.success(
            text=f"找到 {len(candidates)} 个结果。",
            data={
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_media_type(raw: Any) -> str:
        if not isinstance(raw, str) or raw not in _VALID_MEDIA_TYPES:
            raise ValueError("media_type 必须是 movie 或 tv。")
        return raw

    @staticmethod
    def _build_filters(parameters: dict[str, Any], media_type: str) -> dict[str, Any]:
        filters: dict[str, Any] = {}

        sort_by = parameters.get("sort_by")
        if sort_by is not None:
            filters["sort_by"] = sort_by

        with_genres = parameters.get("with_genres")
        if with_genres is not None:
            filters["with_genres"] = with_genres

        year = parameters.get("year")
        if year is not None:
            if media_type == "movie":
                filters["primary_release_year"] = year
            else:
                filters["first_air_date_year"] = year

        vote_average_gte = parameters.get("vote_average_gte")
        if vote_average_gte is not None:
            filters["vote_average.gte"] = vote_average_gte

        vote_count_gte = parameters.get("vote_count_gte")
        if vote_count_gte is not None:
            filters["vote_count.gte"] = vote_count_gte

        return filters

    @staticmethod
    def _normalize_item(item: dict[str, Any], media_type: str) -> dict[str, Any]:
        return {
            "tmdb_id": item.get("id"),
            "title": item.get("title") or item.get("name") or "未知标题",
            "media_type": media_type,
            "overview": item.get("overview") or "",
            "release_date": item.get("release_date")
            or item.get("first_air_date")
            or None,
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
            "popularity": item.get("popularity"),
        }
