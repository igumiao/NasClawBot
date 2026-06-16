"""QBControlTorrentTool — 控制 qBittorrent 种子状态（暂停/恢复/删除等）."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.qbittorrent import QBittorrentAdapter

_VALID_ACTIONS = {"pause", "resume", "recheck", "reannounce", "delete"}


class QBControlTorrentTool(Tool):
    """Control qBittorrent torrent lifecycle: pause, resume, recheck, reannounce, or delete."""

    def __init__(self, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_control_torrent",
            description="控制 qBittorrent 种子状态：暂停、恢复、重新校验、重新汇报 tracker、删除",
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
                name="action",
                type="string",
                description="操作类型",
                required=True,
                enum=list(_VALID_ACTIONS),
            ),
            ToolParameter(
                name="delete_files",
                type="boolean",
                description="删除时是否同时删除文件（仅 action=delete 时有效）",
                required=False,
                default=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        action = str(parameters.get("action", "")).strip().lower()
        delete_files = bool(parameters.get("delete_files", False))

        if not torrent_hash:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_hash is required.",
            )

        if action not in _VALID_ACTIONS:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"不支持的操作: {action}，支持的操作: {', '.join(sorted(_VALID_ACTIONS))}",
            )

        try:
            result = self._qb.control_torrent(torrent_hash, action=action, delete_files=delete_files)
        except ValueError as exc:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=str(exc),
            )

        if result.get("ok"):
            action_labels = {
                "pause": "已暂停",
                "resume": "已恢复",
                "recheck": "开始重新校验",
                "reannounce": "已重新汇报 tracker",
                "delete": "已删除",
            }
            label = action_labels.get(action, action)
            return ToolResponse.success(
                text=f"种子 {label}: {torrent_hash}",
                data={"result": result},
            )

        error_code = result.get("error_code", "UNKNOWN")
        error_message = result.get("error_message", str(result))
        retryable = result.get("retryable", False)
        retry_hint = " (可重试)" if retryable else ""
        return ToolResponse.error(
            code=error_code,
            message=f"[{error_code}] {error_message}{retry_hint} (hash={torrent_hash})",
        )
