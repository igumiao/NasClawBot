"""Application-level approval records for gated Agent tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from hello_agents.tools.response import ToolResponse


APPROVAL_TTL = timedelta(minutes=30)


class ApprovalStatus(str, Enum):
    """Lifecycle states for one deterministic approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    FAILED = "failed"
    EXPIRED = "expired"


class ApprovalRiskLevel(str, Enum):
    """Risk classes used by approval policy and UI display."""

    READONLY = "readonly"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"


@dataclass
class ApprovalRisk:
    """Small display/policy summary for a gated tool call."""

    level: ApprovalRiskLevel
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ApprovalRisk":
        if not data:
            return cls(level=ApprovalRiskLevel.SIDE_EFFECT, summary="Execute a side-effect tool")
        level = str(data.get("level") or ApprovalRiskLevel.SIDE_EFFECT.value)
        return cls(
            level=ApprovalRiskLevel(level) if level in ApprovalRiskLevel._value2member_map_ else ApprovalRiskLevel.SIDE_EFFECT,
            summary=str(data.get("summary") or "Execute a side-effect tool"),
        )


@dataclass
class ApprovalRecord:
    """Durable approval request/decision record stored in checkpoint metadata."""

    approval_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: ApprovalStatus
    reason: str
    created_at: str
    expires_at: str
    decided_at: str | None = None
    decision: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    expired_at: str | None = None
    authorization: dict[str, Any] | None = None
    risk: ApprovalRisk = field(default_factory=lambda: risk_for_tool(""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "decision": self.decision,
            "result": self.result,
            "error": self.error,
            "expired_at": self.expired_at,
            "authorization": self.authorization,
            "risk": self.risk.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], session_id: str | None = None) -> "ApprovalRecord":
        created_at = str(data.get("created_at") or datetime.now(timezone.utc).isoformat())
        expires_at = str(data.get("expires_at") or (_parse_datetime(created_at) + APPROVAL_TTL).isoformat())
        tool_name = str(data.get("tool_name") or "")
        return cls(
            approval_id=str(data["approval_id"]),
            session_id=str(data.get("session_id") or session_id or ""),
            tool_call_id=str(data.get("tool_call_id") or ""),
            tool_name=tool_name,
            arguments=dict(data.get("arguments") or {}),
            status=ApprovalStatus(str(data.get("status") or ApprovalStatus.PENDING.value)),
            reason=str(data.get("reason") or ""),
            created_at=created_at,
            expires_at=expires_at,
            decided_at=data.get("decided_at"),
            decision=dict(data["decision"]) if data.get("decision") else None,
            result=dict(data["result"]) if data.get("result") else None,
            error=dict(data["error"]) if data.get("error") else None,
            expired_at=data.get("expired_at"),
            authorization=dict(data["authorization"]) if data.get("authorization") else None,
            risk=ApprovalRisk.from_dict(data.get("risk") or risk_for_tool(tool_name).to_dict()),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) > _parse_datetime(self.expires_at)


def create_pending_approval(
    raw: dict[str, Any],
    session_id: str,
    now: datetime | None = None,
) -> ApprovalRecord:
    """Normalize a loop-level pending approval into an app-level record."""

    created_at = str(raw.get("created_at") or (now or datetime.now(timezone.utc)).isoformat())
    expires_at = str(raw.get("expires_at") or (_parse_datetime(created_at) + APPROVAL_TTL).isoformat())
    tool_name = str(raw.get("tool_name") or "")
    return ApprovalRecord(
        approval_id=str(raw["approval_id"]),
        session_id=session_id,
        tool_call_id=str(raw.get("tool_call_id") or ""),
        tool_name=tool_name,
        arguments=dict(raw.get("arguments") or {}),
        status=ApprovalStatus.PENDING,
        reason=str(raw.get("reason") or "Tool call requires user approval."),
        created_at=created_at,
        expires_at=expires_at,
        authorization=dict(raw["authorization"]) if raw.get("authorization") else None,
        risk=ApprovalRisk.from_dict(raw.get("risk") or risk_for_tool(tool_name).to_dict()),
    )


def mark_approved(
    record: ApprovalRecord,
    response: ToolResponse,
    now: datetime | None = None,
) -> ApprovalRecord:
    record.status = ApprovalStatus.APPROVED
    record.decided_at = (now or datetime.now(timezone.utc)).isoformat()
    record.decision = {"action": "approve"}
    record.result = response.to_dict()
    record.error = None
    return record


def mark_failed(
    record: ApprovalRecord,
    response: ToolResponse,
    now: datetime | None = None,
) -> ApprovalRecord:
    record.status = ApprovalStatus.FAILED
    record.decided_at = (now or datetime.now(timezone.utc)).isoformat()
    record.decision = {"action": "approve"}
    record.result = None
    record.error = response.error_info or {"message": response.text}
    return record


def mark_denied(
    record: ApprovalRecord,
    now: datetime | None = None,
) -> ApprovalRecord:
    record.status = ApprovalStatus.DENIED
    record.decided_at = (now or datetime.now(timezone.utc)).isoformat()
    record.decision = {"action": "deny"}
    return record


def mark_expired(
    record: ApprovalRecord,
    now: datetime | None = None,
) -> ApprovalRecord:
    record.status = ApprovalStatus.EXPIRED
    record.expired_at = (now or datetime.now(timezone.utc)).isoformat()
    record.decided_at = None
    record.decision = None
    return record


def risk_for_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> ApprovalRisk:
    if tool_name in {"qb_add_torrent", "qb_add_torrents"}:
        if tool_name == "qb_add_torrents":
            return ApprovalRisk(
                level=ApprovalRiskLevel.SIDE_EFFECT,
                summary="Submit multiple torrents to qBittorrent in paused state",
            )
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Submit torrent to qBittorrent in paused state",
        )
    if tool_name == "qb_control_torrent":
        action = (arguments or {}).get("action", "")
        if action == "delete":
            return ApprovalRisk(
                level=ApprovalRiskLevel.DESTRUCTIVE,
                summary="Delete torrent and optionally its files from qBittorrent",
            )
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary=f"Control torrent: {action or 'unknown'}",
        )
    if tool_name == "qb_set_global_speed":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Modify global transfer speed limits",
        )
    if tool_name == "qb_set_torrent_speed":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Modify per-torrent speed limits",
        )
    if tool_name == "schedule_download_check":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Create a scheduled future download completion check",
        )
    if tool_name == "task_cancel":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Cancel a pending background task",
        )
    if tool_name == "task_reschedule":
        return ApprovalRisk(
            level=ApprovalRiskLevel.SIDE_EFFECT,
            summary="Reschedule a pending download check task",
        )
    return ApprovalRisk(
        level=ApprovalRiskLevel.SIDE_EFFECT,
        summary="Execute a side-effect tool",
    )


def _parse_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
