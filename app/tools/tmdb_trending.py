"""TMDBTrendingTool — view TMDB current trending content."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBTrendingTool(Tool):
    """View TMDB current trending movies, TV shows and people."""

    _MEDIA_TYPES = ("all", "movie", "tv", "person")
    _TIME_WINDOWS = ("day", "week")
    _RESULT_LIMIT = 5

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_trending",
            description=(
                "查看 TMDB 日/周趋势热度榜。"
                "适合用户问最近热门、本周热门或 TMDB 热门趋势。"
                "热度榜不代表最新发布，也不适合查某个系列的最新作品。"
                "可选 media_type 筛选电影/电视剧/人物。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="media_type",
                type="string",
                description="筛选媒体类型：all（全部）、movie（电影）、tv（电视剧）、person（人物）",
                required=False,
                enum=list(self._MEDIA_TYPES),
                default="all",
            ),
            ToolParameter(
                name="time_window",
                type="string",
                description="时间窗口：day（今日趋势）、week（本周趋势）",
                required=False,
                enum=list(self._TIME_WINDOWS),
                default="day",
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            media_type, time_window = self._validate_params(parameters)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        try:
            raw = self._adapter.trending_all(time_window)
        except TMDBError as exc:
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 趋势获取失败: {exc}",
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"获取趋势时发生内部错误: {exc}",
            )

        results = raw.get("results", [])
        if media_type != "all":
            results = [r for r in results if r.get("media_type") == media_type]

        candidates = []
        for item in results[: self._RESULT_LIMIT]:
            candidates.append(self._normalize_item(item))

        return ToolResponse.success(
            text=f"找到 {len(candidates)} 个热门内容。",
            data={
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )

    def _validate_params(self, parameters: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(parameters, dict):
            raise ValueError("参数必须是一个对象。")

        unknown = sorted(set(parameters) - {"media_type", "time_window"})
        if unknown:
            raise ValueError(f"不支持的参数: {', '.join(unknown)}")

        media_type = parameters.get("media_type", "all")
        if media_type not in self._MEDIA_TYPES:
            raise ValueError(
                f"media_type 必须是以下之一: {', '.join(self._MEDIA_TYPES)}。"
            )

        time_window = parameters.get("time_window", "day")
        if time_window not in self._TIME_WINDOWS:
            raise ValueError(
                f"time_window 必须是以下之一: {', '.join(self._TIME_WINDOWS)}。"
            )

        return media_type, time_window

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "tmdb_id": item.get("id"),
            "title": item.get("title") or item.get("name") or "未知标题",
            "media_type": item.get("media_type"),
            "overview": item.get("overview") or "",
            "popularity": item.get("popularity"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
        }
