"""Application-level Agent runner for NasClawBot conversations."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import json
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hello_agents.observability import TraceLogger

# Module-level registry: one TraceLogger per conversation session,
# surviving across requests so all turns of one conversation write to the same trace files.
_trace_loggers: dict[str, TraceLogger] = {}
_trace_loggers_lock = Lock()

# Module-level: one qB adapter shared across all HTTP requests within the process.
# The adapter caches the authenticated client internally; the process-level cache
# avoids re-creating the adapter (and re-authenticating) on every request.
_qb_adapter: "QBittorrentAdapter | None" = None
_qb_adapter_lock = Lock()


def _reset_module_qb_adapter() -> None:
    """Reset the module-level qB adapter (used in tests for isolation)."""
    global _qb_adapter
    with _qb_adapter_lock:
        _qb_adapter = None


def _get_or_create_trace_logger(session_id: str) -> TraceLogger:
    with _trace_loggers_lock:
        if session_id not in _trace_loggers:
            _trace_loggers[session_id] = TraceLogger(
                output_dir="memory/traces",
                session_id=session_id,
            )
        return _trace_loggers[session_id]


def _cleanup_session_trace(session_id: str) -> None:
    """Finalize and remove a session's trace logger. Called on session delete."""
    with _trace_loggers_lock:
        tl = _trace_loggers.pop(session_id, None)
    if tl:
        try:
            tl.finalize()
        except Exception:
            pass

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.adapters.tavily import TavilyAdapter
from app.adapters.tmdb import TMDBAdapter
from app.agent.approvals import (
    ApprovalRecord,
    ApprovalStatus,
    create_pending_approval,
    mark_approved,
    mark_denied,
    mark_expired,
    mark_failed,
)
from app.agent.runtime_state import (
    update_runtime_state_after_approval,
    update_runtime_state_after_turn,
)
from app.config import get_settings
from app.domain.authorization import (
    DownloadAuthorizationPolicy,
    approval_authorization_info,
    authorize_with_session_grant,
    create_session_grant,
    granted_item_count,
)
from app.domain.models import ResourceCandidate
from app.services.download_authorization_store import DownloadAuthorizationPolicyStore
from app.services.download_defaults_store import DownloadDefaultsStore
from app.services.markdown_memory_store import MarkdownMemoryStore
from app.tools import (
    CurrentTimeTool,
    MemberProfileTool,
    MemorySearchTool,
    MTeamSearchTool,
    QBAddTorrentTool,
    QBAddTorrentsTool,
    QBListTorrentsTool,
    QBGetTorrentTool,
    QBListCategoriesTool,
    QBControlTorrentTool,
    QBSetGlobalSpeedTool,
    QBSetTorrentSpeedTool,
    TavilySearchTool,
    TMDBSearchTool,
    TMDBDetailsTool,
    TMDBDiscoverTool,
    TMDBTrendingTool,
)
from hello_agents.agents import ToolCallingAgent
from hello_agents.checkpoints import ConversationCheckpoint, ConversationCheckpointStore
from hello_agents.core.config import Config
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.message import Message
from hello_agents.tools import Filter, Gate, ToolRegistry
from hello_agents.tools.response import ToolResponse


_SESSION_LOCKS: dict[str, RLock] = {}
_SESSION_LOCKS_GUARD = Lock()
_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"
_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-memory"


def _session_lock(session_id: str) -> RLock:
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id, RLock())


def _serialize_session(method: Callable[..., Any]) -> Callable[..., Any]:
    """Serialize one session inside the current server process."""

    @wraps(method)
    def wrapper(self: Any, session_id: str, *args: Any, **kwargs: Any) -> Any:
        with _session_lock(session_id):
            return method(self, session_id, *args, **kwargs)

    return wrapper


AGENT_SESSION_PROMPT = f"""你是 NasClawBot 的媒体搜索和下载助手。

用工具而不是猜测。工具描述中已经包含各工具的适用场景和参数约束。

搜索策略：
- 明确片名先查资源站；模糊、最新、角色、剧情、别名或跨语言问题先澄清实体，再查资源站。
- 网络搜索可以分别用中文、英文或中英混合查询同一问题，并综合结果判断。
- 资源站标题召回默认优先英文标题、原名或罗马字标题；结果不理想时再换中文名、别名或原名。华语圈限定内容也可以直接中文搜。
- 电视剧、综艺、动画、季集资源优先用名称、别名、年份、季号、集号判断标题；IMDb 只作辅助线索，不默认硬过滤。

安全边界：
- 下载、控制、限速、删除等操作类工具会等待用户确认；确认前不要声称已经执行。
- 只有后端审批执行返回成功后，才能说任务已经提交或操作已经完成。

回答要简洁，并优先列出标题、分辨率、做种数、大小、优惠状态和 M-Team torrent id。
"""


