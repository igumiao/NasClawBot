"""HTTP routes for chat search and explicit download actions."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.agent import NasClawAgentRunner
from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.qb_routes import build_qb_router
from app.api.schemas import (
    AgentSessionDetailResponse,
    AgentSessionListResponse,
    AgentSessionSummary,
    ChatRequest,
    ChatResponse,
    DownloadRequest,
    DownloadResponse,
)
from app.config import get_settings
from app.tools import MTeamSearchTool, QBAddTorrentTool
from hello_agents.checkpoints import JSONConversationCheckpointStore

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST_INDEX = _FRONTEND_DIR / "dist" / "index.html"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"
_AGENT_SESSION_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-sessions"


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


def _agent_checkpoint_store() -> JSONConversationCheckpointStore:
    return JSONConversationCheckpointStore(_AGENT_SESSION_DIR)


def build_router() -> APIRouter:
    selected_index = _select_frontend_index()
    router = APIRouter()
    router.include_router(build_qb_router())

    @router.get("/health")
    def health() -> dict[str, str]:
        """Basic liveness probe used by local checks/tests."""
        return {"status": "ok"}

    @router.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        """Run a minimal readonly search through the M-Team tool."""

        query = request.message.strip()
        if not query:
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message="请输入搜索关键词。",
                error="message is required",
            )

        search_tool = MTeamSearchTool(_build_mteam_adapter())
        response = search_tool.run_with_timing({"keyword": query})
        tool_call = {
            "tool": search_tool.name,
            "status": response.status.value,
            "stats": response.stats or {},
        }

        if response.status.value == "error":
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message=response.text,
                tool_calls=[tool_call],
                error=response.text,
            )

        results = response.data.get("candidates", [])
        return ChatResponse(
            session_id=request.session_id,
            status="completed",
            message=f"找到 {len(results)} 个搜索结果。",
            results=results,
            tool_calls=[tool_call],
        )

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

    @router.post("/download", response_model=DownloadResponse)
    def download(request: DownloadRequest) -> DownloadResponse:
        """Explicitly add one M-Team torrent to qBittorrent in paused mode."""

        download_tool = QBAddTorrentTool(_build_mteam_adapter(), _build_qb_adapter())
        response = download_tool.run(
            {
                "torrent_id": request.torrent_id,
                "qb_category": request.qb_category,
            }
        )
        if response.status.value == "error":
            return DownloadResponse(status="error", error=response.text)
        return DownloadResponse(
            status="completed",
            receipt=response.data.get("receipt"),
        )

    @router.get("/", response_class=HTMLResponse)
    def index() -> str:
        """Serve the chat page when present, fallback to a tiny placeholder."""
        if selected_index is not None:
            return selected_index.read_text(encoding="utf-8")
        return "<h1>fnOS Media Agent</h1>"

    return router
