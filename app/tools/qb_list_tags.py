"""QBListTagsTool — 查询 qBittorrent 标签列表."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBListTagsTool(Tool):
    """List all tags present on torrents in qBittorrent."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_list_tags",
            description="查询 qBittorrent 中所有已存在的标签。下载时可用这些标签标记种子，方便后续按标签过滤列表。",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        tags = self._qb.list_tags()
        if not tags:
            return ToolResponse.success(
                text="qBittorrent 中暂无标签。",
                data={"tags": []},
            )

        return ToolResponse.success(
            text=f"qBittorrent 中共有 {len(tags)} 个标签: {', '.join(tags)}",
            data={"tags": tags},
        )
