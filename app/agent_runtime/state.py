"""P0 workflow state types for the HelloAgents runtime.

See docs/plan/helloagents-migration-plan.md, Phase 1 Tactical Decisions.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict

from app.domain.models import ConfirmationPayload, ResourceCandidate


class WorkflowStatus(Enum):
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    CANCELED = "canceled"
    ERROR = "error"


class ApprovalState(TypedDict):
    approval_type: str
    tool_name: str
    permission: str  # SIDE_EFFECT | DESTRUCTIVE
    confirmation_payload: dict[str, Any]
    resolved: bool
    resolved_at: str | None
    created_at: str


class SearchDownloadState(TypedDict, total=False):
    user_message: str
    keyword: str
    search_results: list[ResourceCandidate]
    confirmation_payload: ConfirmationPayload | None
    receipt: dict[str, Any] | None


class WorkflowEnvelope(TypedDict):
    session_id: str
    status: str  # WorkflowStatus value
    domain: SearchDownloadState | None
    pending_approval: ApprovalState | None
    error: str | None
    tool_trace: list[dict[str, Any]]
