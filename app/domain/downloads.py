"""Download submission and download-monitor domain contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.runtime_tasks import utc_now_iso


MonitorMode = Literal["once", "until_complete"]
MonitorCompletionAction = Literal["notify", "organize"]
DownloadCompletionAction = Literal["none", "notify", "organize"]
SubmissionStatus = Literal["accepted", "duplicate", "failed"]


class DownloadSubmissionRequest(BaseModel):
    """Internal request used by the deterministic qB submission service."""

    torrent_id: str
    qb_category: str = ""
    save_path: str | None = None
    tag: str | None = None


class DownloadSubmissionResult(BaseModel):
    """Safe receipt for one submitted download."""

    receipt_id: str
    torrent_id: str
    status: SubmissionStatus
    watch_task_id: str | None = None
    submission_receipt: dict[str, Any] | None = None
    submitted_at: str = Field(default_factory=utc_now_iso)
    error: str | None = None


class BatchDownloadSubmissionResult(BaseModel):
    """Aggregated receipt for a batch download submission."""

    items: list[DownloadSubmissionResult]
    summary: dict[str, int] = Field(default_factory=dict)


class DownloadMonitorSpec(BaseModel):
    """Canonical behavior persisted in every newly-created monitor payload."""

    mode: MonitorMode
    on_completed: MonitorCompletionAction


class DownloadMonitorRequest(BaseModel):
    """Agent-facing request to monitor an existing qB torrent."""

    torrent_hash: str
    start_at: str | None = None
    mode: MonitorMode
    on_completed: MonitorCompletionAction


class DownloadMonitorUpdate(BaseModel):
    """Atomic mutation of a pending download monitor."""

    task_id: str
    start_at: str | None = None
    mode: MonitorMode | None = None
    on_completed: MonitorCompletionAction | None = None

    @model_validator(mode="after")
    def _require_mutation(self) -> "DownloadMonitorUpdate":
        mutation_fields = {"start_at", "mode", "on_completed"}
        supplied = mutation_fields.intersection(self.model_fields_set)
        if not supplied:
            raise ValueError("at least one monitor mutation field is required")
        if "start_at" in supplied and self.start_at is None:
            raise ValueError("start_at cannot be null when supplied")
        return self


class DownloadMonitorReceipt(BaseModel):
    """Safe canonical monitor receipt returned to tools and routes."""

    task_id: str
    torrent_hash: str
    torrent_name: str
    start_at: str | None
    mode: MonitorMode
    on_completed: MonitorCompletionAction
    status: str


class ParsedDownloadMonitor(BaseModel):
    """Effective monitor behavior after canonical/legacy payload parsing.

    ``on_completed='none'`` exists only for legacy payloads. New payloads
    must always contain a canonical :class:`DownloadMonitorSpec`.
    """

    mode: MonitorMode
    on_completed: Literal["notify", "organize", "none"]
    is_legacy: bool = False


def parse_download_monitor(payload: dict[str, Any]) -> ParsedDownloadMonitor:
    """Parse canonical monitor payloads and all deployed legacy variants."""

    raw_monitor = payload.get("monitor")
    if raw_monitor is not None:
        spec = DownloadMonitorSpec.model_validate(raw_monitor)
        return ParsedDownloadMonitor(
            mode=spec.mode,
            on_completed=spec.on_completed,
            is_legacy=False,
        )

    raw_policy = payload.get("check_policy")
    legacy_mode = "until_complete"
    if isinstance(raw_policy, dict):
        raw_mode = raw_policy.get("mode")
        if raw_mode == "once":
            legacy_mode = "once"
        elif raw_mode not in (None, "continuous"):
            raise ValueError(f"invalid legacy check_policy.mode: {raw_mode!r}")

    raw_follow_up = payload.get("resolved_follow_up")
    if isinstance(raw_follow_up, dict):
        raw_action = raw_follow_up.get("mode", "none")
    elif isinstance(raw_follow_up, str):
        raw_action = raw_follow_up
    else:
        raw_action = "none"

    action_map = {
        "notify_only": "notify",
        "auto_organize": "organize",
        "none": "none",
    }
    if raw_action not in action_map:
        raise ValueError(f"invalid legacy resolved_follow_up mode: {raw_action!r}")
    return ParsedDownloadMonitor(
        mode=legacy_mode,
        on_completed=action_map[raw_action],
        is_legacy=True,
    )


def build_download_monitor_payload(
    *,
    torrent_hash: str,
    torrent_name: str,
    save_path: str,
    monitor: DownloadMonitorSpec,
    authorization_snapshot: dict[str, Any] | None = None,
    created_via: Literal["conversation_agent"] = "conversation_agent",
) -> dict[str, Any]:
    """Build the only payload shape new download-monitor code may persist."""

    payload: dict[str, Any] = {
        "qb_hash": torrent_hash,
        "torrent_name": torrent_name,
        "save_path": save_path,
        "monitor": monitor.model_dump(),
        "created_via": created_via,
    }
    if monitor.on_completed == "organize":
        if authorization_snapshot is None:
            raise ValueError("organize monitor requires an authorization snapshot")
        payload["authorization_snapshot"] = authorization_snapshot
    elif authorization_snapshot is not None:
        raise ValueError("notify monitor must not carry an authorization snapshot")
    return payload


def normalize_to_utc(value: str) -> str:
    """Normalize an aware ISO-8601 timestamp to canonical UTC."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must include a timezone offset: {value!r}")
    return parsed.astimezone(timezone.utc).isoformat()


def is_future_time(value_utc: str, *, now: datetime | None = None) -> bool:
    """Return whether a canonical aware timestamp is strictly in the future."""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value_utc) > current.astimezone(timezone.utc)
