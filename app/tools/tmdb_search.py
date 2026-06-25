"""TMDBSearchTool — search TMDB movies, TV shows and people."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tmdb import TMDBAdapter, TMDBError


class TMDBSearchTool(Tool):
    """Search TMDB and return a compact list of structured candidates."""

    _MEDIA_TYPES = ("movie", "tv", "person")
    _RESULT_LIMIT = 5
    _MAX_QUERY_LENGTH = 200

    def __init__(self, adapter: TMDBAdapter) -> None:
        super().__init__(
            name="tmdb_search",
            description=(
                "按明确或候选标题搜索 TMDB 的电影、电视剧和人物。"
                "适合验证已知片名、剧名、人物名、中文名、英文名，"
                "或查询明确系列/片名族下的候选条目。"
                "返回标题、媒体类型、TMDB ID、日期和概述。"
                "跨度很大的宇宙/IP、角色相关新作、最新新闻或未明确媒体类型的'系列最新'，"
                "应先用 tavily_search 澄清具体作品范围。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="明确标题、候选官方标题、中文名、英文名、人物名或明确系列名；不要传'最新有什么'、'角色相关新作'这类开放任务。",
                required=True,
            ),
            ToolParameter(
                name="media_type",
                type="string",
                description="筛选媒体类型：movie（电影）、tv（电视剧）、person（人物）",
                required=False,
                enum=list(self._MEDIA_TYPES),
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            query = self._normalize_query(parameters)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        try:
            raw = self._adapter.search_multi(query)
        except TMDBError as exc:
            detail = f": {exc}" if str(exc) else ""
            return ToolResponse.error(
                code="TMDB_ERROR",
                message=f"TMDB 搜索失败{detail}",
            )
        except Exception as exc:
            detail = f": {exc}" if str(exc) else ""
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"搜索时发生内部错误{detail}",
            )

        media_type_filter = parameters.get("media_type")
        results = raw.get("results", [])
        if media_type_filter:
            results = [r for r in results if r.get("media_type") == media_type_filter]

        candidates = []
        for item in results[: self._RESULT_LIMIT]:
            candidates.append(self._normalize_item(item))

        return ToolResponse.success(
            text=f"找到 {len(candidates)} 个结果。",
            data={
                "total_results": raw.get("total_results", 0),
                "returned_count": len(candidates),
                "candidates": candidates,
            },
        )

    def _normalize_query(self, parameters: dict[str, Any]) -> str:
        if not isinstance(parameters, dict):
            raise ValueError("搜索参数必须是一个对象。")

        unknown = sorted(set(parameters) - {"query", "media_type"})
        if unknown:
            raise ValueError(f"不支持的搜索参数: {', '.join(unknown)}")

        query = str(parameters.get("query") or "").strip()
        if not query:
            raise ValueError("搜索关键词不能为空。")
        if len(query) > self._MAX_QUERY_LENGTH:
            raise ValueError(f"搜索关键词不能超过 {self._MAX_QUERY_LENGTH} 个字符。")

        media_type = parameters.get("media_type")
        if media_type is not None and media_type not in self._MEDIA_TYPES:
            raise ValueError(
                f"media_type 必须是以下之一: {', '.join(self._MEDIA_TYPES)}。"
            )

        return query

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "tmdb_id": item.get("id"),
            "title": item.get("title") or item.get("name") or "未知标题",
            "original_title": item.get("original_title")
            or item.get("original_name")
            or None,
            "media_type": item.get("media_type"),
            "overview": item.get("overview") or "",
            "release_date": item.get("release_date")
            or item.get("first_air_date")
            or None,
            "popularity": item.get("popularity"),
            "vote_average": item.get("vote_average"),
            "vote_count": item.get("vote_count"),
        }
