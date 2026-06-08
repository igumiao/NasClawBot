"""QBGetTorrentTool — 查询单个 qBittorrent 种子详情."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBGetTorrentTool(Tool):
    """Query detailed information for a single qBittorrent torrent."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_get_torrent",
            description="查询单个 qBittorrent 种子的详细信息，包括进度、速度、保存路径、分享率等",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_hash",
                type="string",
                description="种子的 info hash",
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        torrent = self._qb.get_torrent(torrent_hash)
        if torrent is None:
            return ToolResponse.error(
                code="NOT_FOUND",
                message=f"未找到种子: {torrent_hash}",
            )

        return ToolResponse.success(
            text=f"种子详情: {torrent.get('name', torrent_hash)}",
            data={"torrent": torrent},
        )
