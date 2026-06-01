"""NasClawBot tool wrappers.

Each tool wraps an existing adapter operation behind the Tool protocol.
Permission remains tool metadata for future Agent loop policy decisions.
"""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.permissions import ToolPermission
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.models import ResourceCandidate
from app.services.receipt_service import build_receipt


class MTeamSearchTool(Tool):
    """Search M-Team by keyword and return structured candidates."""

    permission = ToolPermission.READONLY

    def __init__(self, adapter: MTeamAdapter) -> None:
        super().__init__(
            name="mteam_search",
            description="搜索 M-Team 资源站，返回匹配的种子候选列表",
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="keyword",
                type="string",
                description="搜索关键词",
                required=True,
            )
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        keyword = parameters.get("keyword", "")
        if not keyword.strip():
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="keyword is required for M-Team search.",
            )
        rows = self._adapter.search_torrents_by_keyword(
            keyword=keyword.strip(),
            page=1,
            page_size=20,
        )
        candidates: list[ResourceCandidate] = []
        for row in rows:
            title = str(row.get("title") or row.get("name") or f"M-Team {row.get('id', '')}")
            lowered_title = title.lower()
            media_type = "movie"
            if "s01" in lowered_title or "season" in lowered_title:
                media_type = "tv"
            candidates.append(
                ResourceCandidate(
                    id=str(row.get("id")),
                    title=title,
                    media_type=media_type,
                    resolution="2160p" if "2160" in lowered_title or "4k" in lowered_title else "1080p",
                    seeders=int(row.get("seeders", 0) or 0),
                    size=str(row.get("size", "unknown")),
                    size_bytes=int(row["size_bytes"]) if row.get("size_bytes") is not None else None,
                    source="mteam",
                )
            )
        return ToolResponse.success(
            text=f"Found {len(candidates)} candidates for '{keyword}'.",
            data={"candidates": [c.model_dump() for c in candidates]},
        )


class QBAddTorrentTool(Tool):
    """Execute the full download chain: M-Team detail → genDlToken → qB add (paused)."""

    permission = ToolPermission.SIDE_EFFECT

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
                description="qBittorrent 分类名称",
                required=True,
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
        add_result = self._qb.add_torrent_url(
            url=download_url,
            category=qb_category,
            rename=rename,
            tags=["mteam"],
            paused=True,
        )

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
