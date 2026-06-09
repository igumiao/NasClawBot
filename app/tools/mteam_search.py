"""MTeamSearchTool — search M-Team with a small Agent-facing query surface."""

from __future__ import annotations

import re
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.domain.models import ResourceCandidate


class MTeamSearchTool(Tool):
    """Search M-Team and return a compact list of structured candidates."""

    _SORTS = {
        "smallest": ("SIZE", "ASC"),
        "largest": ("SIZE", "DESC"),
        "most_seeded": ("SEEDERS", "DESC"),
    }
    _RESULT_LIMIT = 10

    def __init__(self, adapter: MTeamAdapter) -> None:
        super().__init__(
            name="mteam_search",
            description=(
                "搜索 M-Team 资源站，默认按最新发布排序，最多返回 10 个候选。"
                "资源标题多为英文/原名，keyword 优先使用英文标题、原名或罗马字标题。"
            ),
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="keyword",
                type="string",
                description=(
                    "搜索关键词。优先使用英文标题、原名或罗马字标题；"
                    "中文名、别名可作为补充搜索。浏览最新资源或使用 IMDb/豆瓣 ID 搜索时可以省略或传空字符串。"
                ),
                required=False,
            ),
            ToolParameter(
                name="sort_by",
                type="string",
                description="可选排序方式。省略时使用 M-Team 默认排序，即按创建时间降序。",
                required=False,
                enum=list(self._SORTS),
            ),
            ToolParameter(
                name="imdb",
                type="string",
                description="IMDb ID，例如 tt1160419。可与 keyword 组合为 AND 查询。",
                required=False,
            ),
            ToolParameter(
                name="douban",
                type="string",
                description="豆瓣 ID，例如 3001114。可与 keyword 组合为 AND 查询；与 IMDb 同传时为 OR 查询。",
                required=False,
            ),
        ]

    def to_openai_schema(self) -> dict[str, Any]:
        schema = super().to_openai_schema()
        schema["function"]["parameters"]["additionalProperties"] = False
        return schema

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            query = self._normalize_query(parameters)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        sort_field = None
        sort_direction = None
        if query["sort_by"]:
            sort_field, sort_direction = self._SORTS[query["sort_by"]]

        rows = self._adapter.search_torrents_by_keyword(
            keyword=query["keyword"],
            page=1,
            page_size=20,
            mode="normal",
            sort_field=sort_field,
            sort_direction=sort_direction,
            imdb=query["imdb"],
            douban=query["douban"],
        )
        candidates: list[ResourceCandidate] = []
        for row in rows[: self._RESULT_LIMIT]:
            title = str(row.get("title") or row.get("name") or f"M-Team {row.get('id', '')}")
            resolution_source = row.get("small_description") or row.get("name") or title
            candidates.append(
                ResourceCandidate(
                    id=str(row.get("id")),
                    title=title,
                    media_type="unknown",
                    resolution=self._resolution(str(resolution_source)),
                    seeders=int(row.get("seeders", 0) or 0),
                    leechers=int(row.get("leechers", 0) or 0),
                    discount=str(row.get("discount")) if row.get("discount") else None,
                    imdb=str(row.get("imdb")) if row.get("imdb") else None,
                    douban=str(row.get("douban")) if row.get("douban") else None,
                    size=str(row.get("size", "unknown")),
                    size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
                    source="mteam",
                )
            )
        return ToolResponse.success(
            text=f"Found {len(candidates)} candidates from {len(rows)} matching M-Team results.",
            data={
                "applied_query": {key: value for key, value in query.items() if value not in (None, "")},
                "pool_count": len(rows),
                "returned_count": len(candidates),
                "candidates": [c.model_dump() for c in candidates],
            },
        )

    def _normalize_query(self, parameters: dict[str, Any]) -> dict[str, str | None]:
        if not isinstance(parameters, dict):
            raise ValueError("M-Team search parameters must be an object.")

        unknown = sorted(set(parameters) - {"keyword", "sort_by", "imdb", "douban"})
        if unknown:
            raise ValueError(f"Unsupported M-Team search parameters: {', '.join(unknown)}")

        keyword = str(parameters.get("keyword") or "").strip()
        sort_by = str(parameters.get("sort_by") or "").strip().lower() or None
        imdb = str(parameters.get("imdb") or "").strip() or None
        douban = str(parameters.get("douban") or "").strip() or None

        if len(keyword) > 100:
            raise ValueError("keyword must be <= 100 characters.")
        if sort_by is not None and sort_by not in self._SORTS:
            raise ValueError(f"sort_by must be one of: {', '.join(self._SORTS)}.")
        if imdb is not None and len(imdb) > 32:
            raise ValueError("imdb must be <= 32 characters.")
        if douban is not None and len(douban) > 32:
            raise ValueError("douban must be <= 32 characters.")

        return {
            "keyword": keyword,
            "sort_by": sort_by,
            "imdb": imdb,
            "douban": douban,
        }

    @staticmethod
    def _resolution(source_text: str) -> str | None:
        lowered_text = source_text.lower()
        if "4320p" in lowered_text or re.search(r"(?<!\d)8k(?!\d)", lowered_text):
            return "4320p"
        if "2160p" in lowered_text or re.search(r"(?<!\d)4k(?!\d)", lowered_text):
            return "2160p"
        if "1080p" in lowered_text:
            return "1080p"
        if "720p" in lowered_text:
            return "720p"
        return None
