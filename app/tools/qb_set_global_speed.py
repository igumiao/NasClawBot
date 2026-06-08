"""QBSetGlobalSpeedTool — 设置 qBittorrent 全局传输限速."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter


class QBSetGlobalSpeedTool(Tool):
    """Set qBittorrent global upload/download speed limits."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_set_global_speed",
            description="设置 qBittorrent 全局传输限速。上传和下载限制均为可选，单位 bytes/s。例如 10MB/s = 10485760",
        )
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="upload_limit",
                type="integer",
                description="全局上传限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
            ToolParameter(
                name="download_limit",
                type="integer",
                description="全局下载限速，单位 bytes/s。不传则不修改",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        upload_limit = parameters.get("upload_limit")
        download_limit = parameters.get("download_limit")

        if upload_limit is None and download_limit is None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="至少需要指定 upload_limit 或 download_limit 之一。",
            )

        result = self._qb.set_global_speed_limits(
            upload_limit=upload_limit,
            download_limit=download_limit,
        )

        if result.get("ok"):
            parts = []
            if upload_limit is not None:
                parts.append(f"上传限速: {upload_limit} bytes/s ({upload_limit / 1048576:.1f} MB/s)")
            if download_limit is not None:
                parts.append(f"下载限速: {download_limit} bytes/s ({download_limit / 1048576:.1f} MB/s)")
            return ToolResponse.success(
                text=f"全局限速已设置: {'，'.join(parts)}",
                data={"result": result},
            )

        return ToolResponse.error(
            code="EXECUTION_FAILED",
            message=f"设置失败: {result.get('status', 'unknown')}",
        )
