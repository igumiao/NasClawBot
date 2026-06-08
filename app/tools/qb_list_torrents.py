"""QBListTorrentsTool — 查询 qBittorrent 种子列表."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBListTorrentsTool(Tool):
    """Query the qBittorrent torrent list with optional filters."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_list_torrents",
            description="查询 qBittorrent 种子列表，可按分类、标签、状态筛选，支持排序和数量限制",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="category",
                type="string",
                description="按分类筛选，如 movie、tvshow、music",
                required=False,
            ),
            ToolParameter(
                name="tag",
                type="string",
                description="按标签筛选，如 mteam",
                required=False,
            ),
            ToolParameter(
                name="status_filter",
                type="string",
                description="按状态筛选: downloading, seeding, paused, queued, checking, error",
                required=False,
            ),
            ToolParameter(
                name="sort",
                type="string",
                description="排序字段，如 name、size、progress、dlspeed、eta",
                required=False,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="返回条数上限，默认返回全部",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        kwargs: dict[str, Any] = {}
        if parameters.get("category"):
            kwargs["category"] = parameters["category"]
        if parameters.get("tag"):
            kwargs["tag"] = parameters["tag"]
        if parameters.get("status_filter"):
            kwargs["status_filter"] = parameters["status_filter"]
        if parameters.get("sort"):
            kwargs["sort"] = parameters["sort"]
        if parameters.get("limit") is not None:
            kwargs["limit"] = parameters["limit"]

        torrents = self._qb.list_torrents(**kwargs)

        if not torrents:
            return ToolResponse.success(
                text="当前没有符合条件的种子任务。",
                data={"torrents": [], "count": 0},
            )

        return ToolResponse.success(
            text=f"共 {len(torrents)} 个种子任务。",
            data={"torrents": torrents, "count": len(torrents)},
        )
