"""QBListCategoriesTool — 查询 qBittorrent 分类列表."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBListCategoriesTool(Tool):
    """List all categories configured in qBittorrent."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_list_categories",
            description="查询 qBittorrent 中已有的所有分类及其保存路径",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        categories = self._qb.list_categories()
        if not categories:
            return ToolResponse.success(
                text="qBittorrent 中暂无分类。",
                data={"categories": {}},
            )

        names = list(categories.keys())
        return ToolResponse.success(
            text=f"qBittorrent 中共有 {len(names)} 个分类: {', '.join(names)}",
            data={"categories": categories},
        )
