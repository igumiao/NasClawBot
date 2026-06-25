"""Runtime state reducer for one NasClawBot Agent session."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.agent.approvals import ApprovalRecord, ApprovalStatus
from app.domain.runtime_tasks import app_now_iso
from hello_agents.loop import ToolCallingLoopResult


RUNTIME_STATE_VERSION = 1


def update_runtime_state_after_turn(
    previous_state: dict[str, Any] | None,
    *,
    user_message: str,
    loop_result: ToolCallingLoopResult | None,
    pending_approvals: list[dict[str, Any]],
    turn_count: int,
) -> dict[str, Any]:
    """Return a compact state snapshot after a normal Agent turn."""

    state = _base_state(previous_state, turn_count=turn_count)
    state["current_query"] = {"text": user_message}

    if loop_result:
        state["last_status"] = loop_result.status
        for observation in loop_result.tool_observations:
            if observation.tool_name == "mteam_search" and observation.response.status.value == "success":
                state["candidate_set"] = _candidate_set_from_mteam_observation(observation)

    if pending_approvals:
        state["pending_action"] = _pending_action_from_approval(pending_approvals[0])
    else:
        state.pop("pending_action", None)

    state["updated_at"] = _now()
    return state


def update_runtime_state_after_approval(
    previous_state: dict[str, Any] | None,
    *,
    approval: ApprovalRecord,
    last_status: str,
    pending_approvals: list[dict[str, Any]] | None = None,
    turn_count: int,
) -> dict[str, Any]:
    """Return a compact state snapshot after an approval decision."""

    state = _base_state(previous_state, turn_count=turn_count)
    state["last_status"] = last_status
    if pending_approvals:
        state["pending_action"] = _pending_action_from_approval(pending_approvals[0])
    else:
        state.pop("pending_action", None)
    state["last_decision"] = {
        "type": _decision_type(approval),
        "approval_id": approval.approval_id,
        "tool_name": approval.tool_name,
        "decided_at": approval.decided_at,
        "status": approval.status.value,
    }
    state["updated_at"] = _now()
    return state


def _base_state(previous_state: dict[str, Any] | None, *, turn_count: int) -> dict[str, Any]:
    state = deepcopy(previous_state) if isinstance(previous_state, dict) else {}
    state["version"] = RUNTIME_STATE_VERSION
    state["turn_count"] = turn_count
    return state


def _candidate_set_from_mteam_observation(observation: Any) -> dict[str, Any]:
    candidates = observation.response.data.get("candidates", [])
    items: list[dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        torrent_id = str(row.get("id") or "")
        items.append(
            {
                "torrent_id": torrent_id,
                "title": str(row.get("title") or ""),
                "media_type": row.get("media_type"),
                "year": row.get("year"),
                "resolution": row.get("resolution"),
                "seeders": row.get("seeders", 0),
                "leechers": row.get("leechers", 0),
                "discount": row.get("discount"),
                "imdb": row.get("imdb"),
                "douban": row.get("douban"),
                "size": row.get("size"),
                "size_bytes": row.get("size_bytes"),
                "source": row.get("source"),
            }
        )
    return {
        "source": "mteam_search",
        "created_at": _now(),
        "applied_query": deepcopy(observation.response.data.get("applied_query") or {}),
        "items": items,
    }


def _pending_action_from_approval(approval: dict[str, Any]) -> dict[str, Any]:
    return {
        "approval_id": approval.get("approval_id"),
        "tool_name": approval.get("tool_name"),
        "arguments": deepcopy(approval.get("arguments") or {}),
    }


def _decision_type(approval: ApprovalRecord) -> str:
    if approval.status == ApprovalStatus.APPROVED:
        return "approval_approved"
    if approval.status == ApprovalStatus.DENIED:
        return "approval_denied"
    if approval.status == ApprovalStatus.FAILED:
        return "approval_failed"
    if approval.status == ApprovalStatus.EXPIRED:
        return "approval_expired"
    return "approval_pending"


def _now() -> str:
    return app_now_iso()
