"""HTTP routes for chat search and explicit download actions."""

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.agent import NasClawAgentRunner
from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.adapters.tavily import TavilyAdapter
from app.adapters.tmdb import TMDBAdapter
from app.api.qb_routes import build_qb_router
from app.api.schemas import (
    AgentApprovalDecisionRequest,
    AgentApprovalResponse,
    AgentSessionDetailResponse,
    AgentSessionListResponse,
    AgentSessionSummary,
    ChatRequest,
    ChatResponse,
    DownloadAuthorizationPolicyResponse,
    DownloadRequest,
    DownloadResponse,
    HealthServicesResponse,
    ServiceHealth,
    SessionUpdateRequest,
)
from app.config import get_settings
from app.domain.authorization import DownloadAuthorizationPolicy
from app.services.download_authorization_store import DownloadAuthorizationPolicyStore
from app.tools import QBAddTorrentTool
from hello_agents.checkpoints import JSONConversationCheckpointStore

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST_INDEX = _FRONTEND_DIR / "dist" / "index.html"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"
_AGENT_SESSION_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-sessions"
_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"


def _select_frontend_index() -> Path | None:
    if _FRONTEND_DIST_INDEX.exists():
        return _FRONTEND_DIST_INDEX
    if _FRONTEND_INDEX.exists():
        return _FRONTEND_INDEX
    return None


def _build_mteam_adapter() -> MTeamAdapter:
    settings = get_settings()
    return MTeamAdapter(
        base_url=settings.mteam_base_url,
        api_key=settings.mteam_api_key,
    )


def _build_qb_adapter() -> QBittorrentAdapter:
    settings = get_settings()
    return QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )


def _build_tmdb_adapter() -> TMDBAdapter:
    settings = get_settings()
    return TMDBAdapter(api_key=settings.tmdb_api_key)


def _build_tavily_adapter() -> TavilyAdapter:
    settings = get_settings()
    return TavilyAdapter(api_key=settings.tavily_api_key)


def _agent_checkpoint_store() -> JSONConversationCheckpointStore:
    return JSONConversationCheckpointStore(_AGENT_SESSION_DIR)


def _download_authorization_store() -> DownloadAuthorizationPolicyStore:
    return DownloadAuthorizationPolicyStore(_SETTINGS_DIR)


