"""HTTP routes for chat search and explicit download actions."""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
    CompactResponse,
    ContextUsage,
    DownloadAuthorizationPolicyResponse,
    DownloadRequest,
    DownloadResponse,
    HealthServicesResponse,
    ServiceHealth,
    SessionUsage,
    SessionUpdateRequest,
    TMDBNetworkSettingsResponse,
)
from app.config import get_settings
from app.domain.authorization import DownloadAuthorizationPolicy
from app.domain.downloads import DownloadSubmissionRequest
from app.services.download_authorization_store import DownloadAuthorizationPolicyStore
from app.services.download_automation import DownloadAutomation
from app.services.download_submission import DownloadSubmission
from app.services.organization_policy_store import OrganizationAuthorizationPolicyStore
from app.services.tmdb_network_store import TMDBNetworkSettingsStore
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.storage.db import ensure_schema
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
    tmdb_network = _tmdb_network_store().load()
    return TMDBAdapter(
        api_key=settings.tmdb_api_key,
        proxy_url=tmdb_network.active_proxy_url,
    )


def _build_tavily_adapter() -> TavilyAdapter:
    settings = get_settings()
    return TavilyAdapter(api_key=settings.tavily_api_key)


def _agent_checkpoint_store() -> JSONConversationCheckpointStore:
    return JSONConversationCheckpointStore(_AGENT_SESSION_DIR)


def _download_authorization_store() -> DownloadAuthorizationPolicyStore:
    return DownloadAuthorizationPolicyStore(_SETTINGS_DIR)


def _tmdb_network_store() -> TMDBNetworkSettingsStore:
    return TMDBNetworkSettingsStore(_SETTINGS_DIR)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_hex() -> str:
    return uuid.uuid4().hex


# Module-level database paths.
_DB_PATH = Path(__file__).resolve().parents[2] / "nas_media_agent.db"


def _get_task_db_path() -> Path:
    """Return the runtime task database path from settings.

    Not a module-level constant so that tests can override
    ``TASK_DB_PATH`` via env / ``FakeSettings`` and isolate
    from the production database.
    """
    return Path(get_settings().task_db_path)


def _build_download_automation_factory(
    default_tags: list[str] | None = None,
) -> Callable[[], DownloadAutomation]:
    """Return a factory that creates DownloadAutomation on demand.

    Each call to the factory builds a fresh coordinator wired with a new
    MTeam/QB adapter pair, the shared SQLite task store, and the
    organization authorization store. The service is stateless, so a new
    instance per invocation is safe.
    """

    def factory() -> DownloadAutomation:
        settings = get_settings()
        mteam = _build_mteam_adapter()
        qb = _build_qb_adapter()
        submission = DownloadSubmission(
            mteam, qb,
            default_save_path=settings.download_default_save_path,
            default_tags=default_tags,
        )
        # Ensure the task schema exists before the store is used.
        task_db_path = _get_task_db_path()
        ensure_schema(task_db_path)
        store = RuntimeTaskStore(
            db_path=task_db_path,
            clock=_utc_now,
            id_factory=_uuid_hex,
        )
        scheduler = TaskScheduler(
            store=store,
            clock=_utc_now,
            id_factory=_uuid_hex,
        )
        policy_store = OrganizationAuthorizationPolicyStore(_SETTINGS_DIR)
        allowed_dirs: list[str] = []
        if bool(getattr(settings, "mcp_fs_enabled", True)):
            allowed_dirs = [
                item.strip()
                for item in str(getattr(settings, "mcp_fs_allowed_dirs", "")).split(",")
                if item.strip()
            ]
            if not allowed_dirs:
                allowed_dirs = [str(Path(__file__).resolve().parents[2] / "test-media")]
        return DownloadAutomation(
            submission=submission,
            qb_adapter=qb,
            scheduler=scheduler,
            policy_store=policy_store,
            clock=_utc_now,
            id_factory=_uuid_hex,
            mcp_allowed_dirs=allowed_dirs,
        )

    return factory


