"""HTTP routes for chat and confirmation against the current workflow."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api.schemas import ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse
from app.domain.models import ResourceCandidate, SearchConstraints
from app.workflow.graph import build_workflow

router = APIRouter()

# Route modules live in `app/api/`; move to repo root before joining frontend.
_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


class DemoSearchTool:
    """Deterministic search tool used until real adapters are wired in Task 9."""

    def __call__(self, constraints: SearchConstraints) -> list[ResourceCandidate]:
        query = constraints.query_text.lower()
        if "dune" in query:
            return [
                ResourceCandidate(
                    id="2",
                    title="Dune Part Two 2024 1080p",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=120,
                    size="12 GB",
                    source="mteam",
                ),
                ResourceCandidate(
                    id="1",
                    title="Dune Part Two 2024 1080p",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=20,
                    size="10 GB",
                    source="mteam",
                ),
            ]

        return [
            ResourceCandidate(
                id="10",
                title="Sample Movie 2024 1080p",
                media_type="movie",
                year=2024,
                resolution="1080p",
                seeders=40,
                size="8 GB",
                source="mteam",
            ),
            ResourceCandidate(
                id="11",
                title="Sample Series S01 Pack",
                media_type="tv",
                year=2024,
                resolution="1080p",
                seeders=65,
                size="20 GB",
                source="mteam",
            ),
        ]


_WORKFLOW = build_workflow(search_tool=DemoSearchTool())


@router.get("/health")
def health() -> dict[str, str]:
    """Basic liveness probe used by local checks/tests."""
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Run search-to-confirmation workflow for a user message."""

    result = _WORKFLOW.invoke(
        {"session_id": request.session_id, "user_message": request.message}
    )
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

    action = request.action.strip().lower()
    if action == "cancel":
        return ConfirmResponse(
            session_id=request.session_id,
            status="canceled",
            messages=["Request canceled by user."],
        )

    if action == "reject_and_refine":
        refinement_message = (request.feedback_text or "").strip()
        if not refinement_message:
            return ConfirmResponse(
                session_id=request.session_id,
                status="error",
                error="feedback_text is required for reject_and_refine.",
            )
        refined = _WORKFLOW.invoke(
            {"session_id": request.session_id, "user_message": refinement_message}
        )
        return ConfirmResponse(
            session_id=request.session_id,
            status=refined.get("status", "error"),
            confirmation_payload=refined.get("confirmation_payload"),
            receipt=refined.get("receipt"),
            error=refined.get("error"),
            messages=["Refined search results are ready for confirmation."],
        )

    if action != "approve":
        return ConfirmResponse(
            session_id=request.session_id,
            status="error",
            error=f"Unsupported action: {request.action}",
        )

    if not request.confirmation_payload:
        return ConfirmResponse(
            session_id=request.session_id,
            status="error",
            error="confirmation_payload is required for approve.",
        )

    payload: dict[str, Any] = dict(request.confirmation_payload)
    if request.selected_result_id:
        payload["selected_result_id"] = request.selected_result_id
    executed = _WORKFLOW.invoke(
        {"session_id": request.session_id, "confirmation_payload": payload}
    )
    final_payload = executed.get("confirmation_payload", {})
    return ConfirmResponse(
        session_id=request.session_id,
        status=executed.get("status", "error"),
        confirmation_payload=final_payload,
        receipt=final_payload.get("receipt"),
        error=executed.get("error"),
        messages=["Download execution placeholder completed."],
    )


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the chat page when present, fallback to a tiny placeholder."""
    if _FRONTEND_INDEX.exists():
        return _FRONTEND_INDEX.read_text(encoding="utf-8")
    return "<h1>fnOS Media Agent</h1>"
