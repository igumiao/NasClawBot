"""Domain models shared by tools, adapters, and API routes.

Keeping these types centralized makes contracts easier to understand during
early development.
"""

from typing import Literal

from pydantic import BaseModel

MediaType = Literal["movie", "tv", "anime", "unknown"]


class ResourceCandidate(BaseModel):
    """One normalized search result entry from an external source."""

    id: str
    title: str
    media_type: str
    year: int | None = None
    resolution: str | None = None
    seeders: int = 0
    leechers: int = 0
    discount: str | None = None
    imdb: str | None = None
    douban: str | None = None
    size: str
    size_bytes: int | None = None
    source: str
    small_description: str | None = None
    subtitle_flags: list[str] = []
