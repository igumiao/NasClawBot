"""QBAddTorrentTool — single & batch torrent submission via DownloadAutomation.

Merged from the former QBAddTorrentTool + QBAddTorrentsTool so the Agent
has one tool for both single and batch download adds.  Provide *either*
``torrent_id`` (single) or ``items`` (batch), never both.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.domain.downloads import DownloadSubmissionRequest
from app.services.download_automation import DownloadAutomation, DownloadAutomationError

logger = logging.getLogger(__name__)

MAX_BATCH_ITEMS = 10


class QBAddTorrentTool(Tool):
    """Submit one or more torrents through DownloadAutomation.

    Thin adapter: builds DownloadSubmissionRequest(s) from Agent tool
    parameters and delegates to the automation service.  Supports both
    single-item (``torrent_id``) and batch-item (``items``) modes, with
    all existing behaviour preserved (paused adds, media tags, subtitle
    auto-download, and receipt shape).
    """

    def __init__(
        self,
        download_automation: DownloadAutomation,
    ) -> None:
        super().__init__(
            name="qb_add_torrent",
            description=(
                "通过 M-Team torrent ID 执行下载：获取详情→生成下载链接→添加到 qBittorrent（暂停状态）。"
                "单个种子传 torrent_id；批量传 items 数组，"
                f"单批最多 {MAX_BATCH_ITEMS} 项。"
            ),
        )
        self._automation = download_automation

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_id",
                type="string",
                description="M-Team torrent ID（单个种子时使用；与 items 互斥）",
                required=False,
            ),
            ToolParameter(
                name="save_path",
                type="string",
                description="自定义保存路径（可选）。不传则自动使用默认路径。仅与 torrent_id 配合使用",
                required=False,
            ),
            ToolParameter(
                name="tag",
                type="string",
                description="可选标签，用于后续列表过滤。如 电影、电视剧、综艺、动漫、纪录片。不传则仅标记 mteam。仅与 torrent_id 配合使用",
                required=False,
            ),
            ToolParameter(
                name="items",
                type="array",
                description=(
                    "批量添加的 torrent 列表（与 torrent_id 互斥）。每项是对象："
                    '{"torrent_id":"M-Team torrent ID","save_path":"可选保存路径","tag":"可选标签 如 电影"}'
                ),
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
        items_raw = parameters.get("items")

        # ── Mode detection ────────────────────────────────────────────
        if torrent_id and items_raw is not None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="Specify either torrent_id (single) or items (batch), not both.",
            )
        if not torrent_id and items_raw is None:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="Either torrent_id or items is required.",
            )

        completion_action = str(parameters.get("completion_action") or "").strip()
        if completion_action not in {"none", "notify", "organize"}:
            return ToolResponse.error(
                code="INVALID_COMPLETION_ACTION",
                message="completion_action must be none, notify, or organize.",
            )

        # ── Build request list ────────────────────────────────────────
        if torrent_id:
            # Single-item mode — build a one-element list.
            requests = [
                DownloadSubmissionRequest(
                    torrent_id=torrent_id,
                    qb_category=str(parameters.get("qb_category", "")).strip(),
                    save_path=str(parameters.get("save_path", "")).strip() or None,
                    tag=str(parameters.get("tag", "")).strip() or None,
                )
            ]
        else:
            # Batch mode — coerce & validate items.
            items, error = _coerce_items(items_raw)
            if error:
                return ToolResponse.error(code="INVALID_PARAM", message=error)
            if not items:
                return ToolResponse.error(
                    code="INVALID_PARAM", message="items must not be empty."
                )
            if len(items) > MAX_BATCH_ITEMS:
                return ToolResponse.error(
                    code="BATCH_TOO_LARGE",
                    message=f"qb_add_torrent supports at most {MAX_BATCH_ITEMS} items per batch.",
                )

            requests = []
            for item in items:
                requests.append(
                    DownloadSubmissionRequest(
                        torrent_id=str(item.get("torrent_id") or "").strip(),
                        qb_category=str(
                            item.get("qb_category") or item.get("category") or ""
                        ).strip(),
                        save_path=str(item.get("save_path") or "").strip() or None,
                        tag=str(item.get("tag") or "").strip() or None,
                    )
                )

        # ── Submit ────────────────────────────────────────────────────
        try:
            from app.agent.runner import current_agent_session_id

            batch = self._automation.submit_downloads(
                requests,
                completion_action=completion_action,  # type: ignore[arg-type]
                source_session_id=current_agent_session_id.get(),
                idempotency_key=str(parameters.get("idempotency_key") or ""),
            )
        except DownloadAutomationError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)

        # ── Format response ───────────────────────────────────────────
        if torrent_id:
            # Single-item response (backward-compatible shape).
            result = batch.items[0]
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
            error_msg = result.error or "Unknown submission error"
            error_code = "CONFLICT" if result.status == "duplicate" else "SUBMIT_FAILED"
            return ToolResponse.error(
                code=error_code,
                message=f"[{error_code}] {error_msg} (torrent_id={torrent_id})",
            )

        # Batch response (backward-compatible shape).
        results: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for index, (req, item_result) in enumerate(zip(requests, batch.items)):
            row: dict[str, Any] = {
                "index": index,
                "torrent_id": req.torrent_id,
                "qb_category": req.qb_category,
                "save_path": req.save_path,
                "status": "success" if item_result.status == "accepted" else "error",
            }
            if item_result.status == "accepted":
                succeeded += 1
                receipt = dict(item_result.submission_receipt or {})
                receipts.append(receipt)
                row["receipt"] = receipt
                row["watch_task_id"] = item_result.watch_task_id
            else:
                failed += 1
                error_code = (
                    "CONFLICT"
                    if item_result.status == "duplicate"
                    else "SUBMIT_FAILED"
                )
                row["error"] = {
                    "code": error_code,
                    "message": item_result.error or "Unknown error",
                }
            results.append(row)

        summary = {
            "total": len(requests),
            "succeeded": succeeded,
            "failed": failed,
        }
        data = {
            "summary": summary,
            "items": results,
            "receipts": receipts,
            "receipt": {
                "type": "batch",
                "status": "submitted_paused" if failed == 0 else "partial",
                "summary": summary,
                "receipts": receipts,
                "completion_action": completion_action,
            },
            "completion_action": completion_action,
        }

        if succeeded == len(requests):
            return ToolResponse.success(
                text=f"Batch download submitted (paused): {succeeded}/{len(requests)} items.",
                data=data,
            )
        if succeeded > 0:
            return ToolResponse.partial(
                text=f"Batch download partially submitted (paused): {succeeded}/{len(requests)} items.",
                data=data,
            )
        return ToolResponse.error(
            code="BATCH_FAILED",
            message=(
                f"批量下载全部失败: 0/{len(requests)} items submitted. "
                "请检查 qBittorrent 连接状态和各 item 的错误信息。"
            ),
            data=data,
        )


def _coerce_items(value: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [], "items must be a list of objects or a JSON encoded list."
    if not isinstance(value, list):
        return [], "items must be a list of objects."

    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return [], f"items[{index}] must be an object."
        items.append(dict(item))
    return items, None
