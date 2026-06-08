"""QBAddTorrentTool — M-Team detail → genDlToken → qB add (paused)."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.services.receipt_service import build_receipt


class QBAddTorrentTool(Tool):
    """Execute the full download chain: M-Team detail → genDlToken → qB add (paused)."""

    def __init__(self, mteam_adapter: MTeamAdapter, qb_adapter: QBittorrentAdapter) -> None:
        super().__init__(
            name="qb_add_torrent",
            description="通过 M-Team torrent ID 执行下载：获取详情→生成下载链接→添加到 qBittorrent（暂停状态）",
        )
        self._mteam = mteam_adapter
        self._qb = qb_adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_id",
                type="string",
                description="M-Team torrent ID",
                required=True,
            ),
            ToolParameter(
                name="qb_category",
                type="string",
                description="qBittorrent 分类名称。从预设中选择最适合的分类",
                required=False,
                enum=["电影", "电视剧", "综艺", "动漫", "纪录片"],
            ),
            ToolParameter(
                name="save_path",
                type="string",
                description="自定义保存路径（可选）。不传则使用 qBittorrent 默认路径",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        torrent_id = str(parameters.get("torrent_id", ""))
        qb_category = str(parameters.get("qb_category", ""))
        if not torrent_id.strip():
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="torrent_id is required for qB add.",
            )

        detail = self._mteam.get_torrent_details(torrent_id)
        if not detail:
            return ToolResponse.error(
                code="DETAIL_FAILED",
                message=f"Failed to get torrent details for id={torrent_id}.",
            )

        download_url = self._mteam.get_torrent_download_url(torrent_id)
        if not download_url:
            return ToolResponse.error(
                code="DOWNLOAD_URL_FAILED",
                message=f"Failed to generate download URL for id={torrent_id}.",
            )

        if not self._mteam.is_download_url_torrent(download_url):
            return ToolResponse.error(
                code="DOWNLOAD_URL_INVALID",
                message=f"Download URL is not a torrent for id={torrent_id}.",
            )

        rename = self._qb.generate_mteam_torrent_name(torrent_id, detail, qb_category)
        add_kwargs: dict[str, Any] = {
            "url": download_url,
            "category": qb_category,
            "rename": rename,
            "tags": ["mteam"],
            "paused": True,
        }
        save_path = str(parameters.get("save_path", "")).strip()
        if save_path:
            add_kwargs["save_path"] = save_path

        add_result = self._qb.add_torrent_url(**add_kwargs)

        if add_result.get("ok"):
            title = str(detail.get("title") or torrent_id)
            qb_hash = add_result.get("qb_hash")
            status = str(add_result.get("status", "submitted_paused"))
            receipt = build_receipt(
                resource_title=title,
                external_id=torrent_id,
                qb_category=qb_category,
                qb_hash=str(qb_hash) if qb_hash else None,
                status=status,
            )
            return ToolResponse.success(
                text=f"Download submitted (paused): {title}",
                data={"receipt": receipt},
            )

        return ToolResponse.error(
            code="SUBMIT_FAILED",
            message=f"qBittorrent add failed for id={torrent_id}.",
        )
