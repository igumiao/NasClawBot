"""HTTP routes for chat and confirmation against the workflow runner."""

from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.agent_runtime.runner import HelloAgentWorkflowRunner
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    ConfirmResponse,
)
from app.api.qb_routes import build_qb_router
from app.config import get_settings
from app.domain.models import ConfirmationPayload

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST_INDEX = _FRONTEND_DIR / "dist" / "index.html"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"


def _select_frontend_index() -> Path | None:
    if _FRONTEND_DIST_INDEX.exists():
        return _FRONTEND_DIST_INDEX
    if _FRONTEND_INDEX.exists():
        return _FRONTEND_INDEX
    return None


class WorkflowRunner(Protocol):
    """Route-level protocol to support dependency injection in tests."""

    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        ...

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: ConfirmationPayload | None,
        selected_result_id: str | None = None,
    ) -> dict[str, Any]:
        ...


def _build_default_runner() -> WorkflowRunner:
    settings = get_settings()
    mteam_adapter = MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )
    qb_adapter = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )
    return HelloAgentWorkflowRunner(
        mteam_adapter=mteam_adapter,
        qb_adapter=qb_adapter,
    )

def build_router(workflow_runner: WorkflowRunner | None = None) -> APIRouter:
    runner = workflow_runner
    selected_index = _select_frontend_index()
    router = APIRouter()
    router.include_router(build_qb_router())

    def get_runner() -> WorkflowRunner:
        nonlocal runner
        if runner is None:
            runner = _build_default_runner()
        return runner

    @router.get("/health")
    def health() -> dict[str, str]:
        """Basic liveness probe used by local checks/tests."""
        return {"status": "ok"}

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Run search-to-confirmation workflow for a user message."""

        result = get_runner().run_chat(request.session_id, request.message)
        return ChatResponse(
            session_id=request.session_id,
            status=result.get("status", "error"),
            confirmation_payload=result.get("confirmation_payload"),
            receipt=result.get("receipt"),
            error=result.get("error"),
        )

    @router.post("/confirm", response_model=ConfirmResponse)
    def confirm(request: ConfirmRequest) -> ConfirmResponse:
        """Handle user action at confirmation stage."""

        if request.action.strip().lower() == "reject_and_refine":
            return ConfirmResponse(
                session_id=request.session_id,
                status="error",
                error="Phase 2A does not support reject_and_refine on /confirm.",
            )

        result = get_runner().run_confirm(
            request.session_id,
            action=request.action,
            confirmation_payload=request.confirmation_payload,
            selected_result_id=request.selected_result_id,
        )
        confirmation_payload = result.get("confirmation_payload")
        receipt = result.get("receipt")
        if receipt is None and isinstance(confirmation_payload, ConfirmationPayload):
            receipt = confirmation_payload.receipt
        messages = result.get("messages") or []
        return ConfirmResponse(
            session_id=request.session_id,
            status=result.get("status", "error"),
            confirmation_payload=confirmation_payload,
            receipt=receipt,
            error=result.get("error"),
            messages=[str(msg) for msg in messages],
        )

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the chat page when present, fallback to a tiny placeholder."""
        if selected_index is not None:
            return selected_index.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router
