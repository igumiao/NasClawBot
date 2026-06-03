"""Request/response payload schemas for the API layer."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models import ResourceCandidate


class ChatRequest(BaseModel):
    """Incoming user message for a specific session."""

    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Search-oriented chat response consumed by the browser shell."""

    session_id: str
    status: str
    message: str = ""
    results: list[ResourceCandidate] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class AgentSessionSummary(BaseModel):
    """Compact conversation checkpoint row for session lists."""

    session_id: str
    created_at: str
    saved_at: str
    message_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSessionListResponse(BaseModel):
    """Known Agent conversation sessions."""

    sessions: list[AgentSessionSummary] = Field(default_factory=list)


class AgentSessionDetailResponse(BaseModel):
    """Full persisted conversation checkpoint for UI restoration."""

    session_id: str
    created_at: str
    saved_at: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DownloadRequest(BaseModel):
    """Explicit user action to add a torrent to qBittorrent."""

    torrent_id: str
    qb_category: str = "mteam"


class DownloadResponse(BaseModel):
    """Response for explicit download submission."""

    status: str
    receipt: dict[str, Any] | None = None
    error: str | None = None


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
