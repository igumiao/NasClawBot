"""MTeamSearchTool — search M-Team by keyword."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.domain.models import ResourceCandidate


class MTeamSearchTool(Tool):
    """Search M-Team by keyword and return structured candidates."""

    def __init__(self, adapter: MTeamAdapter) -> None:
        super().__init__(
            name="mteam_search",
            description="搜索 M-Team 资源站，返回匹配的种子候选列表",
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="keyword",
                type="string",
                description="搜索关键词",
                required=True,
            )
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        keyword = parameters.get("keyword", "")
        if not keyword.strip():
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="keyword is required for M-Team search.",
            )
        rows = self._adapter.search_torrents_by_keyword(
            keyword=keyword.strip(),
            page=1,
            page_size=20,
        )
        candidates: list[ResourceCandidate] = []
        for row in rows:
            title = str(row.get("title") or row.get("name") or f"M-Team {row.get('id', '')}")
            lowered_title = title.lower()
            media_type = "movie"
            if "s01" in lowered_title or "season" in lowered_title:
                media_type = "tv"
            candidates.append(
                ResourceCandidate(
                    id=str(row.get("id")),
                    title=title,
                    media_type=media_type,
                    resolution="2160p" if "2160" in lowered_title or "4k" in lowered_title else "1080p",
                    seeders=int(row.get("seeders", 0) or 0),
                    size=str(row.get("size", "unknown")),
                    size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
                    source="mteam",
                )
            )
        return ToolResponse.success(
            text=f"Found {len(candidates)} candidates for '{keyword}'.",
            data={"candidates": [c.model_dump() for c in candidates]},
        )
