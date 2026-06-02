"""HTTP routes for chat search and explicit download actions."""

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.qb_routes import build_qb_router
from app.api.schemas import ChatRequest, ChatResponse, DownloadRequest, DownloadResponse
from app.config import get_settings
from app.domain.models import ResourceCandidate
from app.tools import MTeamSearchTool, QBAddTorrentTool
from hello_agents.agents import ToolCallingAgent
from hello_agents.core.config import Config
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.tools import ToolRegistry

_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST_INDEX = _FRONTEND_DIR / "dist" / "index.html"
_FRONTEND_INDEX = _FRONTEND_DIR / "index.html"
_AGENT_SESSION_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-sessions"
_SESSION_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")

_READONLY_AGENT_PROMPT = """你是 NasClawBot 的只读媒体搜索助手。

你只能使用 mteam_search 搜索候选资源。不要承诺、触发或暗示已经下载。
如果用户追问上一轮搜索结果，可以结合当前会话历史回答。
当需要搜索时，调用 mteam_search；当已有信息足够时，直接回答。
回答要简洁，并优先列出标题、分辨率、做种数、大小和 M-Team torrent id。
"""


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


def _agent_session_name(session_id: str) -> str:
    cleaned = _SESSION_NAME_PATTERN.sub("-", session_id.strip())[:120].strip(".-")
    return cleaned or "default"


def _agent_session_path(session_name: str) -> Path:
    return _AGENT_SESSION_DIR / f"{session_name}.json"


def _build_readonly_agent() -> ToolCallingAgent:
    settings = get_settings()
    llm = HelloAgentsLLM(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.2,
    )
    registry = ToolRegistry()
    registry.register_tool(MTeamSearchTool(_build_mteam_adapter()))
    return ToolCallingAgent(
        name="nasclawbot-readonly",
        llm=llm,
        tool_registry=registry,
        system_prompt=_READONLY_AGENT_PROMPT,
        config=Config(
            trace_enabled=False,
            session_enabled=True,
            session_dir=str(_AGENT_SESSION_DIR),
            skills_enabled=False,
            subagent_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            tool_output_dir=str(_AGENT_SESSION_DIR / "tool-output"),
        ),
        max_steps=4,
    )


def _load_agent_session(agent: ToolCallingAgent, session_name: str) -> None:
    session_path = _agent_session_path(session_name)
    if session_path.exists():
        agent.load_session(str(session_path), check_consistency=False)


def _agent_tool_calls(agent: ToolCallingAgent) -> list[dict[str, Any]]:
    if not agent.last_result:
        return []
    return [
        {
            "tool": record.tool_name,
            "tool_call_id": record.tool_call_id,
            "arguments": record.arguments,
        }
        for record in agent.last_result.tool_executions
    ]


def _agent_results(agent: ToolCallingAgent) -> list[ResourceCandidate]:
    if not agent.last_result:
        return []

    results: list[ResourceCandidate] = []
    for record in agent.last_result.tool_executions:
        if record.tool_name != "mteam_search":
            continue
        try:
            payload = json.loads(record.result)
        except json.JSONDecodeError:
            continue
        for row in payload.get("data", {}).get("candidates", []):
            results.append(ResourceCandidate.model_validate(row))
    return results


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

        session_name = _agent_session_name(request.session_id)
        agent = _build_readonly_agent()
        _load_agent_session(agent, session_name)

        try:
            answer = agent.run(query, session_name=session_name)
        except Exception as exc:
            return ChatResponse(
                session_id=request.session_id,
                status="error",
                message="Agent 调用失败。",
                error=str(exc),
            )

        return ChatResponse(
            session_id=request.session_id,
            status="completed",
            message=answer,
            results=_agent_results(agent),
            tool_calls=_agent_tool_calls(agent),
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
