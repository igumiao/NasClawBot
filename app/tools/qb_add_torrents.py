"""QBAddTorrentsTool - batch M-Team detail/token -> qB add (paused)."""

from __future__ import annotations

import json
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.tools.qb_add_torrent import QBAddTorrentTool


MAX_BATCH_ITEMS = 10


class QBAddTorrentsTool(Tool):
    """Batch equivalent of QBAddTorrentTool for one user download intent."""

    def __init__(
        self,
        mteam_adapter: MTeamAdapter,
        qb_adapter: QBittorrentAdapter,
        default_save_path: str | None = None,
    ) -> None:
        super().__init__(
            name="qb_add_torrents",
            description=(
                "批量通过 M-Team torrent ID 执行下载：逐项获取详情、生成下载链接、添加到 qBittorrent。"
                "当同一用户请求需要添加多个 torrent 时优先使用本工具。所有任务都会以暂停状态添加；"
                f"单批最多 {MAX_BATCH_ITEMS} 个。"
            ),
        )
        self._single_tool = QBAddTorrentTool(mteam_adapter, qb_adapter, default_save_path=default_save_path)

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

        results: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for index, item in enumerate(items):
            torrent_id = str(item.get("torrent_id") or "").strip()
            if not torrent_id:
                failed += 1
                results.append(
                    {
                        "index": index,
                        "torrent_id": "",
                        "status": "error",
                        "error": {"code": "INVALID_PARAM", "message": "torrent_id is required."},
                    }
                )
                continue

            single_params: dict[str, Any] = {"torrent_id": torrent_id}
            qb_category = str(item.get("qb_category") or item.get("category") or "").strip()
            if qb_category:
                single_params["qb_category"] = qb_category
            save_path = str(item.get("save_path") or "").strip()
            if save_path:
                single_params["save_path"] = save_path
            user_tag = str(item.get("tag") or "").strip()
            if user_tag:
                single_params["tag"] = user_tag
            internal_tag = str(item.get("internal_tag") or "").strip() or None
            if internal_tag:
                single_params["internal_tag"] = internal_tag

            response = self._single_tool.run(single_params)
            row: dict[str, Any] = {
                "index": index,
                "torrent_id": torrent_id,
                "qb_category": qb_category,
                "save_path": save_path or None,
                "status": response.status.value,
            }
            if response.status.value == "success":
                succeeded += 1
                receipt = dict(response.data.get("receipt") or {})
                receipts.append(receipt)
                row["receipt"] = receipt
            else:
                failed += 1
                row["error"] = response.error_info or {"message": response.text}
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
            },
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
