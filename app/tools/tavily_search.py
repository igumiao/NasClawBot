"""TavilySearchTool -- web search for entity clarification."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.tavily import TavilyAdapter, TavilyError


class TavilySearchTool(Tool):
    """Search the public web and return compact source snippets."""

    _TIME_RANGES = ("day", "week", "month", "year")
    _DEFAULT_MAX_RESULTS = 5
    _MAX_RESULTS = 10
    _MAX_QUERY_LENGTH = 300

    def __init__(self, adapter: TavilyAdapter) -> None:
        super().__init__(
            name="tavily_search",
            description=(
                "搜索互联网以澄清影视实体、别名、年份、最新资讯或角色相关作品。"
                "适合在用户描述模糊、提到最近新出、角色、剧情、演员或不确定标题时使用。"
                "可使用中文、英文或中英混合查询；同一问题可多次搜索不同语言线索。"
                "返回网页标题、URL、摘要和相关性分数；不要用它直接查找下载资源。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="网络搜索关键词。可使用中文、英文或中英混合；同一问题可分别搜索不同语言版本以交叉验证。",
                required=True,
            ),
            ToolParameter(
                name="max_results",
                type="integer",
                description="最多返回多少条网页结果，默认 5，最大 10。",
                required=False,
                default=self._DEFAULT_MAX_RESULTS,
            ),
            ToolParameter(
                name="time_range",
                type="string",
                description="限制结果时间范围。用户强调最近、新出、今日、本周时可使用。",
                required=False,
                enum=list(self._TIME_RANGES),
            ),
        ]

    def to_openai_schema(self) -> dict[str, Any]:
        schema = super().to_openai_schema()
        schema["function"]["parameters"]["additionalProperties"] = False
        return schema

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            query, max_results, time_range = self._normalize_parameters(parameters)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        try:
            raw = self._adapter.search(
                query,
                max_results=max_results,
                time_range=time_range,
            )
        except TavilyError as exc:
            return ToolResponse.error(
                code="TAVILY_ERROR",
                message=f"Tavily 搜索失败: {exc}",
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"网络搜索时发生内部错误: {exc}",
            )

        results = raw.get("results", [])
        candidates = [self._normalize_result(item) for item in results[:max_results]]
        credits = self._usage_credits(raw.get("usage"))
        return ToolResponse.success(
            text=f"网络搜索找到 {len(candidates)} 条结果。",
            data={
                "query": raw.get("query") or query,
                "returned_count": len(candidates),
                "results": candidates,
                "usage_credits": credits,
            },
        )

    def _normalize_parameters(
        self,
        parameters: dict[str, Any],
    ) -> tuple[str, int, str | None]:
        if not isinstance(parameters, dict):
            raise ValueError("Tavily search parameters must be an object.")

        unknown = sorted(set(parameters) - {"query", "max_results", "time_range"})
        if unknown:
            raise ValueError(f"Unsupported Tavily search parameters: {', '.join(unknown)}")

        query = str(parameters.get("query") or "").strip()
        if not query:
            raise ValueError("query is required.")
        if len(query) > self._MAX_QUERY_LENGTH:
            raise ValueError(f"query must be <= {self._MAX_QUERY_LENGTH} characters.")

        raw_max_results = parameters.get("max_results", self._DEFAULT_MAX_RESULTS)
        try:
            max_results = int(raw_max_results)
        except (TypeError, ValueError):
            raise ValueError("max_results must be an integer.") from None
        if max_results < 1:
            raise ValueError("max_results must be >= 1.")
        max_results = min(max_results, self._MAX_RESULTS)

        time_range = parameters.get("time_range")
        if time_range is not None:
            time_range = str(time_range).strip().lower()
            if time_range not in self._TIME_RANGES:
                raise ValueError(f"time_range must be one of: {', '.join(self._TIME_RANGES)}.")

        return query, max_results, time_range

    @staticmethod
    def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": item.get("title") or "Untitled",
            "url": item.get("url") or "",
            "content": item.get("content") or "",
            "score": item.get("score"),
        }

    @staticmethod
    def _usage_credits(usage: Any) -> int | None:
        if not isinstance(usage, dict):
            return None
        credits = usage.get("credits")
        if credits is None:
            return None
        try:
            return int(credits)
        except (TypeError, ValueError):
            return None
