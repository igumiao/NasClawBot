"""Domain models for download submission and post-download follow-up.

DownloadSubmissionRequest is an internal transfer model (not exposed to the
LLM as a tool input).  ResolvedFollowUp captures how the after-download
mode was derived.  DownloadSubmissionResult and BatchDownloadSubmissionResult
provide receipt-style responses for the /download endpoint and its batch
equivalent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.runtime_tasks import utc_now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FOLLOW_UP_AUTO_ORGANIZE = "auto_organize"
"""Run the organisation pipeline once the download finishes."""

FOLLOW_UP_NOTIFY_ONLY = "notify_only"
"""Publish a completion event for the UI without further processing."""

FOLLOW_UP_NONE = "none"
"""No post-download follow-up action."""

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FollowUpMode = Literal["auto_organize", "notify_only", "none"]
"""The possible after-download follow-up modes."""

FollowUpSource = Literal["request", "settings", "fallback"]
"""Where the resolved follow-up mode came from."""

SubmissionStatus = Literal["accepted", "duplicate", "failed"]
"""Outcome of a single download submission to qBittorrent."""

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DownloadSubmissionRequest(BaseModel):
    """Internal transfer model for download submission.

    NOT registered as a tool input visible to the LLM.  This model is used
    internally by the /download endpoint and any batch equivalent to carry
    the caller's intent to the submission layer.
    """

    torrent_id: str
    """The M-Team or external torrent identifier to submit to qBittorrent."""

    qb_category: str = ""
    """qBittorrent category for the torrent (e.g. ``"mteam"``)."""

    save_path: str | None = None
    """Optional custom save path override for qBittorrent."""

    tag: str | None = None
    """Optional media-type tag (e.g. 电影, 电视剧, 动漫)."""

    after_download: Literal["auto_organize", "notify_only"] | None = None
    """Optional user preference for what happens after the download completes.

    * ``"auto_organize"`` -- spawn the organisation pipeline.
    * ``"notify_only"`` -- just publish a task event for the UI.
    * ``None`` -- resolve from Settings-level default or system fallback.
    """


class ResolvedFollowUp(BaseModel):
    """Captures how the after-download follow-up mode was resolved.

    Three-way precedence: request-level value wins, then the Settings-level
    default, then the hard-coded system fallback (``"none"``).
    """

    mode: FollowUpMode
    """The resolved follow-up mode after applying precedence."""

    source: FollowUpSource
    """Where the resolved mode came from.

    * ``"request"`` -- explicitly provided in the submission request.
    * ``"settings"`` -- resolved from the stored configuration.
    * ``"fallback"`` -- no explicit or configured value; system default.
    """

    reason: str | None = None
    """Optional human-readable justification for the resolution."""

    authorization_snapshot: dict[str, Any] | None = None
    """Optional snapshot of relevant authorization or grant state at resolution time."""


class DownloadSubmissionResult(BaseModel):
    """Receipt for one submitted download."""

    receipt_id: str
    """Unique receipt identifier (UUID hex)."""

    torrent_id: str
    """The torrent identifier that was submitted."""

    status: SubmissionStatus
    """Submission outcome.

    * ``"accepted"`` -- queued successfully.
    * ``"duplicate"`` -- already present in qBittorrent; not re-submitted.
    * ``"failed"`` -- submission rejected by qBittorrent or the adapter.
    """

    watch_task_id: str
    """Runtime task ID for the watch task spawned to track this download.

    Empty string when the submission failed or no watch task was created.
    """

    resolved_follow_up: ResolvedFollowUp
    """How the after-download follow-up mode was resolved for this item."""

    submission_receipt: dict[str, Any] | None = None
    """Full receipt dict from the underlying DownloadSubmission service.

    Contains resource_title, external_id, qb_category, qb_hash, status,
    subtitle_count, and (on error) error. Populated only when status is
    ``"accepted"``.
    """

    submitted_at: str = Field(default_factory=utc_now_iso)
    """ISO-8601 timestamp of the submission."""

    error: str | None = None
    """Error message when status is ``"failed"``."""


class BatchDownloadSubmissionResult(BaseModel):
    """Aggregated response for a batch download submission."""

    items: list[DownloadSubmissionResult]
    """One result per submitted torrent in submission order."""

    summary: dict[str, int] = Field(default_factory=dict)
    """Summary counts keyed by status (e.g. ``{"accepted": 3, "duplicate": 1}``)."""
