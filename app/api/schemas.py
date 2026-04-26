"""Request/response payload schemas for the API layer."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models import ConfirmationPayload


class ChatRequest(BaseModel):
    """Incoming user message for a specific session."""

    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    """Confirmation-stage action payload for current workflow actions."""

    session_id: str
    action: str
    selected_result_id: str | None = None
    confirmation_payload: ConfirmationPayload | None = None


class ChatResponse(BaseModel):
    """Minimal chat response shape consumed by the browser shell."""

    session_id: str
    status: str
    confirmation_payload: ConfirmationPayload | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None


class ConfirmResponse(BaseModel):
    """Response shape for confirmation actions."""

    session_id: str
    status: str
    confirmation_payload: ConfirmationPayload | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None
    messages: list[str] = Field(default_factory=list)


class QBTorrentSummary(BaseModel):
    """Minimal qB torrent fields for list views and progress polling."""

    hash: str
    name: str
    category: str
    tags: list[str] = Field(default_factory=list)
    state: str
    progress: float
    download_speed: int
    upload_speed: int
    eta: int
    save_path: str
    size: int
    total_size: int


class QBTorrentDetailResponse(QBTorrentSummary):
    """Single torrent detail payload enriched with qB properties."""

    comment: str = ""
    total_uploaded: int = 0
    share_ratio: float = 0.0
    creation_date: int = 0


class QBTorrentListResponse(BaseModel):
    """List response wrapper for qB torrent items."""

    items: list[QBTorrentSummary] = Field(default_factory=list)


class QBTorrentActionRequest(BaseModel):
    """Route payload for controlling a qB torrent."""

    action: Literal["pause", "resume", "recheck", "reannounce", "delete"]
    delete_files: bool = False


class QBTorrentActionResponse(BaseModel):
    """Structured result of a qB torrent control action."""

    ok: bool
    status: str
    qb_hash: str | None = None
