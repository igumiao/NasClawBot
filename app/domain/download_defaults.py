"""Download defaults — user-configurable download preferences."""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_SAVE_PATH = "/vol1/1000/NasClawBot下载区域"


class DownloadDefaults(BaseModel):
    """User-configurable download defaults.

    Currently covers the default save_path used when no explicit
    path is provided to qb_add_torrent / qb_add_torrents.
    """

    default_save_path: str = Field(
        default=DEFAULT_SAVE_PATH,
        description="Default download directory for qBittorrent",
    )


def default_download_defaults() -> DownloadDefaults:
    return DownloadDefaults()
