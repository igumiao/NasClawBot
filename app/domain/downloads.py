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

from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# Scheduled download check (Conversation-created future tasks)
# ---------------------------------------------------------------------------


class DownloadCheckPolicy(BaseModel):
    """Policy controlling how a download-watch task checks for completion.

    This is embedded in the task payload so the handler can dispatch
    between continuous polling (legacy) and one-shot future checks
    created by the Conversation Agent.
    """

    mode: Literal["continuous", "once"] = "continuous"
    """Check mode.

    * ``"continuous"`` — poll repeatedly until download completes
      (legacy behaviour, active for all normal qB downloads).
    * ``"once"`` — execute one business check at ``run_after`` and
      then terminate regardless of progress.
    """

    on_incomplete: Literal["reschedule", "notify"] = "reschedule"
    """Behaviour when a once-mode check finds download still incomplete.

    * ``"reschedule"`` — re-arm for another future check (not used in v1).
    * ``"notify"`` — publish a ``download_check_incomplete`` event and
      mark the task ``SUCCEEDED``.
    """


class ScheduleDownloadCheckRequest(BaseModel):
    """Agent-facing input for the ``schedule_download_check`` tool.

    The Agent resolves natural-language time expressions (e.g. "后天晚上八点")
    into an absolute ISO-8601 timestamp with timezone offset before calling
    the tool.
    """

    torrent_hash: str
    """qBittorrent info hash identifying the torrent to check."""

    run_at: str
    """ISO-8601 datetime with timezone offset when the check should execute.

    Example: ``"2026-06-25T20:00:00+08:00"``.  Naive datetimes are rejected.
    """

    follow_up: Literal["notify_only", "auto_organize"] | None = None
    """Optional override for what happens when the download is complete.

    * ``None`` — resolve from Settings default (falls back to ``notify_only``).
    * ``"notify_only"`` — publish a completion event.
    * ``"auto_organize"`` — spawn the organisation pipeline.
    """


class ScheduledDownloadCheckReceipt(BaseModel):
    """Receipt returned to the Agent after a scheduled check is created."""

    task_id: str
    """Runtime task ID for the created future check."""

    torrent_hash: str
    """qBittorrent info hash being checked."""

    torrent_name: str
    """Current torrent name from qB at creation time."""

    run_at: str
    """Canonical UTC ISO-8601 timestamp when the check will execute."""

    check_mode: Literal["once"] = "once"
    """Always ``"once"`` for Conversation-created scheduled checks."""

    resolved_follow_up: Literal["notify_only", "auto_organize"]
    """The resolved follow-up mode after applying precedence."""

    if_incomplete: Literal["notify"] = "notify"
    """Always ``"notify"`` — one-shot checks never reschedule on incomplete."""


# ---------------------------------------------------------------------------
# UTC time normalisation helper
# ---------------------------------------------------------------------------


def normalize_to_utc(run_at: str) -> str:
    """Parse *run_at* as an aware ISO-8601 datetime and return canonical UTC.

    Returns the datetime as an ISO-8601 string with ``+00:00`` offset.

    Raises:
        ValueError: When *run_at* is a naive datetime (missing timezone
            offset) or cannot be parsed.
    """
    dt = datetime.fromisoformat(run_at)
    if dt.tzinfo is None:
        raise ValueError(
            f"run_at must include a timezone offset, got naive: {run_at!r}"
        )
    return dt.astimezone(timezone.utc).isoformat()


def is_future_time(run_at_utc: str, *, now: datetime | None = None) -> bool:
    """Return ``True`` when *run_at_utc* is strictly in the future.

    Args:
        run_at_utc: Canonical UTC ISO-8601 string (output of
            :func:`normalize_to_utc`).
        now: Current time for comparison.  Defaults to ``datetime.now(timezone.utc)``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    return datetime.fromisoformat(run_at_utc) > now
