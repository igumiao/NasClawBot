"""QBAddTorrentTool — M-Team detail → genDlToken → qB add (paused) → community subtitles."""

from __future__ import annotations

import logging
import os
from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.services.receipt_service import build_receipt

logger = logging.getLogger(__name__)


class QBAddTorrentTool(Tool):
    """Execute the full download chain: M-Team detail → genDlToken → qB add (paused)."""

    def __init__(
        self,
        mteam_adapter: MTeamAdapter,
        qb_adapter: QBittorrentAdapter,
        default_save_path: str | None = None,
        default_tags: list[str] | None = None,
    ) -> None:
        super().__init__(
            name="qb_add_torrent",
            description="通过 M-Team torrent ID 执行下载：获取详情→生成下载链接→添加到 qBittorrent（暂停状态）",
        )
        self._mteam = mteam_adapter
        self._qb = qb_adapter
        self._default_save_path = (default_save_path or "").strip() or None
        self._default_tags = list(default_tags) if default_tags else ["mteam"]

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

        user_tag = str(parameters.get("tag", "")).strip()
        tags = list(self._default_tags)
        if user_tag:
            tags.append(user_tag)

        # internal_tag is programmatic-only (NOT exposed in Agent schema)
        internal_tag = str(parameters.get("internal_tag", "")).strip() or None
        add_tags = [f"nasclaw-task-{internal_tag}"] if internal_tag else None

        rename = self._qb.generate_mteam_torrent_name(torrent_id, detail, qb_category)
        add_kwargs: dict[str, Any] = {
            "url": download_url,
            "category": qb_category,
            "rename": rename,
            "tags": tags,
            "paused": True,
        }
        save_path = str(parameters.get("save_path", "")).strip()
        if not save_path and self._default_save_path:
            save_path = self._default_save_path
        if save_path:
            add_kwargs["save_path"] = save_path

        add_result = self._qb.add_torrent_url(**add_kwargs, add_tags=add_tags)

        if add_result.get("ok"):
            title = str(detail.get("title") or torrent_id)
            qb_hash = add_result.get("qb_hash")
            status = str(add_result.get("status", "submitted_paused"))

            # Auto-download community subtitles when available.
            subtitle_count = 0
            if detail.get("hasChineseSubtitle"):
                subtitle_count = self._download_subtitles(
                    torrent_id=torrent_id,
                    save_path=save_path,
                )

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

        error_code = add_result.get("error_code", "UNKNOWN")
        error_message = add_result.get("error_message", str(add_result))
        retryable = add_result.get("retryable", False)
        retry_hint = " (可重试)" if retryable else ""
        return ToolResponse.error(
            code=error_code,
            message=f"[{error_code}] {error_message}{retry_hint} (torrent_id={torrent_id})",
        )

    def _download_subtitles(
        self, *, torrent_id: str, save_path: str | None,
    ) -> int:
        """Download community subtitles for a torrent to save_path.

        Non-blocking: failures are logged but never raised.
        Returns the number of successfully downloaded subtitle files.
        """
        subs = self._mteam.list_subtitles(torrent_id)
        if not subs:
            return 0

        target_dir = save_path or ""
        if target_dir:
            try:
                os.makedirs(target_dir, exist_ok=True)
            except OSError:
                logger.exception(
                    "Cannot create subtitle target dir torrent_id=%s path=%s",
                    torrent_id, target_dir,
                )
                return 0

        downloaded = 0
        for sub in subs:
            sub_id = str(sub.get("id", "")).strip()
            filename = str(sub.get("filename") or f"subtitle_{sub_id}.srt").strip()
            if not sub_id:
                continue
            content = self._mteam.download_subtitle_bytes(sub_id)
            if content is None:
                continue
            out_path = os.path.join(target_dir, filename) if target_dir else filename
            try:
                with open(out_path, "wb") as fh:
                    fh.write(content)
                downloaded += 1
                logger.info(
                    "Subtitle saved torrent_id=%s subtitle_id=%s path=%s size=%s",
                    torrent_id, sub_id, out_path, len(content),
                )
            except OSError:
                logger.exception(
                    "Failed to write subtitle torrent_id=%s subtitle_id=%s path=%s",
                    torrent_id, sub_id, out_path,
                )
        return downloaded
