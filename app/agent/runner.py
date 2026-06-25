"""Application-level Agent runner for NasClawBot conversations."""

from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import logging
from functools import wraps
import json
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Context variable for the current Agent session, read by download tools
# to attach the correct source_session_id to background tasks and events.
current_agent_session_id: ContextVar[str | None] = ContextVar(
    "current_agent_session_id", default=None,
)

logger = logging.getLogger(__name__)

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


def _get_or_create_trace_logger(
    session_id: str,
    output_dir: str = "memory/traces",
) -> TraceLogger:
    key = (session_id, output_dir)
    with _trace_loggers_lock:
        if key not in _trace_loggers:
            _trace_loggers[key] = TraceLogger(
                output_dir=output_dir,
                session_id=session_id,
            )
        return _trace_loggers[key]


def _cleanup_session_trace(
    session_id: str,
    output_dir: str = "memory/traces",
) -> None:
    """Finalize and remove a session's trace logger. Called on session delete."""
    key = (session_id, output_dir)
    with _trace_loggers_lock:
        tl = _trace_loggers.pop(key, None)
    if tl:
        try:
            tl.finalize()
        except Exception:
            pass

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.adapters.tavily import TavilyAdapter
from app.adapters.tmdb import TMDBAdapter
from app.agent.dependencies import AgentToolDependencies
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
from app.config import Settings, get_settings
from app.mcp_pool import get_mcp_pool
from app.domain.authorization import (
    DownloadAuthorizationPolicy,
    approval_authorization_info,
    authorize_with_session_grant,
    create_session_grant,
    granted_item_count,
)
from app.domain.models import ResourceCandidate
from app.domain.runtime_tasks import TaskEvent, app_now
from app.runtime.store import RuntimeTaskStore
from app.services.download_authorization_store import DownloadAuthorizationPolicyStore
from app.services.download_automation import DownloadAutomation
from app.services.markdown_memory_store import MarkdownMemoryStore
from app.services.tmdb_network_store import TMDBNetworkSettingsStore
from app.tools import (
    CurrentTimeTool,
    MemberProfileTool,
    MemorySearchTool,
    RememberThisTool,
    MTeamSearchTool,
    QBAddTorrentTool,
    QBListTorrentsTool,
    QBGetTorrentTool,
    QBListTagsTool,
    QBControlTorrentTool,
    QBSetGlobalSpeedTool,
    QBSetTorrentSpeedTool,
    MonitorDownloadTool,
    TaskCancelTool,
    TaskListTool,
    UpdateDownloadMonitorTool,
    ListTaskEventsTool,
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
from hello_agents.tools.mcp.bridge import register_mcp_tools
from hello_agents.tools.response import ToolResponse


_SESSION_LOCKS: dict[str, RLock] = {}
_SESSION_LOCKS_GUARD = Lock()
_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"
_MEMORY_DIR = Path(__file__).resolve().parents[2] / "memory" / "agent-memory"

# MCP filesystem tools available to the chat Agent.  The deprecated `read_file`
# (aliased to read_text_file by the server) is excluded — the canonical
# `read_text_file` with head/tail support is the only text-file reader.
_MCP_CHAT_TOOLS: list[str] = [
    "read_text_file",
    "read_media_file",
    "read_multiple_files",
    "write_file",
    "edit_file",
    "create_directory",
    "list_directory",
    "list_directory_with_sizes",
    "directory_tree",
    "move_file",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
]


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

记忆记录 — 把自己当成了解用户的贴身管家，而不是搜索引擎：

你会在对话中逐渐认识用户。当你了解到任何关于用户的事情，调用 remember_this 记下来：

- 身份与背景：名字、称呼、职业、所在城市、年龄段等
- 兴趣与爱好：影视、音乐、游戏、运动、美食、阅读，任何提到的喜好都值得记
- 生活状态：作息习惯、工作节奏、近期在忙的事情
- 观点与态度：对某部电影/某个话题的看法，喜欢什么风格，讨厌什么
- 影视偏好：画质、编码、音轨、字幕、类型
- 技术环境：硬件配置、NAS 型号、网络条件
- 其他任何让下次对话更懂用户的信息

原则：宁可多记，不要漏记。记录时放心写，后台记忆整理系统会自动去重、合并和更新。

下载策略：
- 添加下载时，根据媒体类型传入 tag 参数（电影/电视剧/综艺/动漫/纪录片），方便后续 qb_list_torrents 按标签过滤。
- 可用 qb_list_tags 查询 qBittorrent 中已存在的标签。

安全边界：
- 工具审核前不要声称已经执行工具。
- 只有后端审批执行返回成功后，才能说任务已经提交或操作已经完成。
- **用户拒绝审批时**：说明用户不想执行该操作，不要重新提交相同或类似的审批。暂停当前任务，询问用户拒绝的原因或希望如何调整。
- **工具返回错误时**：工具 observation 的 `status` 字段为 `error` 时，说明操作已执行但失败了。禁止编造"已提交"、"已添加"、"正在处理"等成功描述。

回答要简洁，并优先列出标题、分辨率、做种数、大小、优惠状态和 M-Team torrent id。
"""
# 必须立即停止当前任务，直接向用户如实报告失败原因（包含错误码和错误消息），

def _tool_display_name(tool_name: str) -> str:
    """Return a short Chinese display label for *tool_name*."""
    _LABELS: dict[str, str] = {
        "qb_add_torrent": "下载请求",
        "qb_control_torrent": "种子控制操作",
        "qb_set_global_speed": "全局限速",
        "qb_set_torrent_speed": "种子限速",
        "monitor_download": "下载监控创建",
        "task_cancel": "任务取消",
        "update_download_monitor": "下载监控修改",
    }
    return _LABELS.get(tool_name, f"操作（{tool_name}）")


def _requests_background_organization(
    tool_name: str,
    arguments: dict[str, Any],
) -> bool:
    """Return whether a download add includes background organization."""
    return (
        tool_name == "qb_add_torrent"
        and str(arguments.get("completion_action") or "") == "organize"
    )


def _agent_session_prompt(
    settings: Any,
    profile_memory: str = "",
    now: datetime | None = None,
) -> str:
    """Build the Agent system prompt with a fresh server date anchor.

    When *now* is provided it is used as the current datetime (allowing
    evaluation runs to pin the date anchor).  Otherwise ``datetime.now()``
    is called with the configured timezone.
    """
    try:
        tz = ZoneInfo(settings.app_timezone)
        timezone_name = settings.app_timezone
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
        timezone_name = "UTC"
    effective_now = now or datetime.now(tz)
    today = effective_now.date().isoformat()
    date_line = (
        f"当前日期：{today}，时区：{timezone_name}。"
        "判断已上映、未上映、最新、最近时，以工具结果中的日期和当前日期为准。"
    )
    prompt = f"{AGENT_SESSION_PROMPT}\n{date_line}"
    default_path = (settings.download_default_save_path or "").strip()
    if default_path:
        prompt = (
            f"{prompt}\n\n"
            f"默认下载路径：{default_path}。"
            f"添加下载时如不指定 save_path，种子将保存到此目录。"
        )
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
    context_usage: dict[str, Any] | None = None
    session_usage: dict[str, Any] | None = None


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
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    checkpoint: ConversationCheckpoint | None = None
    context_usage: dict[str, Any] | None = None
    session_usage: dict[str, Any] | None = None


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
        download_automation_factory: Callable[[], DownloadAutomation] | None = None,
        runtime_task_store: RuntimeTaskStore | None = None,
        task_management_service_factory: Callable[[], Any] | None = None,
        settings: Settings | None = None,
        fixed_now: datetime | None = None,
        trace_root: Path | None = None,
        dependencies: "AgentToolDependencies | None" = None,
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
            "remember_this",
            "mteam_search",
            "member_profile",
            "qb_add_torrent",
            "qb_list_torrents",
            "qb_get_torrent",
            "qb_list_tags",
            "qb_control_torrent",
            "qb_set_global_speed",
            "qb_set_torrent_speed",
            "tavily_search",
            "tmdb_search",
            "tmdb_details",
            "tmdb_discover",
            "tmdb_trending",
            "skill_load",
            "monitor_download",
            "task_list",
            "task_cancel",
            "update_download_monitor",
            "list_task_events",
        ])
        self.tool_gate = tool_gate or Gate(confirm=[
            lambda call: call.tool_name == "qb_add_torrent",
            lambda call: call.tool_name == "qb_control_torrent",
            lambda call: call.tool_name == "qb_set_global_speed",
            lambda call: call.tool_name == "qb_set_torrent_speed",
            lambda call: call.tool_name == "monitor_download",
            lambda call: call.tool_name == "task_cancel",
            lambda call: call.tool_name == "update_download_monitor",
            # MCP filesystem — gating destructive write/edit; move + mkdir are ALLOW
            lambda call: call.tool_name == "mcp_filesystem_write_file",
            lambda call: call.tool_name == "mcp_filesystem_edit_file",
        ])
        self.approval_summary_enabled = approval_summary_enabled
        self.memory_root = memory_root or _MEMORY_DIR
        self._download_automation_factory = download_automation_factory
        self._runtime_task_store = runtime_task_store
        self._task_management_service_factory = task_management_service_factory
        self.settings = settings or get_settings()
        self.fixed_now = fixed_now
        self.trace_root = trace_root or Path("memory/traces")
        self._dependencies = dependencies

    def describe_configuration(self) -> dict[str, Any]:
        """Return the effective, secret-free Agent configuration for eval manifests.

        This builds the same Agent module used by ``run`` without invoking the
        model.  Callers receive the rendered system prompt and the exact Tool
        schemas visible after Filter application, so A/B reports can hash the
        configuration that the model actually sees.
        """
        agent = self._build_agent()
        schemas = agent._build_tool_schemas()
        if self.tool_filter is not None:
            schema_names = [
                str(schema.get("function", {}).get("name") or "")
                for schema in schemas
            ]
            allowed = set(self.tool_filter.apply(schema_names))
            schemas = [
                schema
                for schema in schemas
                if str(schema.get("function", {}).get("name") or "") in allowed
            ]
        schemas.sort(key=lambda item: str(item.get("function", {}).get("name") or ""))
        return {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "max_steps": self.max_steps,
            "prompt_template": AGENT_SESSION_PROMPT,
            "rendered_prompt": agent.system_prompt or "",
            "tool_schemas": schemas,
            "timezone": self.settings.app_timezone,
            "download_path": self.settings.download_default_save_path,
        }

    @_serialize_session
    def run(self, session_id: str, message: str) -> AgentRunResult:
        current_agent_session_id.set(session_id)
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
                pending_approvals=self._enrich_approvals_for_display(
                    self._pending_approval_dicts(checkpoint),
                    default_save_path=self.settings.download_default_save_path,
                ),
                checkpoint=checkpoint,
                context_usage=checkpoint.metadata.get("context_usage"),
                session_usage=checkpoint.metadata.get("session_usage"),
            )

        # ── 加载未注入的后台任务事件，注入到 ephemeral system context ──
        uninjected_events: list[TaskEvent] = []
        extra_system_text = ""
        rt_store = self._get_runtime_task_store()
        if rt_store is not None:
            uninjected_events = rt_store.get_events_for_session(
                session_id, uninjected_only=True,
            )
            if uninjected_events:
                extra_system_text = self._format_background_events(uninjected_events)
                logger.info(
                    "Session %s: injecting background events into system prompt:\n%s",
                    session_id, extra_system_text,
                )

        agent = self._build_agent(extra_system_text=extra_system_text)
        agent.trace_logger = _get_or_create_trace_logger(session_id, output_dir=str(self.trace_root))
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

        # ── 标记事件已注入（仅在保存 checkpoint 成功后） ──
        if uninjected_events and rt_store is not None:
            rt_store.mark_events_injected(
                [e.event_id for e in uninjected_events],
                now=app_now(),
            )

        # 为 API 响应注入默认存储路径（仅展示用，不修改 checkpoint）
        display_approvals = self._enrich_approvals_for_display(
            pending_approvals, default_save_path=self.settings.download_default_save_path,
        )

        return AgentRunResult(
            session_id=session_id,
            status=agent.last_result.status if agent.last_result else "success",
            answer=answer,
            results=self._agent_results(agent),
            tool_calls=self._agent_tool_calls(agent),
            pending_approvals=display_approvals,
            checkpoint=saved_checkpoint,
            context_usage=getattr(agent, "_last_context_usage", None),
            session_usage=getattr(agent, "_session_metadata", {}).get("session_usage"),
        )

    def _get_qb_adapter(self) -> QBittorrentAdapter:
        """Return the qB adapter — recording deps in eval, else process-level cached.

        In evaluation mode the dependencies seam provides a RecordingQBAdapter
        that writes to the CallJournal without touching a real qBittorrent.
        Outside evaluation the process-level singleton reuses authenticated
        sessions across HTTP requests.
        """
        if self._dependencies is not None and self._dependencies.qb is not None:
            return self._dependencies.qb

        global _qb_adapter
        if _qb_adapter is not None:
            return _qb_adapter
        with _qb_adapter_lock:
            if _qb_adapter is not None:
                return _qb_adapter
            settings = self.settings
            _qb_adapter = self.qb_adapter_factory(
                base_url=settings.qb_base_url,
                username=settings.qb_username,
                password=settings.qb_password,
            )
            return _qb_adapter

    def _build_download_automation(self) -> DownloadAutomation | None:
        """Create DownloadAutomation via the injected factory.

        Returns ``None`` when no factory was provided (e.g. in tests that
        do not exercise the download path).
        """
        if self._download_automation_factory is None:
            return None
        return self._download_automation_factory()

    def _get_runtime_task_store(self) -> RuntimeTaskStore | None:
        """Return the runtime task store, preferring deps over the injected store."""
        if self._dependencies is not None:
            return self._dependencies.runtime_task_store
        return self._runtime_task_store

    def _get_task_management_service(self) -> Any | None:
        """Return the task management service, preferring deps over the factory."""
        if self._dependencies is not None:
            return self._dependencies.task_management
        if self._task_management_service_factory is not None:
            return self._task_management_service_factory()
        return None

    def _get_download_automation(self) -> DownloadAutomation | None:
        """Return DownloadAutomation, preferring deps over the factory."""
        if self._dependencies is not None:
            return self._dependencies.download_automation
        return self._build_download_automation()

    def _build_agent(self, extra_system_text: str = "") -> ToolCallingAgent:
        settings = self.settings
        deps = self._dependencies
        llm = self.llm_factory(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
        )
        if deps is not None:
            mteam_adapter = deps.mteam
            qb_adapter = deps.qb
            memory_store = deps.memory_store
        else:
            mteam_adapter = self.mteam_adapter_factory(
                base_url=settings.mteam_base_url,
                api_key=settings.mteam_api_key,
            )
            qb_adapter = self._get_qb_adapter()
            memory_store = MarkdownMemoryStore(self.memory_root)
            memory_store.ensure_template_files()
        registry = ToolRegistry()
        registry.register_tool(CurrentTimeTool(timezone_name=settings.app_timezone, fixed_now=self.fixed_now))
        registry.register_tool(MemorySearchTool(memory_store))
        registry.register_tool(RememberThisTool(memory_store))
        registry.register_tool(MTeamSearchTool(mteam_adapter))
        registry.register_tool(MemberProfileTool(mteam_adapter))

        default_save_path = settings.download_default_save_path

        automation = deps.download_automation if deps is not None else self._build_download_automation()
        if automation is not None:
            registry.register_tool(QBAddTorrentTool(automation))
            registry.register_tool(MonitorDownloadTool(automation))
            registry.register_tool(UpdateDownloadMonitorTool(automation))
        registry.register_tool(QBListTorrentsTool(qb_adapter))
        registry.register_tool(QBGetTorrentTool(qb_adapter))
        registry.register_tool(QBListTagsTool(qb_adapter))
        registry.register_tool(QBControlTorrentTool(qb_adapter))
        registry.register_tool(QBSetGlobalSpeedTool(qb_adapter))
        registry.register_tool(QBSetTorrentSpeedTool(qb_adapter))
        if deps is not None:
            tavily_adapter = deps.tavily
            tmdb_adapter = deps.tmdb
        else:
            tavily_adapter = TavilyAdapter(api_key=settings.tavily_api_key)
            tmdb_network = TMDBNetworkSettingsStore(_SETTINGS_DIR).load()
            tmdb_adapter = TMDBAdapter(
                api_key=settings.tmdb_api_key,
                proxy_url=tmdb_network.active_proxy_url,
            )
        registry.register_tool(TavilySearchTool(tavily_adapter))
        registry.register_tool(TMDBSearchTool(tmdb_adapter))
        registry.register_tool(TMDBDetailsTool(tmdb_adapter))
        registry.register_tool(TMDBDiscoverTool(tmdb_adapter))
        registry.register_tool(TMDBTrendingTool(tmdb_adapter))
        # ── Task management tools (when factory is available) ──
        if deps is not None:
            tms = deps.task_management
        elif self._task_management_service_factory is not None:
            tms = self._task_management_service_factory()
        else:
            tms = None
        if tms is not None:
            registry.register_tool(TaskListTool(tms))
            registry.register_tool(TaskCancelTool(tms))
        # ── Task events tool (when store is available) ─────────
        rt_store = deps.runtime_task_store if deps is not None else self._runtime_task_store
        if rt_store is not None:
            registry.register_tool(ListTaskEventsTool(rt_store))
        # ── MCP tools ──────────────────────────────────────────
        mcp_pool = deps.mcp_pool if deps is not None else get_mcp_pool()
        if mcp_pool is not None:
            register_mcp_tools(
                mcp_pool, registry, tool_filter=self.tool_filter,
                allow=_MCP_CHAT_TOOLS,
            )
        # ── Agent config ───────────────────────────────────────
        config_values = {
            "trace_enabled": False,  # runner manages trace per conversation session
            "session_enabled": False,
            "skills_enabled": True,
            "subagent_enabled": False,
            "todowrite_enabled": False,
            "devlog_enabled": False,
            "preflight_compression_enabled": True,
            "write_time_compression_enabled": False,
            "enable_smart_compression": True,
            "context_window": settings.context_window,
            "compression_threshold": 0.7,
            "min_retain_rounds": 4,
        }
        config_values.update(self.agent_config_overrides)
        agent = ToolCallingAgent(
            name="nasclawbot-agent",
            llm=llm,
            tool_registry=registry,
            system_prompt=_agent_session_prompt(settings, memory_store.format_user_profile_prompt(), now=self.fixed_now),
            config=Config(**config_values),
            max_steps=self.max_steps,
            tool_filter=self.tool_filter,
            tool_gate=self.tool_gate,
        )
        # ── 注入可用技能列表到 system prompt（L1 元数据） ──
        if agent.skill_loader is not None:
            descriptions = agent.skill_loader.get_descriptions()
            if descriptions.strip():
                skill_block = (
                    "\n\n## 可用技能 (Skills)\n\n"
                    "你可以使用 `skill_load` 工具加载任意技能的完整指导文档。"
                    "在执行特定领域的任务前，建议先加载对应的技能获取规范。\n\n"
                    f"{descriptions}"
                )
                agent.system_prompt = (agent.system_prompt or "") + skill_block
        # ── 注入后台任务事件通知（ephemeral system context，不属于 checkpoint） ──
        if extra_system_text:
            agent.system_prompt = (agent.system_prompt or "") + "\n\n" + extra_system_text
        return agent

    @_serialize_session
    def approve(
        self,
        session_id: str,
        approval_id: str,
        decision: str = "approve_once",
    ) -> AgentApprovalResult:
        current_agent_session_id.set(session_id)
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
            "qb_control_torrent",
            "qb_set_global_speed",
            "qb_set_torrent_speed",
            "monitor_download",
            "task_cancel",
            "update_download_monitor",
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
        agent.trace_logger = _get_or_create_trace_logger(session_id, output_dir=str(self.trace_root))
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
            pending_approvals=self._enrich_approvals_for_display(
                self._pending_approval_dicts(saved_checkpoint),
                default_save_path=self.settings.download_default_save_path,
            ),
            tool_calls=self._agent_tool_calls(agent),
            checkpoint=saved_checkpoint,
            context_usage=saved_checkpoint.metadata.get("context_usage"),
            session_usage=saved_checkpoint.metadata.get("session_usage"),
        )

    @_serialize_session
    def deny(self, session_id: str, approval_id: str) -> AgentApprovalResult:
        current_agent_session_id.set(session_id)
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
            message=(
                "用户拒绝了这个操作。不要重新提交相同或类似的审批请求。"
                "请暂停当前任务，询问用户为什么拒绝或希望如何调整。"
            ),
            context={"tool_name": approval.tool_name},
        )
        agent = self._build_agent()
        agent.trace_logger = _get_or_create_trace_logger(session_id, output_dir=str(self.trace_root))
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
            pending_approvals=self._enrich_approvals_for_display(
                self._pending_approval_dicts(saved_checkpoint),
                default_save_path=self.settings.download_default_save_path,
            ),
            tool_calls=self._agent_tool_calls(agent),
            checkpoint=saved_checkpoint,
            context_usage=saved_checkpoint.metadata.get("context_usage"),
            session_usage=saved_checkpoint.metadata.get("session_usage"),
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
            tool_label = _tool_display_name(approval.tool_name)
            message = f"{tool_label}执行失败：{response.text}"
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
            context_usage=saved_checkpoint.metadata.get("context_usage"),
            session_usage=saved_checkpoint.metadata.get("session_usage"),
        )

    def _deny_deterministically(
        self,
        session_id: str,
        checkpoint: ConversationCheckpoint,
        approval: ApprovalRecord,
    ) -> AgentApprovalResult:
        mark_denied(approval)
        tool_label = _tool_display_name(approval.tool_name)
        message = f"已取消这次{tool_label}。"
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
            context_usage=saved_checkpoint.metadata.get("context_usage"),
            session_usage=saved_checkpoint.metadata.get("session_usage"),
        )

    @staticmethod
    def cleanup_session_trace(session_id: str, trace_root: str = "memory/traces") -> None:
        """Finalize and remove trace files for a deleted session."""
        _cleanup_session_trace(session_id, output_dir=trace_root)

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

    def compact_session(self, session_id: str) -> "CompactResponse":
        """Manually force context compression on a session checkpoint.

        Loads the checkpoint, builds the agent with normal config, and forces
        preflight compression regardless of the current token count.  Useful
        for testing and for inspecting what the LLM summary looks like.
        """
        from app.api.schemas import CompactResponse
        from hello_agents.context.window_manager import ContextWindowManager

        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint is None:
            raise KeyError("Agent session not found")

        message_count_before = len(checkpoint.history)

        agent = self._build_agent()
        self._restore_history(agent, checkpoint)

        wm = ContextWindowManager(agent)
        compressed = wm._compress_active_history(estimated_tokens=999_999)

        if not compressed:
            return CompactResponse(
                session_id=session_id,
                compressed=False,
                summary=None,
                archive=None,
                message_count_before=message_count_before,
                message_count_after=len(checkpoint.history),
                estimated_tokens_before=agent._history_token_count,
            )

        # ── 提取压缩结果 ──
        summary = None
        for msg in agent.history_manager.get_history():
            if msg.role == "summary":
                summary = msg.content
                break

        archives = getattr(agent, "_conversation_archives", [])
        latest_archive = archives[-1] if archives else None

        # ── 持久化 ──
        now = app_now().isoformat()
        checkpoint.history = [m.to_dict() for m in agent.history_manager.get_history()]
        checkpoint.archives = [a for a in archives]
        checkpoint.saved_at = now
        checkpoint.metadata["archive_count"] = len(checkpoint.archives)
        self.checkpoint_store.save(checkpoint)

        return CompactResponse(
            session_id=session_id,
            compressed=True,
            summary=summary,
            archive=latest_archive,
            message_count_before=message_count_before,
            message_count_after=len(checkpoint.history),
            estimated_tokens_before=agent._history_token_count,
        )

    def _install_authorization_hook(
        self,
        agent: ToolCallingAgent,
        checkpoint: ConversationCheckpoint | None,
    ) -> None:
        metadata = dict(checkpoint.metadata if checkpoint else {})
        metadata["authorization_grants"] = list(metadata.get("authorization_grants") or [])
        setattr(agent, "_session_metadata", metadata)
        policy = self._load_download_authorization_policy()
        default_save_path = self.settings.download_default_save_path

        def authorize_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
            if _requests_background_organization(tool_name, arguments):
                return None
            session_metadata = getattr(agent, "_session_metadata", metadata)
            return authorize_with_session_grant(session_metadata, policy, tool_name, arguments, default_save_path)

        setattr(agent, "authorize_tool_call", authorize_tool_call)

    @staticmethod
    def _load_download_authorization_policy() -> DownloadAuthorizationPolicy:
        return DownloadAuthorizationPolicyStore(_SETTINGS_DIR).load()

    def _validate_grant_decision(self, approval: ApprovalRecord) -> None:
        if _requests_background_organization(approval.tool_name, approval.arguments):
            raise ValueError("Downloads that organize on completion require one-time approval")
        default_save_path = self.settings.download_default_save_path
        info = approval_authorization_info(
            self._load_download_authorization_policy(),
            approval.tool_name,
            approval.arguments,
            default_save_path=default_save_path,
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
        default_save_path = self.settings.download_default_save_path
        used_items = granted_item_count(approval.tool_name, response.data, approval.arguments)
        grant = create_session_grant(
            policy,
            approval.tool_name,
            approval.arguments,
            used_items=used_items,
            default_save_path=default_save_path,
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
        tool_name = approval.tool_name
        if tool_name in (
            "qb_add_torrent",
            "monitor_download",
            "update_download_monitor",
        ):
            automation = self._get_download_automation()
            if automation is None:
                raise RuntimeError(
                    "DownloadAutomation factory not configured — cannot execute download approvals."
                )
            if tool_name == "qb_add_torrent":
                tool = QBAddTorrentTool(automation)
            elif tool_name == "monitor_download":
                tool = MonitorDownloadTool(automation)
            else:
                tool = UpdateDownloadMonitorTool(automation)
            if tool_name != "update_download_monitor" and "idempotency_key" not in approval.arguments:
                approval.arguments["idempotency_key"] = approval.approval_id
        elif tool_name == "task_cancel":
            tms = self._get_task_management_service()
            if tms is None:
                raise RuntimeError(
                    "TaskManagementService factory not configured — "
                    "cannot execute task management approvals."
                )
            tool = TaskCancelTool(tms)
        else:
            qb_adapter = self._get_qb_adapter()
            if tool_name == "qb_control_torrent":
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
        tool_label = _tool_display_name(approval.tool_name)
        return cls._save_approval_decision(
            checkpoint=checkpoint,
            approval=approval,
            assistant_message=f"这次{tool_label}确认已过期，请重新发起请求。",
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
        now = app_now().isoformat()
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
        now = app_now().isoformat()
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
        context_usage = getattr(agent, "_last_context_usage", None)
        if context_usage:
            checkpoint.metadata["context_usage"] = context_usage
        session_usage = getattr(agent, "_session_metadata", {}).get("session_usage")
        if session_usage:
            checkpoint.metadata["session_usage"] = session_usage
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
        # Batch mode: arguments contain an "items" array.
        is_batch = "items" in approval.arguments
        if is_batch:
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
            state = "暂停状态" if status == "submitted_paused" else "下载中"
            return f"下载请求已提交到 qBittorrent（{state}）：{title}。torrent_id={torrent_id}, category={category}, status={status}。"
        return f"下载请求已提交到 qBittorrent（暂停状态）。torrent_id={torrent_id}, category={category}。"

    def _summarize_approval_success(
        self,
        approval: ApprovalRecord,
        receipt: dict[str, Any] | None,
        fallback_message: str,
    ) -> str:
        if not self.approval_summary_enabled:
            return fallback_message

        settings = self.settings
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
        now = app_now().isoformat()
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
        context_usage = getattr(agent, "_last_context_usage", None)
        if context_usage:
            metadata["context_usage"] = context_usage
        session_usage = getattr(agent, "_session_metadata", {}).get("session_usage")
        if session_usage:
            metadata["session_usage"] = session_usage
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
        entries: list[dict[str, Any]] = []
        for observation in agent.last_result.tool_observations:
            entry: dict[str, Any] = {
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
                "assistant_text": observation.assistant_text or "",
                "reasoning_content": observation.reasoning_content,
            }
            if observation.response.status.value == "error":
                entry["error"] = observation.response.text
            if observation.tool_name == "mteam_search":
                candidates = observation.response.data.get("candidates", [])
                if candidates:
                    entry["results"] = candidates
            entries.append(entry)
        return entries

    def _agent_pending_approvals(self, agent: ToolCallingAgent, session_id: str) -> list[dict[str, Any]]:
        if not agent.last_result:
            return []
        policy = self._load_download_authorization_policy()
        default_save_path = self.settings.download_default_save_path
        approvals: list[dict[str, Any]] = []
        for raw in deepcopy(agent.last_result.pending_approvals):
            record = create_pending_approval(raw, session_id=session_id)
            if _requests_background_organization(record.tool_name, record.arguments):
                record.authorization = {
                    "eligible": False,
                    "reason": "Downloads that organize on completion require one-time approval",
                }
            else:
                record.authorization = approval_authorization_info(
                    policy, record.tool_name, record.arguments, default_save_path=default_save_path,
                )
            approvals.append(record.to_dict())
        return approvals

    @staticmethod
    def _enrich_approvals_for_display(
        approvals: list[dict[str, Any]], default_save_path: str,
    ) -> list[dict[str, Any]]:
        """为前端展示注入默认存储路径，不修改原始数据。

        仅在 Agent 未指定 save_path 时注入，保证前端审批卡片
        始终能看到实际存储路径。
        """
        resolved = (default_save_path or "").strip()
        if not resolved or not approvals:
            return approvals
        enriched: list[dict[str, Any]] = []
        for a in approvals:
            tool_name = str(a.get("tool_name", ""))
            if tool_name != "qb_add_torrent":
                enriched.append(a)
                continue
            a = deepcopy(a)
            args = a.get("arguments", {})
            if not isinstance(args, dict):
                enriched.append(a)
                continue
            # Batch mode: "items" key in arguments.
            if "items" in args:
                for item in args.get("torrents", []) or args.get("items", []):
                    if isinstance(item, dict) and not str(item.get("save_path", "")).strip():
                        item["save_path"] = resolved
            else:
                if not str(args.get("save_path", "")).strip():
                    args["save_path"] = resolved
            enriched.append(a)
        return enriched

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

    @staticmethod
    def _format_background_events(events: list[TaskEvent]) -> str:
        """Format uninjected task events as an attention-grabbing system block.

        Injected at the TOP of the system prompt (via prepend in _build_agent)
        so the LLM cannot overlook it — a bottom-append on a long prompt is
        too easy to skim past.  The 【系统通知】 marker and explicit reporting
        instruction further reduce the chance of the LLM ignoring the block.
        """
        lines = [
            "【系统通知】后台任务状态更新",
            "",
            "以下后台任务已在本次对话之前自动完成。请在回复的开头简要告知用户这些任务的完成情况，",
            "然后继续处理用户的请求。不要重复执行这些已完成的任务。",
            "",
        ]
        for event in events:
            emoji = {
                "download_completed": "📥",
                "download_completed_no_path": "📥",
                "download_check_incomplete": "⏳",
                "organize_completed": "📁",
                "task_failed": "⚠️",
            }.get(event.kind, "📌")
            lines.append(f"{emoji} **{event.title}** — {event.summary}")
            lines.append("")
        return "\n".join(lines)
