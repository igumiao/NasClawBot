"""QBAddTorrentsTool — batch torrent submission via DownloadAutomation."""

from __future__ import annotations

import json
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.domain.downloads import DownloadSubmissionRequest
from app.services.download_automation import DownloadAutomation, DownloadAutomationError


MAX_BATCH_ITEMS = 10


class QBAddTorrentsTool(Tool):
    """Batch equivalent of QBAddTorrentTool via DownloadAutomation.

    Thin adapter: builds a list of DownloadSubmissionRequest from the Agent
    tool parameters and delegates to the coordinator's submit_many(),
    preserving all existing behavior (paused adds, media tags, subtitle
    auto-download, partial success reporting, and batch receipt shape).
    """

    def __init__(
        self,
        download_automation: DownloadAutomation,
    ) -> None:
        super().__init__(
            name="qb_add_torrents",
            description=(
                "批量通过 M-Team torrent ID 执行下载：逐项获取详情、生成下载链接、添加到 qBittorrent。"
                "当同一用户请求需要添加多个 torrent 时优先使用本工具。所有任务都会以暂停状态添加；"
                f"单批最多 {MAX_BATCH_ITEMS} 个。"
            ),
        )
        self._automation = download_automation

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="items",
                type="array",
                description=(
                    "要添加的 torrent 列表。每项是对象："
                    '{"torrent_id":"M-Team torrent ID","save_path":"可选保存路径","tag":"可选标签 如 电影"}'
                ),
                required=True,
            ),
            ToolParameter(
                name="completion_action",
                type="string",
                description="整批完成动作，必填：none、notify 或 organize；不同动作请拆分调用",
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        items, error = _coerce_items(parameters.get("items"))
        if error:
            return ToolResponse.error(code="INVALID_PARAM", message=error)
        if not items:
            return ToolResponse.error(code="INVALID_PARAM", message="items must not be empty.")
        if len(items) > MAX_BATCH_ITEMS:
            return ToolResponse.error(
                code="BATCH_TOO_LARGE",
                message=f"qb_add_torrents supports at most {MAX_BATCH_ITEMS} items per batch.",
            )
        completion_action = str(parameters.get("completion_action") or "").strip()
        if completion_action not in {"none", "notify", "organize"}:
            return ToolResponse.error(
                code="INVALID_COMPLETION_ACTION",
                message="completion_action must be none, notify, or organize.",
            )

        # Build per-item requests from tool parameters.
        requests: list[DownloadSubmissionRequest] = []
        for item in items:
            requests.append(DownloadSubmissionRequest(
                torrent_id=str(item.get("torrent_id") or "").strip(),
                qb_category=str(item.get("qb_category") or item.get("category") or "").strip(),
                save_path=str(item.get("save_path") or "").strip() or None,
                tag=str(item.get("tag") or "").strip() or None,
            ))
        try:
            from app.agent.runner import current_agent_session_id

            batch_result = self._automation.submit_downloads(
                requests,
                completion_action=completion_action,  # type: ignore[arg-type]
                source_session_id=current_agent_session_id.get(),
                idempotency_key=str(parameters.get("idempotency_key") or ""),
            )
        except DownloadAutomationError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)

        results: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for index, (req, item_result) in enumerate(zip(requests, batch_result.items)):
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
                error_code = "CONFLICT" if item_result.status == "duplicate" else "SUBMIT_FAILED"
                row["error"] = {"code": error_code, "message": item_result.error or "Unknown error"}
            results.append(row)

        summary = {
            "total": len(items),
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

        if succeeded == len(items):
            return ToolResponse.success(
                text=f"Batch download submitted (paused): {succeeded}/{len(items)} items.",
                data=data,
            )
        if succeeded > 0:
            return ToolResponse.partial(
                text=f"Batch download partially submitted (paused): {succeeded}/{len(items)} items.",
                data=data,
            )
        return ToolResponse.error(
            code="BATCH_FAILED",
            message=f"批量下载全部失败: 0/{len(items)} items submitted. 请检查 qBittorrent 连接状态和各 item 的错误信息。",
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