def _build_task_management_service_factory() -> Callable[[], Any]:
    """Build a factory that creates a fresh TaskManagementService on each call.

    The service uses the same TASK_DB_PATH as the TaskRuntime so task
    management operations (create scheduled check, list, cancel, reschedule)
    work against the same SQLite database.

    Each call creates short-lived RuntimeTaskStore/TaskScheduler adapters;
    connections are opened and closed per method, so there is no connection
    leak.
    """
    from app.runtime.scheduler import TaskScheduler
    from app.runtime.store import RuntimeTaskStore
    from app.services.task_management import TaskManagementService

    task_db_path = _get_task_db_path()
    settings_dir = Path(__file__).resolve().parents[2] / "memory" / "settings"

    def factory() -> TaskManagementService:
        store = RuntimeTaskStore(
            db_path=task_db_path,
            clock=_utc_now,
            id_factory=_uuid_hex,
        )
        scheduler = TaskScheduler(
            store=store,
            clock=_utc_now,
            id_factory=_uuid_hex,
        )
        return TaskManagementService(scheduler=scheduler)

    return factory


def _build_agent_runner() -> NasClawAgentRunner:
    """Build a NasClawAgentRunner wired with a DownloadAutomation factory,
    the shared RuntimeTaskStore, and the TaskManagementService factory.

    The Agent tools use the default ``["mteam"]`` tag set, matching the
    pre-existing behavior.  The RuntimeTaskStore enables background task
    event injection into the Agent's system prompt.
    """
    task_db_path = _get_task_db_path()
    ensure_schema(task_db_path)
    runtime_store = RuntimeTaskStore(
        db_path=task_db_path,
        clock=_utc_now,
        id_factory=_uuid_hex,
    )
    return NasClawAgentRunner(
        checkpoint_store=_agent_checkpoint_store(),
        download_automation_factory=_build_download_automation_factory(
            default_tags=["mteam"],
        ),
        runtime_task_store=runtime_store,
        task_management_service_factory=_build_task_management_service_factory(),
    )


