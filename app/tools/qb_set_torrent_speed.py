"""QBSetTorrentSpeedTool — 设置单个种子的传输限速."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBSetTorrentSpeedTool(Tool):
    """Set per-torrent upload/download speed limits."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_set_torrent_speed",
            description="设置单个种子的传输限速。上传和下载限制均为可选，单位 bytes/s。例如 10MB/s = 10485760",
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
            ToolParameter(
                name="upload_limit",
                type="integer",
                description="上传限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
            ToolParameter(
                name="download_limit",
                type="integer",
                description="下载限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        upload_limit = parameters.get("upload_limit")
        download_limit = parameters.get("download_limit")

        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        if upload_limit is None and download_limit is None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="至少需要指定 upload_limit 或 download_limit 之一。",
            )

        try:
            result = self._qb.set_torrent_speed_limits(
                torrent_hash=torrent_hash,
                upload_limit=upload_limit,
                download_limit=download_limit,
            )
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        if result.get("ok"):
            parts = []
            if upload_limit is not None:
                parts.append(f"上传限速: {upload_limit} bytes/s ({upload_limit / 1048576:.1f} MB/s)")
            if download_limit is not None:
                parts.append(f"下载限速: {download_limit} bytes/s ({download_limit / 1048576:.1f} MB/s)")
            return ToolResponse.success(
                text=f"种子 {torrent_hash} 限速已设置: {'，'.join(parts)}",
                data={"result": result},
            )

        return ToolResponse.error(
            code="EXECUTION_FAILED",
            message=f"设置失败: {result.get('status', 'unknown')}",
        )
