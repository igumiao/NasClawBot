"""Request/response payload schemas for the API layer."""

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.domain.authorization import DownloadAuthorizationPolicy
from app.domain.models import ResourceCandidate


class ContextUsage(BaseModel):
    """Last model request prompt-context utilization snapshot."""

    context_window: int = 64000
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    @computed_field
    @property
    def usage_pct(self) -> float:
        if self.context_window <= 0:
            return 0.0
        return round(self.prompt_tokens / self.context_window * 100, 1)

    @computed_field
    @property
    def cache_hit_rate(self) -> float | None:
        total = self.cache_hit_tokens + self.cache_miss_tokens
        if total <= 0:
            return None
        return round(self.cache_hit_tokens / total * 100, 1)


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
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    context_usage: ContextUsage | None = None


class AgentSessionSummary(BaseModel):
    """Compact conversation checkpoint row for session lists."""

    session_id: str
    created_at: str
    saved_at: str
    message_count: int
    archive_count: int = 0
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
    archives: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompactResponse(BaseModel):
    """Result of a manual context compaction."""

    session_id: str
    compressed: bool
    summary: str | None = None
    archive: dict[str, Any] | None = None
    message_count_before: int = 0
    message_count_after: int = 0
    estimated_tokens_before: int = 0


class AgentApprovalResponse(BaseModel):
    """Result of a deterministic Agent approval decision."""

    session_id: str
    approval_id: str
    status: str
    message: str
    receipt: dict[str, Any] | None = None
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    context_usage: ContextUsage | None = None


class AgentApprovalDecisionRequest(BaseModel):
    """Optional payload for approving a pending Agent approval."""

    decision: Literal["approve_once", "approve_and_grant_session"] = "approve_once"


class SessionUpdateRequest(BaseModel):
    """Fields accepted for a PATCH /chat/agent/sessions/{session_id} update."""

    title: str | None = None


class DownloadRequest(BaseModel):
    """Explicit user action to add a torrent to qBittorrent."""

    torrent_id: str
    qb_category: str = "mteam"
    save_path: str | None = None


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


class FreeToppedTorrentSchema(BaseModel):
    """One free topped torrent row for the UI."""

    id: str
    name: str
    size_bytes: int
    size_display: str
    seeders: int
    leechers: int
    discount: str | None = None
    topping_level: int = 0
    free_until: str | None = None
    category: str = ""
    imdb: str | None = None
    douban: str | None = None


class FreeToppedResponse(BaseModel):
    """Free topped torrents split by topping level."""

    level2: list[FreeToppedTorrentSchema] = Field(default_factory=list)
    level1: list[FreeToppedTorrentSchema] = Field(default_factory=list)
    total_count: int = 0


class ServiceHealth(BaseModel):
    """Health status for a single external service dependency."""

    service: str  # "tmdb" | "tavily" | "mteam" | "qbittorrent"
    status: str  # "ok" | "unavailable" | "unconfigured" | "error"
    latency_ms: float  # response time in milliseconds
    message: str  # human-readable detail


class HealthServicesResponse(BaseModel):
    """Aggregated health check for all external service dependencies."""

    status: str  # "ok" when all configured services are healthy, "degraded" otherwise
    services: list[ServiceHealth] = Field(default_factory=list)


class DownloadAuthorizationPolicyResponse(DownloadAuthorizationPolicy):
    """Settings response for download authorization policy."""


class MemoryInboxEntry(BaseModel):
    index: int
    timestamp: str
    text: str


class MemoryInboxResponse(BaseModel):
    entries: list[MemoryInboxEntry] = Field(default_factory=list)
    entry_count: int


class CurationSuggestion(BaseModel):
    inbox_index: int | None = None
    preview: str = ""
    action: Literal["keep", "discard", "modify", "delete"]
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    edited_text: str | None = None
    existing_text: str | None = None
    new_text: str | None = None
    reason: str | None = None


class CurationSections(BaseModel):
    user_profile: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)


class CurationResponse(BaseModel):
    suggestions: list[CurationSuggestion] = Field(default_factory=list)
    inbox_entry_count: int
    sections: CurationSections = Field(default_factory=CurationSections)


class CuratorApplyDecision(BaseModel):
    action: Literal["keep", "discard", "modify", "delete"]
    inbox_index: int | None = None
    destination: Literal["user_profile", "knowledge"] | None = None
    section: str | None = None
    text: str | None = None
    existing_text: str | None = None
    new_text: str | None = None


class CuratorApplyRequest(BaseModel):
    inbox_entry_count: int
    decisions: list[CuratorApplyDecision] = Field(default_factory=list)


class CuratorApplyResponse(BaseModel):
    applied: int
    discarded: int
    modified: int
    deleted: int
    remaining: int