def build_router() -> APIRouter:
    selected_index = _select_frontend_index()
    router = APIRouter()
    router.include_router(build_qb_router())

    @router.get("/health")
    def health() -> dict[str, str]:
        """Basic liveness probe used by local checks/tests."""
        return {"status": "ok"}

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

    def _check_service(svc: str, adapter: object) -> ServiceHealth:
        t0 = time.perf_counter()
        st = getattr(adapter, "health")()
        elapsed = (time.perf_counter() - t0) * 1000.0
        return ServiceHealth(
            service=svc,
            status=st,
            latency_ms=round(elapsed, 1),
            message=_MESSAGES.get(st, st).format(_LABELS.get(svc, svc)),
        )

    @router.get("/health/services", response_model=HealthServicesResponse)
    def health_services() -> HealthServicesResponse:
        """Check reachability of all configured external service dependencies.

        Each service is probed independently; the overall status is ``"ok"``
        when every *configured* service responds, and ``"degraded"``
        otherwise.  Unconfigured services are reported but do not degrade
        the overall status.
        """
        results = [
            _check_service("tmdb", _build_tmdb_adapter()),
            _check_service("tavily", _build_tavily_adapter()),
            _check_service("mteam", _build_mteam_adapter()),
            _check_service("qbittorrent", _build_qb_adapter()),
        ]

        def _is_healthy(s: str) -> bool:
            return s in ("ok", "unconfigured")

        overall = (
            "ok"
            if all(_is_healthy(result.status) for result in results)
            else "degraded"
        )

        return HealthServicesResponse(
            status=overall,
            services=results,
        )

    @router.get("/health/services/tmdb", response_model=ServiceHealth)
    def health_tmdb_service() -> ServiceHealth:
        """Check only TMDB reachability and credentials."""

        return _check_service("tmdb", _build_tmdb_adapter())

    @router.get("/health/services/tavily", response_model=ServiceHealth)
    def health_tavily_service() -> ServiceHealth:
        """Check only Tavily reachability and credentials."""

        return _check_service("tavily", _build_tavily_adapter())

    @router.get("/health/services/mteam", response_model=ServiceHealth)
    def health_mteam_service() -> ServiceHealth:
        """Check only M-Team reachability and credentials."""

        return _check_service("mteam", _build_mteam_adapter())

    @router.get("/health/services/qbittorrent", response_model=ServiceHealth)
    def health_qbittorrent_service() -> ServiceHealth:
        """Check only qBittorrent reachability and credentials."""

        return _check_service("qbittorrent", _build_qb_adapter())

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

    @router.get("/settings/tmdb-network", response_model=TMDBNetworkSettingsResponse)
    def get_tmdb_network_settings() -> TMDBNetworkSettingsResponse:
        """Return TMDB-specific network override settings."""

        settings = _tmdb_network_store().load()
        return TMDBNetworkSettingsResponse.model_validate(settings.model_dump())

    @router.put("/settings/tmdb-network", response_model=TMDBNetworkSettingsResponse)
    def update_tmdb_network_settings(
        body: TMDBNetworkSettingsResponse,
    ) -> TMDBNetworkSettingsResponse:
        """Persist TMDB-specific network override settings."""

        settings = _tmdb_network_store().save(body)
        return TMDBNetworkSettingsResponse.model_validate(settings.model_dump())

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

        runner = _build_agent_runner()

        try:
            result = runner.run(request.session_id, query)
        except Exception as exc:
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message="Agent 调用失败。",
                error=str(exc),
            )

        context_usage = None
        if result.context_usage:
            context_usage = ContextUsage(**result.context_usage)
        session_usage = None
        if result.session_usage:
            session_usage = SessionUsage(**result.session_usage)

        return ChatResponse(
            session_id=request.session_id,
            status="completed" if result.status == "success" else result.status,
            message=result.answer,
            results=result.results,
            tool_calls=result.tool_calls,
            pending_approvals=result.pending_approvals,
            context_usage=context_usage,
            session_usage=session_usage,
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

    @router.post("/chat/agent/sessions/{session_id}/compact", response_model=CompactResponse)
    def compact_agent_session(session_id: str) -> CompactResponse:
        """Manually compact (compress) context for a session.

        Forces preflight compression regardless of the current token count so you can
        inspect the LLM-generated summary and archived messages.
        """
        import traceback as _tb
        try:
            runner = _build_agent_runner()
            return runner.compact_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            _tb.print_exc()
            raise HTTPException(status_code=500, detail=_tb.format_exc()) from exc

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

        runner = _build_agent_runner()
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
            context_usage=ContextUsage(**result.context_usage) if result.context_usage else None,
            session_usage=SessionUsage(**result.session_usage) if result.session_usage else None,
        )

    @router.post("/chat/agent/sessions/{session_id}/approvals/{approval_id}/deny", response_model=AgentApprovalResponse)
    def deny_agent_approval(session_id: str, approval_id: str) -> AgentApprovalResponse:
        """Reject one pending Agent tool call without executing it."""

        runner = _build_agent_runner()
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
            context_usage=ContextUsage(**result.context_usage) if result.context_usage else None,
            session_usage=SessionUsage(**result.session_usage) if result.session_usage else None,
        )

    @router.post("/download", response_model=DownloadResponse)
    def download(request: DownloadRequest) -> DownloadResponse:
        """Explicitly add one M-Team torrent to qBittorrent in paused mode."""

        automation = _build_download_automation_factory(default_tags=["刷流"])()
        req = DownloadSubmissionRequest(
            torrent_id=request.torrent_id,
            qb_category=request.qb_category,
            save_path=request.save_path or None,
            tag=None,
        )
        result = automation.submit_downloads(
            [req], completion_action="none", source_session_id=None
        ).items[0]

        if result.status == "accepted":
            return DownloadResponse(
                status="completed",
                receipt=result.submission_receipt,
                watch_task_id=result.watch_task_id,
            )

        return DownloadResponse(
            status="error",
            error=result.error or "Unknown submission error",
            watch_task_id=None,
        )

    @router.get("/favicon.png", response_class=FileResponse)
    def favicon() -> FileResponse:
        """Serve the favicon from the frontend dist directory."""
        favicon_path = _FRONTEND_DIST_INDEX.parent / "favicon.png"
        if favicon_path.exists():
            return FileResponse(favicon_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Favicon not found")

    @router.get("/brand-logo.png", response_class=FileResponse)
    def brand_logo() -> FileResponse:
        """Serve the brand logo from the frontend dist directory."""
        logo_path = _FRONTEND_DIST_INDEX.parent / "brand-logo.png"
        if logo_path.exists():
            return FileResponse(logo_path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Brand logo not found")

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the chat page when present, fallback to a tiny placeholder."""
        if selected_index is not None:
            return selected_index.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router
