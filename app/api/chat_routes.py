"""HTTP routes for chat and confirmation against the workflow runner."""

from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.schemas import ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse
from app.config import get_settings
from app.domain.models import ResourceCandidate, SearchConstraints
from app.workflow.graph import LangGraphWorkflowRunner, build_workflow

# Route modules live in `app/api/`; move to repo root before joining frontend.
_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


class WorkflowRunner(Protocol):
    """Route-level protocol to support dependency injection in tests."""

    def run_chat(self, session_id: str, message: str) -> dict[str, Any]:
        ...

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict[str, Any] | None,
        selected_result_id: str | None = None,
        feedback_text: str | None = None,
    ) -> dict[str, Any]:
        ...


class AdapterSearchTool:
    """Workflow search callable backed by the M-Team adapter."""

    def __init__(self, adapter: MTeamAdapter):
        self._adapter = adapter

    def __call__(self, constraints: SearchConstraints) -> list[ResourceCandidate]:
        rows = self._adapter.search_torrents_by_keyword(
            keyword=constraints.query_text,
            page=1,
            page_size=20,
        )
        candidates: list[ResourceCandidate] = []
        for row in rows:
            title = str(row.get("title") or row.get("name") or f"M-Team {row.get('id', '')}")
            lowered_title = title.lower()
            media_type = "movie"
            if "s01" in lowered_title or "season" in lowered_title:
                media_type = "tv"
            candidates.append(
                ResourceCandidate(
                    id=str(row.get("id")),
                    title=title,
                    media_type=media_type,
                    resolution="2160p" if "2160" in lowered_title or "4k" in lowered_title else "1080p",
                    seeders=int(row.get("seeders", 0) or 0),
                    size=str(row.get("size", "unknown")),
                    source="mteam",
                )
            )
        return candidates


class AdapterDownloadExecutor:
    """Download executor that follows M-Team id -> token URL -> qB add(urls)."""

    def __init__(self, mteam_adapter: MTeamAdapter, qb_adapter: QBittorrentAdapter):
        self._mteam_adapter = mteam_adapter
        self._qb_adapter = qb_adapter

    def __call__(self, selected_result: dict[str, Any], qb_category: str) -> dict[str, Any]:
        external_id = str(selected_result["id"])
        detail = self._mteam_adapter.get_torrent_details(external_id)
        if not detail:
            return {"status": "detail_failed", "qb_hash": None}
        download_url = self._mteam_adapter.get_torrent_download_url(external_id)
        if not download_url:
            return {"status": "download_url_failed", "qb_hash": None}
        rename = self._qb_adapter.generate_mteam_torrent_name(external_id, detail, qb_category)
        add_result = self._qb_adapter.add_torrent_url(
            url=download_url,
            category=qb_category,
            rename=rename,
            tags=["mteam"],
            paused=False,
        )
        if add_result.get("ok"):
            return {"status": "submitted", "qb_hash": add_result.get("qb_hash")}
        return {
            "status": str(add_result.get("status", "submit_failed")),
            "qb_hash": add_result.get("qb_hash"),
        }


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
    graph = build_workflow(
        search_tool=AdapterSearchTool(mteam_adapter),
        download_executor=AdapterDownloadExecutor(mteam_adapter, qb_adapter),
    )
    return LangGraphWorkflowRunner(graph)


def build_router(workflow_runner: WorkflowRunner | None = None) -> APIRouter:
    runner = workflow_runner or _build_default_runner()
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        """Basic liveness probe used by local checks/tests."""
        return {"status": "ok"}

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Run search-to-confirmation workflow for a user message."""

        result = runner.run_chat(request.session_id, request.message)
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

        result = runner.run_confirm(
            request.session_id,
            action=request.action,
            confirmation_payload=request.confirmation_payload,
            selected_result_id=request.selected_result_id,
            feedback_text=request.feedback_text,
        )
        confirmation_payload = result.get("confirmation_payload")
        receipt = result.get("receipt")
        if receipt is None and isinstance(confirmation_payload, dict):
            receipt = confirmation_payload.get("receipt")
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
        if _FRONTEND_INDEX.exists():
            return _FRONTEND_INDEX.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router


router = build_router()