def build_router() -> APIRouter:
    selected_index = _select_frontend_index()
    router = APIRouter()
    router.include_router(build_qb_router())

    @router.get("/health")
    def health() -> dict[str, str]:
        """Basic liveness probe used by local checks/tests."""
        return {"status": "ok"}

    @router.get("/health/services", response_model=HealthServicesResponse)
    def health_services() -> HealthServicesResponse:
        """Check reachability of all configured external service dependencies.

        Each service is probed independently; the overall status is ``"ok"``
        when every *configured* service responds, and ``"degraded"``
        otherwise.  Unconfigured services are reported but do not degrade
        the overall status.
        """
        _LABELS: dict[str, str] = {
            "tmdb": "TMDB",
            "tavily": "Tavily",
            "mteam": "M-Team",
            "qbittorrent": "qBittorrent",
        }
        _MESSAGES: dict[str, str] = {
            "ok": "{} API 响应正常",
            "unavailable": "{} 无法连接",
            "unconfigured": "{} 未配置",
            "error": "{} 返回错误",
        }

        def _check(svc: str, adapter: object) -> tuple[str, str, float]:
            t0 = time.perf_counter()
            st = getattr(adapter, "health")()
            elapsed = (time.perf_counter() - t0) * 1000.0
            return (svc, st, round(elapsed, 1))

        results = [
            _check("tmdb", _build_tmdb_adapter()),
            _check("tavily", _build_tavily_adapter()),
            _check("mteam", _build_mteam_adapter()),
            _check("qbittorrent", _build_qb_adapter()),
        ]

        def _is_healthy(s: str) -> bool:
            return s in ("ok", "unconfigured")

        overall = (
            "ok"
            if all(_is_healthy(st) for (_, st, _) in results)
            else "degraded"
        )

        return HealthServicesResponse(
            status=overall,
            services=[
                ServiceHealth(
                    service=svc,
                    status=st,
                    latency_ms=el,
                    message=_MESSAGES.get(st, st).format(_LABELS.get(svc, svc)),
                )
                for (svc, st, el) in results
            ],
        )

    @router.get("/settings/download-authorization", response_model=DownloadAuthorizationPolicyResponse)
    def get_download_authorization_policy() -> DownloadAuthorizationPolicyResponse:
        """Return the user-configured download authorization policy."""

        policy = _download_authorization_store().load()
        return DownloadAuthorizationPolicyResponse.model_validate(policy.model_dump())

    @router.put("/settings/download-authorization", response_model=DownloadAuthorizationPolicyResponse)
    def update_download_authorization_policy(
        body: DownloadAuthorizationPolicy,
    ) -> DownloadAuthorizationPolicyResponse:
        """Persist the user-configured download authorization policy."""

        policy = _download_authorization_store().save(body)
        return DownloadAuthorizationPolicyResponse.model_validate(policy.model_dump())

    @router.post("/chat/agent", response_model=ChatResponse)
    def chat_agent(request: ChatRequest) -> ChatResponse:
        """Run the readonly experimental ToolCallingAgent with session history."""
        
        query = request.message.strip()
        if not query:
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message="请输入消息。",
                error="message is required",
            )

        runner = NasClawAgentRunner(
            checkpoint_store=_agent_checkpoint_store(),
        )

        try:
            result = runner.run(request.session_id, query)
        except Exception as exc:
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message="Agent 调用失败。",
                error=str(exc),
            )

        return ChatResponse(
            session_id=request.session_id,
            status="completed" if result.status == "success" else result.status,
            message=result.answer,
            results=result.results,
            tool_calls=result.tool_calls,
            pending_approvals=result.pending_approvals,
        )

    @router.get("/chat/agent/sessions", response_model=AgentSessionListResponse)
    def list_agent_sessions() -> AgentSessionListResponse:
        """List persisted Agent conversation checkpoints."""

        summaries = [
            AgentSessionSummary(
                session_id=summary.session_id,
                created_at=summary.created_at,
                saved_at=summary.saved_at,
                message_count=summary.message_count,
                archive_count=summary.archive_count,
                metadata=summary.metadata,
            )
            for summary in _agent_checkpoint_store().list()
        ]
        return AgentSessionListResponse(sessions=summaries)

    @router.get("/chat/agent/sessions/{session_id}", response_model=AgentSessionDetailResponse)
    def get_agent_session(session_id: str) -> AgentSessionDetailResponse:
        """Load one persisted Agent conversation checkpoint."""

        checkpoint = _agent_checkpoint_store().load(session_id)
        if checkpoint is None:
            raise HTTPException(status_code=404, detail="Agent session not found")

        return AgentSessionDetailResponse(
            session_id=checkpoint.session_id,
            created_at=checkpoint.created_at,
            saved_at=checkpoint.saved_at,
            messages=checkpoint.history,
            archives=checkpoint.archives,
            metadata=checkpoint.metadata,
        )

    @router.delete("/chat/agent/sessions/{session_id}", status_code=204)
    def delete_agent_session(session_id: str):
        """Delete one persisted Agent conversation checkpoint."""

        store = _agent_checkpoint_store()
        if not store.delete(session_id):
            raise HTTPException(status_code=404, detail="Agent session not found")
        NasClawAgentRunner.cleanup_session_trace(session_id)

    @router.patch("/chat/agent/sessions/{session_id}", response_model=AgentSessionDetailResponse)
    def update_agent_session(session_id: str, body: SessionUpdateRequest) -> AgentSessionDetailResponse:
        """Rename an Agent session by updating metadata.title."""

        store = _agent_checkpoint_store()
        checkpoint = store.load(session_id)
        if checkpoint is None:
            raise HTTPException(status_code=404, detail="Agent session not found")

        if body.title is not None:
            checkpoint.metadata["title"] = body.title.strip() or None
        store.save(checkpoint)

        return AgentSessionDetailResponse(
            session_id=checkpoint.session_id,
            created_at=checkpoint.created_at,
            saved_at=checkpoint.saved_at,
            messages=checkpoint.history,
            archives=checkpoint.archives,
            metadata=checkpoint.metadata,
        )

    @router.post("/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve", response_model=AgentApprovalResponse)
    def approve_agent_approval(
        session_id: str,
        approval_id: str,
        body: AgentApprovalDecisionRequest | None = None,
    ) -> AgentApprovalResponse:
        """Approve one pending Agent tool call and execute it deterministically."""

        runner = NasClawAgentRunner(checkpoint_store=_agent_checkpoint_store())
        try:
            result = runner.approve(
                session_id,
                approval_id,
                decision=(body.decision if body else "approve_once"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return AgentApprovalResponse(
            session_id=result.session_id,
            approval_id=result.approval_id,
            status=result.status,
            message=result.message,
            receipt=result.receipt,
            pending_approvals=result.pending_approvals,
            error=result.error,
        )

    @router.post("/chat/agent/sessions/{session_id}/approvals/{approval_id}/deny", response_model=AgentApprovalResponse)
    def deny_agent_approval(session_id: str, approval_id: str) -> AgentApprovalResponse:
        """Reject one pending Agent tool call without executing it."""

        runner = NasClawAgentRunner(checkpoint_store=_agent_checkpoint_store())
        try:
            result = runner.deny(session_id, approval_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return AgentApprovalResponse(
            session_id=result.session_id,
            approval_id=result.approval_id,
            status=result.status,
            message=result.message,
            receipt=result.receipt,
            pending_approvals=result.pending_approvals,
            error=result.error,
        )

    @router.post("/download", response_model=DownloadResponse)
    def download(request: DownloadRequest) -> DownloadResponse:
        """Explicitly add one M-Team torrent to qBittorrent in paused mode."""

        download_tool = QBAddTorrentTool(_build_mteam_adapter(), _build_qb_adapter())
        tool_params = {
            "torrent_id": request.torrent_id,
            "qb_category": request.qb_category,
        }
        if request.save_path:
            tool_params["save_path"] = request.save_path
        response = download_tool.run(tool_params)
        if response.status.value == "error":
            return DownloadResponse(status="error", error=response.text)
        return DownloadResponse(
            status="completed",
            receipt=response.data.get("receipt"),
        )

    @router.get("/favicon.png", response_class=FileResponse)
    def favicon() -> FileResponse:
        """Serve the favicon from the frontend dist directory."""
        favicon_path = _FRONTEND_DIST_INDEX.parent / "favicon.png"
        if favicon_path.exists():
            return FileResponse(favicon_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Favicon not found")

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the chat page when present, fallback to a tiny placeholder."""
        if selected_index is not None:
            return selected_index.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router
