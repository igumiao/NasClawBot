"""HelloAgents-backed workflow runner implementing the WorkflowRunner protocol.

See docs/plan/helloagents-migration-plan.md Phase 1 for the full design.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hello_agents.runtime.workflow import SequentialWorkflow
from hello_agents.tools.permissions import ToolPermission

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.agent_runtime.keyword import KeywordExtractor
from app.agent_runtime.state import WorkflowStatus
from app.agent_runtime.tools import MTeamSearchTool, QBAddTorrentTool
from app.config import get_settings
from app.domain.models import ConfirmationCandidate, ConfirmationPayload, ResourceCandidate
from app.storage.runtime_session_store import RuntimeSessionStore

# Internal WorkflowStatus -> external API status contract (ADR 002, line 52).
_STATUS_TO_API: dict[str, str] = {
    WorkflowStatus.AWAITING_APPROVAL.value: "awaiting_confirmation",
    WorkflowStatus.COMPLETED.value: "completed",
    WorkflowStatus.CANCELED.value: "canceled",
    WorkflowStatus.ERROR.value: "error",
}


def _api_status(internal_status: str) -> str:
    return _STATUS_TO_API.get(internal_status, internal_status)


def _make_envelope(session_id: str, user_message: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": WorkflowStatus.IN_PROGRESS.value,
        "domain": {
            "user_message": user_message,
            "keyword": "",
            "search_results": [],
            "confirmation_payload": None,
            "receipt": None,
        },
        "pending_approval": None,
        "error": None,
        "tool_trace": [],
    }


# ---------------------------------------------------------------------------
# Workflow steps
# ---------------------------------------------------------------------------


def _keyword_step(keyword_extractor: KeywordExtractor) -> Any:
    def step(envelope: dict[str, Any]) -> dict[str, Any]:
        domain: dict[str, Any] = envelope["domain"]
        result = keyword_extractor.invoke(domain["user_message"])
        domain["keyword"] = result["keyword"]
        return envelope

    return step


def _search_step(search_tool: MTeamSearchTool) -> Any:
    def step(envelope: dict[str, Any]) -> dict[str, Any]:
        domain: dict[str, Any] = envelope["domain"]
        try:
            response = search_tool.run_with_timing({"keyword": domain["keyword"]})
        except Exception as exc:
            envelope["status"] = WorkflowStatus.ERROR.value
            envelope["error"] = f"Search failed: {exc}"
            return envelope
        if response.status.value == "error":
            envelope["status"] = WorkflowStatus.ERROR.value
            envelope["error"] = response.text
            return envelope
        domain["search_results"] = response.data.get("candidates", [])
        return envelope

    return step


def _build_confirmation_step() -> Any:
    def step(envelope: dict[str, Any]) -> dict[str, Any]:
        domain: dict[str, Any] = envelope["domain"]
        candidates: list[dict[str, Any]] = domain.get("search_results", [])

        if not candidates:
            confirmation = ConfirmationPayload(
                summary="I couldn't find matching candidates. You can refine your request.",
                recommended_result_id=None,
                results=[],
            )
            domain["confirmation_payload"] = confirmation.model_dump()
            now = datetime.now(timezone.utc).isoformat()
            envelope["pending_approval"] = {
                "approval_type": "download_confirmation",
                "tool_name": "qb_add_torrent",
                "permission": ToolPermission.SIDE_EFFECT.value,
                "confirmation_payload": confirmation.model_dump(),
                "resolved": False,
                "resolved_at": None,
                "created_at": now,
            }
            envelope["status"] = WorkflowStatus.AWAITING_APPROVAL.value
            return envelope

        top = candidates[:3]
        recommended_id = str(top[0]["id"]) if top else None
        confirmation = ConfirmationPayload(
            summary=f"Found {len(candidates)} results. Top match: {top[0]['title']}" if top else "No results.",
            recommended_result_id=recommended_id,
            results=[
                ConfirmationCandidate(
                    id=str(c["id"]),
                    title=str(c.get("title", "")),
                    seeders=int(c.get("seeders", 0)),
                    resolution=str(c.get("resolution", "")),
                    size=str(c.get("size", "")),
                )
                for c in top
            ],
        )
        domain["confirmation_payload"] = confirmation.model_dump()

        now = datetime.now(timezone.utc).isoformat()
        envelope["pending_approval"] = {
            "approval_type": "download_confirmation",
            "tool_name": "qb_add_torrent",
            "permission": ToolPermission.SIDE_EFFECT.value,
            "confirmation_payload": confirmation.model_dump(),
            "resolved": False,
            "resolved_at": None,
            "created_at": now,
        }
        envelope["status"] = WorkflowStatus.AWAITING_APPROVAL.value
        return envelope

    return step


def _execute_download_step(download_tool: QBAddTorrentTool) -> Any:
    def step(envelope: dict[str, Any]) -> dict[str, Any]:
        domain: dict[str, Any] = envelope["domain"]
        confirmation = domain.get("confirmation_payload")

        selected_id = None
        if isinstance(confirmation, ConfirmationPayload):
            selected_id = confirmation.selected_result_id or confirmation.recommended_result_id
        elif isinstance(confirmation, dict):
            selected_id = confirmation.get("selected_result_id") or confirmation.get("recommended_result_id")

        if not selected_id:
            envelope["status"] = WorkflowStatus.ERROR.value
            envelope["error"] = "No torrent selected for download."
            return envelope

        response = download_tool.run(
            {"torrent_id": str(selected_id), "qb_category": "mteam"}
        )
        if response.status.value == "error":
            envelope["status"] = WorkflowStatus.ERROR.value
            envelope["error"] = response.text
            return envelope

        domain["receipt"] = response.data.get("receipt")
        approval = envelope.get("pending_approval") or {}
        approval["resolved"] = True
        approval["resolved_at"] = datetime.now(timezone.utc).isoformat()
        envelope["pending_approval"] = approval
        envelope["status"] = WorkflowStatus.COMPLETED.value
        return envelope

    return step


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class HelloAgentWorkflowRunner:
    """Application adapter that translates /chat and /confirm calls into
    runtime workflow invocations, matching the WorkflowRunner protocol."""

    def __init__(
        self,
        mteam_adapter: MTeamAdapter | None = None,
        qb_adapter: QBittorrentAdapter | None = None,
    ) -> None:
        settings = get_settings()
        self._mteam = mteam_adapter or MTeamAdapter(
            base_url=settings.mteam_base_url,
            api_key=settings.mteam_api_key,
        )
        self._qb = qb_adapter or QBittorrentAdapter(
            base_url=settings.qb_base_url,
            username=settings.qb_username,
            password=settings.qb_password,
        )
        self._keyword_extractor = KeywordExtractor()
        self._session_store = RuntimeSessionStore(settings.database_path)

    # -- WorkflowRunner protocol -------------------------------------------

    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        search_tool = MTeamSearchTool(self._mteam)
        download_tool = QBAddTorrentTool(self._mteam, self._qb)

        workflow = SequentialWorkflow(
            steps=[
                _keyword_step(self._keyword_extractor),
                _search_step(search_tool),
                _build_confirmation_step(),
            ]
        )
        envelope = _make_envelope(session_id, message)
        envelope = workflow.run(envelope)
        self._session_store.save(session_id, envelope)

        return {
            "session_id": session_id,
            "status": _api_status(envelope.get("status", "")),
            "confirmation_payload": envelope.get("domain", {}).get("confirmation_payload"),
            "receipt": envelope.get("domain", {}).get("receipt"),
            "error": envelope.get("error"),
        }

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict[str, Any] | ConfirmationPayload | None,
        selected_result_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()

        if normalized_action == "cancel":
            envelope = self._session_store.load(session_id)
            if envelope:
                envelope["status"] = WorkflowStatus.CANCELED.value
                self._session_store.save(session_id, envelope)
            return {
                "session_id": session_id,
                "status": "canceled",
                "messages": ["Request canceled by user."],
            }

        if normalized_action != "approve":
            return {
                "session_id": session_id,
                "status": "error",
                "error": f"Unsupported action: {action}",
            }

        if not confirmation_payload:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "confirmation_payload is required for approve.",
            }

        envelope = self._session_store.load(session_id)
        if envelope is None:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "No pending approval found for this session.",
            }
        if envelope.get("status") != WorkflowStatus.AWAITING_APPROVAL.value:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "Session is not awaiting approval.",
            }
        approval = envelope.get("pending_approval") or {}
        if approval.get("resolved") is True:
            return {
                "session_id": session_id,
                "status": "error",
                "error": "Approval has already been resolved.",
            }
        if approval.get("approval_type") != "download_confirmation":
            return {
                "session_id": session_id,
                "status": "error",
                "error": f"Unknown approval type: {approval.get('approval_type')}.",
            }

        if isinstance(confirmation_payload, ConfirmationPayload):
            payload = confirmation_payload
        else:
            payload = ConfirmationPayload.model_validate(confirmation_payload)
        if selected_result_id:
            payload = payload.model_copy(update={"selected_result_id": selected_result_id})

        # Validate selected id against the persisted approval payload.
        persisted_cf = approval.get("confirmation_payload") or {}
        persisted_candidates = {
            str(c.get("id")): c
            for c in persisted_cf.get("results", [])
        }
        resolved_id = payload.selected_result_id or payload.recommended_result_id
        if not isinstance(resolved_id, str) or not resolved_id.strip():
            return {
                "session_id": session_id,
                "status": "error",
                "error": "No torrent selected for download.",
            }
        if resolved_id not in persisted_candidates:
            return {
                "session_id": session_id,
                "status": "error",
                "error": f"Selected id {resolved_id} does not match any candidate in the pending approval.",
            }

        envelope.setdefault("domain", {})["confirmation_payload"] = payload.model_dump()
        envelope["pending_approval"]["resolved"] = True

        download_tool = QBAddTorrentTool(self._mteam, self._qb)
        workflow = SequentialWorkflow(steps=[_execute_download_step(download_tool)])
        envelope["status"] = WorkflowStatus.IN_PROGRESS.value
        envelope = workflow.run(envelope)
        self._session_store.save(session_id, envelope)

        domain = envelope.get("domain", {})
        confirmation = domain.get("confirmation_payload")
        receipt = domain.get("receipt")
        if receipt is None and isinstance(confirmation, ConfirmationPayload):
            receipt = confirmation.receipt

        messages = envelope.get("messages") or []
        return {
            "session_id": session_id,
            "status": _api_status(envelope.get("status", "")),
            "confirmation_payload": confirmation,
            "receipt": receipt,
            "error": envelope.get("error"),
            "messages": [str(msg) for msg in messages],
        }