def _agent_session_prompt(settings: Any, profile_memory: str = "") -> str:
    """Build the Agent system prompt with a fresh server date anchor."""
    try:
        tz = ZoneInfo(settings.app_timezone)
        timezone_name = settings.app_timezone
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
        timezone_name = "UTC"
    today = datetime.now(tz).date().isoformat()
    date_line = (
        f"当前日期：{today}，时区：{timezone_name}。"
        "判断已上映、未上映、最新、最近时，以工具结果中的日期和当前日期为准。"
    )
    prompt = f"{AGENT_SESSION_PROMPT}\n{date_line}"
    if profile_memory.strip():
        prompt = f"{prompt}\n\n长期用户画像：\n{profile_memory.strip()}"
    return prompt


@dataclass
class AgentRunResult:
    """Route-facing result of one Agent conversation turn."""

    session_id: str
    status: str
    answer: str
    results: list[ResourceCandidate]
    tool_calls: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    checkpoint: ConversationCheckpoint


@dataclass
class AgentApprovalResult:
    """Route-facing result of one deterministic approval decision."""

    session_id: str
    approval_id: str
    status: str
    message: str
    receipt: dict[str, Any] | None = None
    error: str | None = None
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    checkpoint: ConversationCheckpoint | None = None


class NasClawAgentRunner:
    """Run a NasClawBot Agent turn with durable conversation checkpoints.

    The current Agent tool set includes readonly `mteam_search` and
    confirm-gated `qb_add_torrent`. Approval decisions execute business
    effects in the runner, then resume the paused provider tool-call protocol.
    """

    def __init__(
        self,
        checkpoint_store: ConversationCheckpointStore,
        llm_factory: Callable[..., Any] | None = None,
        mteam_adapter_factory: Callable[..., MTeamAdapter] | None = None,
        qb_adapter_factory: Callable[..., QBittorrentAdapter] | None = None,
        max_steps: int = 30,
        agent_config_overrides: dict[str, Any] | None = None,
        tool_filter: Filter | None = None,
        tool_gate: Gate | None = None,
        approval_summary_enabled: bool = True,
        memory_root: Path | None = None,
    ):
        self.checkpoint_store = checkpoint_store
        self.llm_factory = llm_factory or HelloAgentsLLM
        self.mteam_adapter_factory = mteam_adapter_factory or MTeamAdapter
        self.qb_adapter_factory = qb_adapter_factory or QBittorrentAdapter
        self.max_steps = max_steps
        self.agent_config_overrides = agent_config_overrides or {}
        self.tool_filter = tool_filter or Filter(allow=[
            "current_time",
            "memory_search",
            "mteam_search",
            "member_profile",
            "qb_add_torrent",
            "qb_add_torrents",
            "qb_list_torrents",
            "qb_get_torrent",
            "qb_list_categories",
            "qb_control_torrent",
            "qb_set_global_speed",
            "qb_set_torrent_speed",
            "tavily_search",
            "tmdb_search",
            "tmdb_details",
            "tmdb_discover",
            "tmdb_trending",
        ])
        self.tool_gate = tool_gate or Gate(confirm=[
            lambda call: call.tool_name == "qb_add_torrent",
            lambda call: call.tool_name == "qb_add_torrents",
            lambda call: call.tool_name == "qb_control_torrent",
            lambda call: call.tool_name == "qb_set_global_speed",
            lambda call: call.tool_name == "qb_set_torrent_speed",
        ])
        self.approval_summary_enabled = approval_summary_enabled
        self.memory_root = memory_root or _MEMORY_DIR

    @_serialize_session
    def run(self, session_id: str, message: str) -> AgentRunResult:
        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint:
            checkpoint = self._expire_pending_approvals(checkpoint)
        if checkpoint and self._pending_approval_dicts(checkpoint):
            return AgentRunResult(
                session_id=session_id,
                status="awaiting_approval",
                answer="当前会话有待确认的工具调用，请先批准或拒绝后再继续。",
                results=[],
                tool_calls=[],
                pending_approvals=self._pending_approval_dicts(checkpoint),
                checkpoint=checkpoint,
            )

        agent = self._build_agent()
        agent.trace_logger = _get_or_create_trace_logger(session_id)
        if checkpoint:
            self._restore_history(agent, checkpoint)
        self._install_authorization_hook(agent, checkpoint)

        answer = agent.run(message)
        pending_approvals = self._agent_pending_approvals(agent, session_id)
        saved_checkpoint = self._checkpoint_from_agent(
            session_id=session_id,
            agent=agent,
            user_message=message,
            prior_checkpoint=checkpoint,
            pending_approvals=pending_approvals,
        )
        self.checkpoint_store.save(saved_checkpoint)

        return AgentRunResult(
            session_id=session_id,
            status=agent.last_result.status if agent.last_result else "success",
            answer=answer,
            results=self._agent_results(agent),
            tool_calls=self._agent_tool_calls(agent),
            pending_approvals=pending_approvals,
            checkpoint=saved_checkpoint,
        )

    def _get_qb_adapter(self) -> QBittorrentAdapter:
        """Return the process-level cached qB adapter, creating it once.

        Double-checked locking: first read without lock (fast path), then
        acquire lock for the create-once guarantee. The adapter itself caches
        the authenticated client internally, so every request within the
        process reuses the same SID until the qB session expires.
        """
        global _qb_adapter
        if _qb_adapter is not None:
            return _qb_adapter
        with _qb_adapter_lock:
            if _qb_adapter is not None:
                return _qb_adapter
            settings = get_settings()
            _qb_adapter = self.qb_adapter_factory(
                base_url=settings.qb_base_url,
                username=settings.qb_username,
                password=settings.qb_password,
            )
            return _qb_adapter

    def _build_agent(self) -> ToolCallingAgent:
        settings = get_settings()
        llm = self.llm_factory(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
        )
        mteam_adapter = self.mteam_adapter_factory(
            base_url=settings.mteam_base_url,
            api_key=settings.mteam_api_key,
        )
        qb_adapter = self._get_qb_adapter()
        registry = ToolRegistry()
        memory_store = MarkdownMemoryStore(self.memory_root)
        registry.register_tool(CurrentTimeTool(timezone_name=settings.app_timezone))
        registry.register_tool(MemorySearchTool(memory_store))
        registry.register_tool(MTeamSearchTool(mteam_adapter))
        registry.register_tool(MemberProfileTool(mteam_adapter))

        defaults_store = DownloadDefaultsStore(Path(__file__).resolve().parents[2] / "memory" / "settings")
        download_defaults = defaults_store.load()
        default_save_path = download_defaults.default_save_path

        registry.register_tool(QBAddTorrentTool(mteam_adapter, qb_adapter, default_save_path=default_save_path))
        registry.register_tool(QBAddTorrentsTool(mteam_adapter, qb_adapter, default_save_path=default_save_path))
        registry.register_tool(QBListTorrentsTool(qb_adapter))
        registry.register_tool(QBGetTorrentTool(qb_adapter))
        registry.register_tool(QBListCategoriesTool(qb_adapter))
        registry.register_tool(QBControlTorrentTool(qb_adapter))
        registry.register_tool(QBSetGlobalSpeedTool(qb_adapter))
        registry.register_tool(QBSetTorrentSpeedTool(qb_adapter))
        tavily_adapter = TavilyAdapter(api_key=settings.tavily_api_key)
        registry.register_tool(TavilySearchTool(tavily_adapter))
        tmdb_adapter = TMDBAdapter(api_key=settings.tmdb_api_key)
        registry.register_tool(TMDBSearchTool(tmdb_adapter))
        registry.register_tool(TMDBDetailsTool(tmdb_adapter))
        registry.register_tool(TMDBDiscoverTool(tmdb_adapter))
        registry.register_tool(TMDBTrendingTool(tmdb_adapter))
        config_values = {
            "trace_enabled": False,  # runner manages trace per conversation session
            "session_enabled": False,
            "skills_enabled": False,
            "subagent_enabled": False,
            "todowrite_enabled": False,
            "devlog_enabled": False,
            "preflight_compression_enabled": True,
            "write_time_compression_enabled": False,
            "enable_smart_compression": True,
            "context_window": 64000,
            "compression_threshold": 0.7,
            "min_retain_rounds": 4,
        }
        config_values.update(self.agent_config_overrides)
        return ToolCallingAgent(
            name="nasclawbot-agent",
            llm=llm,
            tool_registry=registry,
            system_prompt=_agent_session_prompt(settings, memory_store.format_user_profile_prompt()),
            config=Config(**config_values),
            max_steps=self.max_steps,
            tool_filter=self.tool_filter,
            tool_gate=self.tool_gate,
        )

    @_serialize_session
    def approve(
        self,
        session_id: str,
        approval_id: str,
        decision: str = "approve_once",
    ) -> AgentApprovalResult:
        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint is None:
            raise KeyError("Agent session not found")

        approval = self._find_approval(checkpoint, approval_id)
        if approval is None:
            raise KeyError("Approval not found")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("Approval has already been resolved")
        if approval.is_expired():
            saved_checkpoint = self._expire_approval(
                checkpoint=checkpoint,
                approval=approval,
            )
            self.checkpoint_store.save(saved_checkpoint)
            raise ValueError("Approval has expired")
        if decision == "approve_and_grant_session":
            self._validate_grant_decision(approval)
        elif decision != "approve_once":
            raise ValueError("Unknown approval decision")
        _EXECUTABLE_TOOLS = {
            "qb_add_torrent",
            "qb_add_torrents",
            "qb_control_torrent",
            "qb_set_global_speed",
            "qb_set_torrent_speed",
        }
        if approval.tool_name not in _EXECUTABLE_TOOLS:
            raise ValueError(f"Tool '{approval.tool_name}' cannot be executed via approval")

        paused_loop = self._find_paused_loop(checkpoint, approval_id)
        if not paused_loop:
            return self._approve_deterministically(
                session_id,
                checkpoint,
                approval,
                decision=decision,
            )
        self._validate_paused_loop_matches_approval(paused_loop, approval)

        response = self._execute_approved_tool(approval)
        if decision == "approve_and_grant_session" and response.status.value != "error":
            self._create_grant_from_approval(checkpoint, approval, response)

        if response.status.value == "error":
            mark_failed(approval, response)
            status = ApprovalStatus.FAILED.value
            error = response.text
            receipt = None
        else:
            receipt = response.data.get("receipt")
            mark_approved(approval, response)
            status = ApprovalStatus.APPROVED.value
            error = None

        agent = self._build_agent()
        agent.trace_logger = _get_or_create_trace_logger(session_id)
        self._restore_history(agent, checkpoint)
        message = agent.resume_tool_call(paused_loop, response)
        saved_checkpoint = self._checkpoint_from_resumed_agent(
            checkpoint=checkpoint,
            agent=agent,
            approval=approval,
            last_status="success" if status == ApprovalStatus.APPROVED.value else "tool_error",
        )
        self.checkpoint_store.save(saved_checkpoint)
        return AgentApprovalResult(
            session_id=session_id,
            approval_id=approval_id,
            status=status,
            message=message,
            receipt=receipt,
            error=error,
            pending_approvals=self._pending_approval_dicts(saved_checkpoint),
            checkpoint=saved_checkpoint,
        )

    @_serialize_session
    def deny(self, session_id: str, approval_id: str) -> AgentApprovalResult:
        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint is None:
            raise KeyError("Agent session not found")

        approval = self._find_approval(checkpoint, approval_id)
        if approval is None:
            raise KeyError("Approval not found")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("Approval has already been resolved")
        if approval.is_expired():
            saved_checkpoint = self._expire_approval(
                checkpoint=checkpoint,
                approval=approval,
            )
            self.checkpoint_store.save(saved_checkpoint)
            raise ValueError("Approval has expired")

        paused_loop = self._find_paused_loop(checkpoint, approval_id)
        if not paused_loop:
            return self._deny_deterministically(session_id, checkpoint, approval)
        self._validate_paused_loop_matches_approval(paused_loop, approval)

        mark_denied(approval)
        denial_response = ToolResponse.error(
            code="USER_DENIED",
            message="用户拒绝了这次工具调用。",
            context={"tool_name": approval.tool_name},
        )
        agent = self._build_agent()
        agent.trace_logger = _get_or_create_trace_logger(session_id)
        self._restore_history(agent, checkpoint)
        message = agent.resume_tool_call(paused_loop, denial_response)
        saved_checkpoint = self._checkpoint_from_resumed_agent(
            checkpoint=checkpoint,
            agent=agent,
            approval=approval,
            last_status="approval_denied",
        )
        self.checkpoint_store.save(saved_checkpoint)
        return AgentApprovalResult(
            session_id=session_id,
            approval_id=approval_id,
            status="denied",
            message=message,
            pending_approvals=self._pending_approval_dicts(saved_checkpoint),
            checkpoint=saved_checkpoint,
        )

    def _approve_deterministically(
        self,
        session_id: str,
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
        decision: str = "approve_once",
    ) -> AgentApprovalResult:
        response = self._execute_approved_tool(approval)
        if decision == "approve_and_grant_session" and response.status.value != "error":
            self._create_grant_from_approval(checkpoint, approval, response)

        if response.status.value == "error":
            message = f"下载请求执行失败：{response.text}"
            mark_failed(approval, response)
            status = ApprovalStatus.FAILED.value
            error = response.text
            receipt = None
        else:
            receipt = response.data.get("receipt")
            mark_approved(approval, response)
            fallback_message = self._approval_success_message(approval, receipt)
            message = self._summarize_approval_success(
                approval=approval,
                receipt=receipt,
                fallback_message=fallback_message,
            )
            status = ApprovalStatus.APPROVED.value
            error = None

        saved_checkpoint = self._save_approval_decision(
            checkpoint=checkpoint,
            approval=approval,
            assistant_message=message,
            last_status="success" if status == ApprovalStatus.APPROVED.value else "tool_error",
        )
        self.checkpoint_store.save(saved_checkpoint)
        return AgentApprovalResult(
            session_id=session_id,
            approval_id=approval.approval_id,
            status=status,
            message=message,
            receipt=receipt,
            error=error,
            checkpoint=saved_checkpoint,
        )

    def _deny_deterministically(
        self,
        session_id: str,
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
    ) -> AgentApprovalResult:
        mark_denied(approval)
        message = "已取消这次下载请求。"
        saved_checkpoint = self._save_approval_decision(
            checkpoint=checkpoint,
            approval=approval,
            assistant_message=message,
            last_status="approval_denied",
        )
        self.checkpoint_store.save(saved_checkpoint)
        return AgentApprovalResult(
            session_id=session_id,
            approval_id=approval.approval_id,
            status="denied",
            message=message,
            checkpoint=saved_checkpoint,
        )

    @staticmethod
    def cleanup_session_trace(session_id: str) -> None:
        """Finalize and remove trace files for a deleted session."""
        _cleanup_session_trace(session_id)

    @staticmethod
    def _restore_history(agent: ToolCallingAgent, checkpoint: ConversationCheckpoint) -> None:
        agent.clear_history()
        for message_data in checkpoint.history:
            agent.history_manager.append(Message.from_dict(message_data))
        setattr(agent, "_conversation_archives", list(checkpoint.archives))
        agent._history_token_count = sum(
            agent.token_counter.count_message(message)
            for message in agent.history_manager.get_history()
        )
        agent._session_metadata = dict(checkpoint.metadata)

    def _install_authorization_hook(
        self,
        agent: ToolCallingAgent,
        checkpoint: ConversationCheckpoint | None,
    ) -> None:
        metadata = dict(checkpoint.metadata if checkpoint else {})
        metadata["authorization_grants"] = list(metadata.get("authorization_grants") or [])
        setattr(agent, "_session_metadata", metadata)
        policy = self._load_download_authorization_policy()

        def authorize_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
            session_metadata = getattr(agent, "_session_metadata", metadata)
            return authorize_with_session_grant(session_metadata, policy, tool_name, arguments)

        setattr(agent, "authorize_tool_call", authorize_tool_call)

    @staticmethod
    def _load_download_authorization_policy() -> DownloadAuthorizationPolicy:
        return DownloadAuthorizationPolicyStore(_SETTINGS_DIR).load()

    def _validate_grant_decision(self, approval: ApprovalRecord) -> None:
        info = approval_authorization_info(
            self._load_download_authorization_policy(),
            approval.tool_name,
            approval.arguments,
        )
        if not info.get("eligible"):
            raise ValueError(str(info.get("reason") or "Tool is not eligible for session authorization"))

    def _create_grant_from_approval(
        self,
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
        response: ToolResponse,
    ) -> None:
        policy = self._load_download_authorization_policy()
        used_items = granted_item_count(approval.tool_name, response.data, approval.arguments)
        grant = create_session_grant(
            policy,
            approval.tool_name,
            approval.arguments,
            used_items=used_items,
        )
        grants = [
            grant_item
            for grant_item in checkpoint.metadata.get("authorization_grants", [])
            if not (
                isinstance(grant_item, dict)
                and grant_item.get("policy_id") == grant.get("policy_id")
                and grant_item.get("status") == "active"
            )
        ]
        grants.append(grant)
        checkpoint.metadata["authorization_grants"] = grants

    def _execute_approved_tool(self, approval: ApprovalRecord) -> ToolResponse:
        settings = get_settings()
        qb_adapter = self._get_qb_adapter()

        defaults_store = DownloadDefaultsStore(Path(__file__).resolve().parents[2] / "memory" / "settings")
        download_defaults = defaults_store.load()
        default_save_path = download_defaults.default_save_path

        tool_name = approval.tool_name
        if tool_name == "qb_add_torrent":
            tool = QBAddTorrentTool(
                self.mteam_adapter_factory(
                    base_url=settings.mteam_base_url,
                    api_key=settings.mteam_api_key,
                ),
                qb_adapter,
                default_save_path=default_save_path,
            )
        elif tool_name == "qb_add_torrents":
            tool = QBAddTorrentsTool(
                self.mteam_adapter_factory(
                    base_url=settings.mteam_base_url,
                    api_key=settings.mteam_api_key,
                ),
                qb_adapter,
                default_save_path=default_save_path,
            )
        elif tool_name == "qb_control_torrent":
            tool = QBControlTorrentTool(qb_adapter)
        elif tool_name == "qb_set_global_speed":
            tool = QBSetGlobalSpeedTool(qb_adapter)
        elif tool_name == "qb_set_torrent_speed":
            tool = QBSetTorrentSpeedTool(qb_adapter)
        else:
            raise ValueError(f"Cannot execute tool: {tool_name}")

        return tool.run_with_timing(dict(approval.arguments))

    @staticmethod
    def _find_approval(
        checkpoint: ConversationCheckpoint,
        approval_id: str,
    ) -> ApprovalRecord | None:
        for approval in checkpoint.metadata.get("pending_approvals", []):
            if approval.get("approval_id") == approval_id:
                return ApprovalRecord.from_dict(approval, session_id=checkpoint.session_id)
        for approval in checkpoint.metadata.get("approvals", []):
            if approval.get("approval_id") == approval_id:
                return ApprovalRecord.from_dict(approval, session_id=checkpoint.session_id)
        return None

    def _expire_pending_approvals(
        self,
        checkpoint: ConversationCheckpoint,
    ) -> ConversationCheckpoint:
        expired: list[ApprovalRecord] = []
        for item in checkpoint.metadata.get("pending_approvals", []):
            if item.get("status") != ApprovalStatus.PENDING.value:
                continue
            approval = ApprovalRecord.from_dict(item, session_id=checkpoint.session_id)
            if approval.is_expired():
                expired.append(approval)
        if not expired:
            return checkpoint

        for approval in expired:
            checkpoint = self._expire_approval(checkpoint, approval)
        self.checkpoint_store.save(checkpoint)
        return checkpoint

    @classmethod
    def _expire_approval(
        cls,
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
    ) -> ConversationCheckpoint:
        mark_expired(approval)
        tool_call_ids = {approval.tool_call_id}
        paused_loop = checkpoint.metadata.pop("paused_loop", None)
        if isinstance(paused_loop, dict):
            pending_tool_call = paused_loop.get("pending_tool_call")
            if isinstance(pending_tool_call, dict):
                tool_call_ids.add(str(pending_tool_call.get("id") or ""))
            assistant_message = paused_loop.get("assistant_message")
            if isinstance(assistant_message, dict):
                for tool_call in assistant_message.get("tool_calls") or []:
                    if isinstance(tool_call, dict):
                        tool_call_ids.add(str(tool_call.get("id") or ""))
        tool_call_ids.discard("")
        checkpoint.history = [
            message
            for message in checkpoint.history
            if not cls._assistant_message_has_any_tool_call(message, tool_call_ids)
        ]
        return cls._save_approval_decision(
            checkpoint=checkpoint,
            approval=approval,
            assistant_message="这次下载确认已过期，请重新发起下载请求。",
            last_status="approval_expired",
        )

    @staticmethod
    def _assistant_message_has_any_tool_call(message: dict[str, Any], tool_call_ids: set[str]) -> bool:
        if message.get("role") != "assistant":
            return False
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            return False
        tool_calls = metadata.get("tool_calls")
        if not isinstance(tool_calls, list):
            return False
        return any(
            isinstance(tool_call, dict) and tool_call.get("id") in tool_call_ids
            for tool_call in tool_calls
        )

    @staticmethod
    def _save_approval_decision(
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
        assistant_message: str,
        last_status: str,
    ) -> ConversationCheckpoint:
        now = datetime.now(timezone.utc).isoformat()
        checkpoint.history.append(Message(assistant_message, "assistant").to_dict())
        checkpoint.saved_at = now
        checkpoint.metadata["last_status"] = last_status
        remaining_approvals = [
            item
            for item in checkpoint.metadata.get("pending_approvals", [])
            if item.get("approval_id") != approval.approval_id
        ]
        checkpoint.metadata["pending_approvals"] = remaining_approvals
        paused_loop = checkpoint.metadata.get("paused_loop")
        if isinstance(paused_loop, dict) and paused_loop.get("approval_id") == approval.approval_id:
            checkpoint.metadata.pop("paused_loop", None)
        approvals = list(checkpoint.metadata.get("approvals", []))
        approvals.append(approval.to_dict())
        checkpoint.metadata["approvals"] = approvals
        checkpoint.metadata["turn_count"] = sum(1 for message in checkpoint.history if message.get("role") == "user")
        checkpoint.metadata["runtime_state"] = update_runtime_state_after_approval(
            checkpoint.metadata.get("runtime_state"),
            approval=approval,
            last_status=last_status,
            pending_approvals=remaining_approvals,
            turn_count=checkpoint.metadata["turn_count"],
        )
        return checkpoint

    def _checkpoint_from_resumed_agent(
        self,
        checkpoint: ConversationCheckpoint,
        agent: ToolCallingAgent,
        approval: ApprovalRecord,
        last_status: str,
    ) -> ConversationCheckpoint:
        now = datetime.now(timezone.utc).isoformat()
        checkpoint.history = [message.to_dict() for message in agent.get_history()]
        checkpoint.saved_at = now
        checkpoint.archives = list(getattr(agent, "_conversation_archives", checkpoint.archives))
        checkpoint.metadata["last_status"] = agent.last_result.status if agent.last_result else last_status
        pending_approvals = [
            item
            for item in self._agent_pending_approvals(agent, checkpoint.session_id)
            if item.get("approval_id") != approval.approval_id
        ]
        checkpoint.metadata["pending_approvals"] = pending_approvals
        if agent.last_result and agent.last_result.paused_loop:
            checkpoint.metadata["paused_loop"] = deepcopy(agent.last_result.paused_loop)
        else:
            checkpoint.metadata.pop("paused_loop", None)
        approvals = list(checkpoint.metadata.get("approvals", []))
        approvals.append(approval.to_dict())
        checkpoint.metadata["approvals"] = approvals
        checkpoint.metadata["turn_count"] = sum(1 for message in checkpoint.history if message.get("role") == "user")
        checkpoint.metadata["archive_count"] = len(checkpoint.archives)
        checkpoint.metadata["runtime_state"] = update_runtime_state_after_approval(
            checkpoint.metadata.get("runtime_state"),
            approval=approval,
            last_status=checkpoint.metadata["last_status"],
            pending_approvals=pending_approvals,
            turn_count=checkpoint.metadata["turn_count"],
        )
        return checkpoint

    @staticmethod
    def _pending_approval_dicts(checkpoint: ConversationCheckpoint) -> list[dict[str, Any]]:
        return [
            approval
            for approval in checkpoint.metadata.get("pending_approvals", [])
            if approval.get("status") == ApprovalStatus.PENDING.value
        ]

    @staticmethod
    def _find_paused_loop(
        checkpoint: ConversationCheckpoint,
        approval_id: str,
    ) -> dict[str, Any] | None:
        paused_loop = checkpoint.metadata.get("paused_loop")
        if isinstance(paused_loop, dict) and paused_loop.get("approval_id") == approval_id:
            return deepcopy(paused_loop)
        return None

    @staticmethod
    def _validate_paused_loop_matches_approval(
        paused_loop: dict[str, Any],
        approval: ApprovalRecord,
    ) -> None:
        pending_tool_call = dict(paused_loop.get("pending_tool_call") or {})
        if pending_tool_call.get("id") != approval.tool_call_id:
            raise ValueError("Paused loop pending tool_call_id does not match approval")
        if pending_tool_call.get("name") != approval.tool_name:
            raise ValueError("Paused loop pending tool name does not match approval")
        if dict(pending_tool_call.get("arguments") or {}) != dict(approval.arguments):
            raise ValueError("Paused loop pending tool arguments do not match approval")

        assistant_message = dict(paused_loop.get("assistant_message") or {})
        tool_calls = assistant_message.get("tool_calls") or []
        for tool_call in tool_calls:
            function = dict(tool_call.get("function") or {})
            if tool_call.get("id") == approval.tool_call_id and function.get("name") == approval.tool_name:
                return
        raise ValueError("Paused loop assistant message does not contain matching tool call")

    @staticmethod
    def _approval_success_message(
        approval: ApprovalRecord,
        receipt: dict[str, Any] | None,
    ) -> str:
        torrent_id = str(approval.arguments.get("torrent_id", ""))
        category = str(approval.arguments.get("qb_category", ""))
        if approval.tool_name == "qb_add_torrents":
            items = approval.arguments.get("items")
            count = len(items) if isinstance(items, list) else 0
            if receipt:
                summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
                succeeded = summary.get("succeeded", count)
                failed = summary.get("failed", 0)
                return f"批量下载请求已提交到 qBittorrent（暂停状态）：成功 {succeeded}/{count}，失败 {failed}。"
            return f"批量下载请求已提交到 qBittorrent（暂停状态）：共 {count} 项。"
        if receipt:
            title = receipt.get("resource_title") or torrent_id
            status = receipt.get("status") or "submitted_paused"
            return f"下载请求已提交到 qBittorrent（暂停状态）：{title}。torrent_id={torrent_id}, category={category}, status={status}。"
        return f"下载请求已提交到 qBittorrent（暂停状态）。torrent_id={torrent_id}, category={category}。"

    def _summarize_approval_success(
        self,
        approval: ApprovalRecord,
        receipt: dict[str, Any] | None,
        fallback_message: str,
    ) -> str:
        if not self.approval_summary_enabled:
            return fallback_message

        settings = get_settings()
        llm = self.llm_factory(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
        )
        payload = {
            "approval_id": approval.approval_id,
            "tool_name": approval.tool_name,
            "arguments": {
                "torrent_id": approval.arguments.get("torrent_id"),
                "qb_category": approval.arguments.get("qb_category"),
            },
            "status": approval.status.value,
            "receipt": receipt or {},
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你正在总结一个已经由后端确定性执行完成的用户审批动作。"
                    "不要调用工具，不要声称执行了额外操作。"
                    "只基于给定结果，用简洁中文回复用户。"
                    "必须说明 qBittorrent 任务是暂停状态。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]
        try:
            response = llm.invoke(messages)
        except Exception:
            return fallback_message

        content = response.content if hasattr(response, "content") else str(response)
        return content.strip() or fallback_message

    @staticmethod
    def _checkpoint_from_agent(
        session_id: str,
        agent: ToolCallingAgent,
        user_message: str,
        prior_checkpoint: ConversationCheckpoint | None,
        pending_approvals: list[dict[str, Any]],
    ) -> ConversationCheckpoint:
        now = datetime.now(timezone.utc).isoformat()
        history = [message.to_dict() for message in agent.get_history()]
        archives = list(getattr(agent, "_conversation_archives", prior_checkpoint.archives if prior_checkpoint else []))
        metadata = dict(getattr(agent, "_session_metadata", prior_checkpoint.metadata if prior_checkpoint else {}))
        metadata.update(
            {
                "agent_name": agent.name,
                "model": getattr(agent.llm, "model", None),
                "tool_names": NasClawAgentRunner._tool_names(agent),
                "last_status": agent.last_result.status if agent.last_result else "success",
                "pending_approvals": deepcopy(pending_approvals),
                "turn_count": sum(1 for message in agent.get_history() if message.role == "user"),
                "archive_count": len(archives),
            }
        )
        if agent.last_result and agent.last_result.paused_loop:
            metadata["paused_loop"] = deepcopy(agent.last_result.paused_loop)
        else:
            metadata.pop("paused_loop", None)
        metadata["runtime_state"] = update_runtime_state_after_turn(
            metadata.get("runtime_state"),
            user_message=user_message,
            loop_result=agent.last_result,
            pending_approvals=deepcopy(pending_approvals),
            turn_count=metadata["turn_count"],
        )
        return ConversationCheckpoint(
            session_id=session_id,
            created_at=prior_checkpoint.created_at if prior_checkpoint else now,
            saved_at=now,
            history=history,
            archives=archives,
            metadata=metadata,
        )

    @staticmethod
    def _tool_names(agent: ToolCallingAgent) -> list[str]:
        if not agent.tool_registry:
            return []
        tool_names = list(getattr(agent.tool_registry, "_tools", {}).keys())
        function_names = list(getattr(agent.tool_registry, "_functions", {}).keys())
        return sorted(tool_names + function_names)

    @staticmethod
    def _agent_tool_calls(agent: ToolCallingAgent) -> list[dict[str, Any]]:
        if not agent.last_result:
            return []
        return [
            {
                "tool": observation.tool_name,
                "tool_call_id": observation.tool_call_id,
                "arguments": observation.arguments,
                "status": observation.response.status.value,
                "stats": observation.response.stats or {},
                "truncated": observation.truncated,
                "observation_stats": observation.stats,
                "gate_result": observation.gate_result,
                "gate_reason": observation.gate_reason,
                "approval_id": observation.approval_id,
            }
            for observation in agent.last_result.tool_observations
        ]

    def _agent_pending_approvals(self, agent: ToolCallingAgent, session_id: str) -> list[dict[str, Any]]:
        if not agent.last_result:
            return []
        policy = self._load_download_authorization_policy()
        approvals: list[dict[str, Any]] = []
        for raw in deepcopy(agent.last_result.pending_approvals):
            record = create_pending_approval(raw, session_id=session_id)
            record.authorization = approval_authorization_info(policy, record.tool_name, record.arguments)
            approvals.append(record.to_dict())
        return approvals

    @staticmethod
    def _agent_results(agent: ToolCallingAgent) -> list[ResourceCandidate]:
        if not agent.last_result:
            return []

        results: list[ResourceCandidate] = []
        for observation in agent.last_result.tool_observations:
            if observation.tool_name != "mteam_search":
                continue
            for row in observation.response.data.get("candidates", []):
                results.append(ResourceCandidate.model_validate(row))
        return results
