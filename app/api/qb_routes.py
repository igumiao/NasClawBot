"""HTTP routes for qBittorrent task listing, detail, and control."""

from fastapi import APIRouter, HTTPException

from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.schemas import (
    QBTorrentActionRequest,
    QBTorrentActionResponse,
    QBTorrentDetailResponse,
    QBTorrentListResponse,
)
from app.config import get_settings


def _build_qb_adapter() -> QBittorrentAdapter:
    settings = get_settings()
    return QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )


def build_qb_router() -> APIRouter:
    """Build qBittorrent management routes as a separate router slice."""

    router = APIRouter()

    @router.get("/qb/torrents", response_model=QBTorrentListResponse)
    def list_qb_torrents(
        category: str | None = None,
        tag: str | None = None,
        limit: int | None = None,
        status_filter: str | None = None,
        sort: str | None = None,
        reverse: bool | None = None,
    ) -> QBTorrentListResponse:
        """Expose qB torrent listing for polling and management surfaces."""
        qb_adapter = _build_qb_adapter()
        items = qb_adapter.list_torrents(
            category=category,
            tag=tag,
            limit=limit,
            status_filter=status_filter,
            sort=sort,
            reverse=reverse,
        )
        return QBTorrentListResponse(items=items)

    @router.get("/qb/torrents/{torrent_hash}", response_model=QBTorrentDetailResponse)
    def get_qb_torrent(torrent_hash: str) -> QBTorrentDetailResponse:
        """Expose one qB torrent detail row with progress fields."""
        qb_adapter = _build_qb_adapter()
        item = qb_adapter.get_torrent(torrent_hash)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Torrent not found: {torrent_hash}")
        return QBTorrentDetailResponse(**item)

    @router.post("/qb/torrents/{torrent_hash}/actions", response_model=QBTorrentActionResponse)
    def control_qb_torrent(
        torrent_hash: str,
        request: QBTorrentActionRequest,
    ) -> QBTorrentActionResponse:
        """Dispatch a supported control action for one qB torrent."""
        qb_adapter = _build_qb_adapter()
        result = qb_adapter.control_torrent(
            torrent_hash,
            action=request.action,
            delete_files=request.delete_files,
        )
        return QBTorrentActionResponse(**result)

    return router
