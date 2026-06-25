"""DownloadSubmission -- M-Team detail/token -> qB add (paused) -> community subtitles.

Extracted from QBAddTorrentTool into a reusable service so both the Agent
tool and the explicit /download endpoint (and any future batch path) share
the same submission logic.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.downloads import DownloadSubmissionRequest
from app.services.receipt_service import build_receipt

logger = logging.getLogger(__name__)


class DownloadSubmission:
    """Reusable download submission service.

    Orchestrates the full chain:
      M-Team torrent detail -> genDlToken -> qBittorrent add (paused)
      -> optional community subtitle auto-download
    """

    def __init__(
        self,
        mteam_adapter: MTeamAdapter,
        qb_adapter: QBittorrentAdapter,
        default_save_path: str | None = None,
        default_tags: list[str] | None = None,
        paused: bool = False,
    ) -> None:
        self._mteam = mteam_adapter
        self._qb = qb_adapter
        self._default_save_path = (default_save_path or "").strip() or None
        self._default_tags = list(default_tags) if default_tags else ["mteam"]
        self._paused = paused

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_save_path(self, request: DownloadSubmissionRequest) -> str:
        """Return the effective qB save path without performing submission."""
        return (request.save_path or "").strip() or self._default_save_path or ""

    def submit(
        self,
        request: DownloadSubmissionRequest,
        correlation_tag: str | None = None,
    ) -> dict:
        """Execute the full download chain.

        Args:
            request: Submission intent carrying torrent_id, category,
                save_path, user-facing tag, etc.
            correlation_tag: Optional programmatic identifier that is added
                as a qB tag ``nasclaw-task-{correlation_tag}`` for tracking
                (never exposed in the Agent tool schema).

        Returns:
            A receipt dict with at minimum:

            - **resource_title** (str | None) -- display title of the torrent.
            - **external_id** (str) -- the M-Team torrent id.
            - **qb_category** (str) -- the category used for the qB add.
            - **qb_hash** (str | None) -- qB torrent hash on success.
            - **status** (str) -- ``"submitted_paused"`` on success,
              ``"error"`` on failure.
            - **subtitle_count** (int) -- number of subtitle files saved.
            - **error** (str | None) -- human-readable error message when
              status is ``"error"``.
        """
        torrent_id = request.torrent_id.strip()
        if not torrent_id:
            return _error_receipt(
                torrent_id=torrent_id,
                qb_category=request.qb_category or "",
                error="torrent_id is required.",
            )

        # 1 -- Fetch M-Team torrent details
        detail = self._mteam.get_torrent_details(torrent_id)
        if not detail:
            return _error_receipt(
                torrent_id=torrent_id,
                qb_category=request.qb_category or "",
                error=f"Failed to get torrent details for id={torrent_id}.",
            )

        # 2 -- Generate one-time download token URL
        download_url = self._mteam.get_torrent_download_url(torrent_id)
        if not download_url:
            return _error_receipt(
                torrent_id=torrent_id,
                qb_category=request.qb_category or "",
                error=f"Failed to generate download URL for id={torrent_id}.",
            )

        # 3 -- Verify the token URL resolves to a .torrent payload
        if not self._mteam.is_download_url_torrent(download_url):
            return _error_receipt(
                torrent_id=torrent_id,
                qb_category=request.qb_category or "",
                error=f"Download URL is not a torrent for id={torrent_id}.",
            )

        # 4 -- Build tag list
        #     default_tags   => base labels (e.g. "mteam")
        #     request.tag    => optional user-facing media-type label
        #     correlation_tag => programmatic tracking tag (not in Agent schema)
        tags = list(self._default_tags)
        user_tag = (request.tag or "").strip()
        if user_tag:
            tags.append(user_tag)

        add_tags: list[str] | None = None
        if correlation_tag:
            add_tags = [f"nasclaw-task-{correlation_tag}"]

        # 5 -- Generate stable qB torrent name anchored on M-Team id
        rename = self._qb.generate_mteam_torrent_name(
            torrent_id,
            detail,
            request.qb_category or "",
        )

        # 6 -- Assemble qB add payload
        add_kwargs: dict[str, Any] = {
            "url": download_url,
            "category": request.qb_category or "",
            "rename": rename,
            "tags": tags,
            "paused": self._paused,
        }
        save_path = self.resolve_save_path(request)
        if save_path:
            add_kwargs["save_path"] = save_path

        add_result = self._qb.add_torrent_url(**add_kwargs, add_tags=add_tags)

        # 7 -- Handle success / error
        if add_result.get("ok"):
            title = str(detail.get("title") or torrent_id)
            qb_hash = add_result.get("qb_hash")
            status = str(add_result.get("status", "submitted_paused"))

            # 8 -- Auto-download community subtitles when available
            subtitle_count = 0
            if detail.get("hasChineseSubtitle"):
                subtitle_count = self._download_subtitles(
                    torrent_id=torrent_id,
                    save_path=save_path,
                )

            receipt = build_receipt(
                resource_title=title,
                external_id=torrent_id,
                qb_category=request.qb_category or "",
                qb_hash=str(qb_hash) if qb_hash else None,
                status=status,
            )
            receipt["subtitle_count"] = subtitle_count
            return receipt

        # 9 -- Error path
        error_code = add_result.get("error_code", "UNKNOWN")
        error_message = add_result.get("error_message", str(add_result))
        retryable = add_result.get("retryable", False)
        retry_hint = " (可重试)" if retryable else ""
        return _error_receipt(
            torrent_id=torrent_id,
            qb_category=request.qb_category or "",
            error=f"[{error_code}] {error_message}{retry_hint}",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_subtitles(
        self,
        *,
        torrent_id: str,
        save_path: str | None,
    ) -> int:
        """Download community subtitles for a torrent to *save_path*.

        Non-blocking: all failures are logged but never raised.
        Returns the number of subtitle files successfully written.
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
                    torrent_id,
                    target_dir,
                )
                return 0

        downloaded = 0
        for sub in subs:
            sub_id = str(sub.get("id", "")).strip()
            filename = (
                str(sub.get("filename") or f"subtitle_{sub_id}.srt").strip()
            )
            if not sub_id:
                continue
            content = self._mteam.download_subtitle_bytes(sub_id)
            if content is None:
                continue
            out_path = (
                os.path.join(target_dir, filename) if target_dir else filename
            )
            try:
                with open(out_path, "wb") as fh:
                    fh.write(content)
                downloaded += 1
                logger.info(
                    "Subtitle saved torrent_id=%s subtitle_id=%s path=%s size=%s",
                    torrent_id,
                    sub_id,
                    out_path,
                    len(content),
                )
            except OSError:
                logger.exception(
                    "Failed to write subtitle torrent_id=%s subtitle_id=%s path=%s",
                    torrent_id,
                    sub_id,
                    out_path,
                )
        return downloaded


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _error_receipt(
    torrent_id: str,
    qb_category: str,
    error: str,
) -> dict:
    """Return a minimal error receipt consistent with the success shape."""
    return {
        "resource_title": None,
        "external_id": torrent_id,
        "qb_category": qb_category,
        "qb_hash": None,
        "status": "error",
        "error": error,
        "subtitle_count": 0,
    }
