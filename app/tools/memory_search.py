"""MemorySearchTool -- read-only search over app markdown memory."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.markdown_memory_store import (
    DEFAULT_MEMORY_SEARCH_LIMIT,
    MAX_MEMORY_SEARCH_LIMIT,
    MarkdownMemoryStore,
)


class MemorySearchTool(Tool):
    """Search read-only markdown memory files."""

    _MAX_QUERY_LENGTH = 200

    def __init__(self, store: MarkdownMemoryStore | None = None) -> None:
        super().__init__(
            name="memory_search",
            description=(
                "只读搜索本应用的 markdown 知识库，"
                "用于补充当前对话上下文；不会写入记忆。"
            ),
        )
        self._store = store or MarkdownMemoryStore()

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="要在知识库中查找的文本，大小写不敏感。",
                required=True,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description=f"最多返回多少条命中，默认 {DEFAULT_MEMORY_SEARCH_LIMIT}，最大 {MAX_MEMORY_SEARCH_LIMIT}。",
                required=False,
                default=DEFAULT_MEMORY_SEARCH_LIMIT,
            ),
        ]

    def to_openai_schema(self) -> dict[str, Any]:
        schema = super().to_openai_schema()
        schema["function"]["parameters"]["additionalProperties"] = False
        return schema

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            query, limit = self._normalize_parameters(parameters)
        except ValueError as exc:
            return ToolResponse.error(code="INVALID_PARAM", message=str(exc))

        hits = self._store.search(query=query, limit=limit)
        payload_hits = [
            {
                "line_number": hit.line_number,
                "section": hit.section,
                "text": hit.text,
                "score": hit.score,
                "match_type": hit.match_type,
                "context": [
                    {
                        "line_number": line.line_number,
                        "text": line.text,
                    }
                    for line in hit.context or []
                ],
            }
            for hit in hits
        ]
        return ToolResponse.success(
            text=f"Memory search found {len(payload_hits)} hit(s).",
            data={
                "query": query,
                "limit": limit,
                "returned_count": len(payload_hits),
                "hits": payload_hits,
            },
        )

    def _normalize_parameters(
        self,
        parameters: dict[str, Any],
    ) -> tuple[str, int]:
        if not isinstance(parameters, dict):
            raise ValueError("memory_search parameters must be an object.")

        unknown = sorted(set(parameters) - {"query", "limit"})
        if unknown:
            raise ValueError(f"Unsupported memory_search parameters: {', '.join(unknown)}")

        query = str(parameters.get("query") or "").strip()
        if not query:
            raise ValueError("query is required.")
        if len(query) > self._MAX_QUERY_LENGTH:
            raise ValueError(f"query must be <= {self._MAX_QUERY_LENGTH} characters.")

        raw_limit = parameters.get("limit", DEFAULT_MEMORY_SEARCH_LIMIT)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer.") from None
        if limit < 1:
            raise ValueError("limit must be >= 1.")
        limit = min(limit, MAX_MEMORY_SEARCH_LIMIT)

        return query, limit
