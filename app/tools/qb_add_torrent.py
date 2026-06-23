"""QBAddTorrentTool — single torrent submission via DownloadAutomation."""

from __future__ import annotations

import logging
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.domain.downloads import DownloadSubmissionRequest
from app.services.download_automation import DownloadAutomation, DownloadAutomationError

logger = logging.getLogger(__name__)


class QBAddTorrentTool(Tool):
    """Submit one torrent through DownloadAutomation.

    Thin adapter: builds a DownloadSubmissionRequest from the Agent tool
    parameters and delegates to the automation service, preserving all existing
    behavior (paused adds, media tags, subtitle auto-download, and receipt
    shape).
    """

    def __init__(
        self,
        download_automation: DownloadAutomation,
    ) -> None:
        super().__init__(
            name="qb_add_torrent",
            description="通过 M-Team torrent ID 执行下载：获取详情→生成下载链接→添加到 qBittorrent（暂停状态）",
        )
        self._automation = download_automation

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_id",
                type="string",
                description="M-Team torrent ID",
                required=True,
            ),
            ToolParameter(
                name="save_path",
                type="string",
                description="自定义保存路径（可选）。不传则自动使用默认路径",
                required=False,
            ),
            ToolParameter(
                name="tag",
                type="string",
                description="可选标签，用于后续列表过滤。如 电影、电视剧、综艺、动漫、纪录片。不传则仅标记 mteam",
                required=False,
            ),
            ToolParameter(
                name="completion_action",
                type="string",
                description=(
                    "下载完成动作，必填：none 仅提交；notify 持续监督并通知；"
                    "organize 持续监督并整理。用户仅说下载时使用 notify，只有明确要求整理时使用 organize。"
                ),
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_id = str(parameters.get("torrent_id", "")).strip()
        if not torrent_id:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_id is required for qB add.",
            )

        # qb_category is NOT exposed via get_parameters() but may be passed
        # by the batch tool (QBAddTorrentsTool) or the /download route.
        qb_category = str(parameters.get("qb_category", "")).strip()
        completion_action = str(parameters.get("completion_action") or "").strip()
        if completion_action not in {"none", "notify", "organize"}:
            return ToolResponse.error(
                code="INVALID_COMPLETION_ACTION",
                message="completion_action must be none, notify, or organize.",
            )

        request = DownloadSubmissionRequest(
            torrent_id=torrent_id,
            qb_category=qb_category,
            save_path=str(parameters.get("save_path", "")).strip() or None,
            tag=str(parameters.get("tag", "")).strip() or None,
        )
        try:
            from app.agent.runner import current_agent_session_id

            batch = self._automation.submit_downloads(
                [request],
                completion_action=completion_action,  # type: ignore[arg-type]
                source_session_id=current_agent_session_id.get(),
                idempotency_key=str(parameters.get("idempotency_key") or ""),
            )
            result = batch.items[0]
        except DownloadAutomationError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)

        if result.status == "accepted":
            receipt = result.submission_receipt or {}
            title = str(receipt.get("resource_title") or torrent_id)
            return ToolResponse.success(
                text=f"Download submitted (paused): {title}",
                data={
                    "receipt": receipt,
                    "watch_task_id": result.watch_task_id,
                    "completion_action": completion_action,
                },
            )

        # Error / duplicate path
        error_msg = result.error or "Unknown submission error"
        error_code = "CONFLICT" if result.status == "duplicate" else "SUBMIT_FAILED"
        return ToolResponse.error(
            code=error_code,
            message=f"[{error_code}] {error_msg} (torrent_id={torrent_id})",
        )
