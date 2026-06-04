"""Application-level Agent runner for NasClawBot conversations."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.config import get_settings
from app.domain.models import ResourceCandidate
from app.tools import MTeamSearchTool, QBAddTorrentTool
from hello_agents.agents import ToolCallingAgent
from hello_agents.checkpoints import ConversationCheckpoint, ConversationCheckpointStore
from hello_agents.core.config import Config
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.message import Message
from hello_agents.tools import Filter, Gate, ToolRegistry
from hello_agents.tools.response import ToolResponse


AGENT_SESSION_PROMPT = """你是 NasClawBot 的媒体搜索和下载助手。

你可以使用 mteam_search 搜索候选资源。
当用户明确要求下载某个 M-Team torrent id 或上一轮候选资源时，可以调用 qb_add_torrent 提出下载请求。
qb_add_torrent 会先等待用户确认；在用户确认前，不要声称已经下载或已经提交到 qBittorrent。
只有后端审批执行返回成功结果后，才能说下载任务已经提交。
如果用户追问上一轮搜索结果，可以结合当前会话历史回答。
当需要搜索时，调用 mteam_search；当用户明确要求下载时，调用 qb_add_torrent；当已有信息足够时，直接回答。
回答要简洁，并优先列出标题、分辨率、做种数、大小和 M-Team torrent id。
"""


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
    checkpoint: ConversationCheckpoint | None = None


class NasClawAgentRunner:
    """Run a NasClawBot Agent turn with durable conversation checkpoints.

    The current Agent tool set includes readonly `mteam_search` and
    confirm-gated `qb_add_torrent`. Approval decisions are resolved
    deterministically by the runner instead of resuming the provider
    tool-call protocol.
    """

    def __init__(
        self,
        checkpoint_store: ConversationCheckpointStore,
        llm_factory: Callable[..., Any] | None = None,
        mteam_adapter_factory: Callable[..., MTeamAdapter] | None = None,
        qb_adapter_factory: Callable[..., QBittorrentAdapter] | None = None,
        max_steps: int = 4,
        agent_config_overrides: dict[str, Any] | None = None,
        tool_filter: Filter | None = None,
        tool_gate: Gate | None = None,
    ):
        self.checkpoint_store = checkpoint_store
        self.llm_factory = llm_factory or HelloAgentsLLM
        self.mteam_adapter_factory = mteam_adapter_factory or MTeamAdapter
        self.qb_adapter_factory = qb_adapter_factory or QBittorrentAdapter
        self.max_steps = max_steps
        self.agent_config_overrides = agent_config_overrides or {}
        self.tool_filter = tool_filter or Filter(allow=["mteam_search", "qb_add_torrent"])
        self.tool_gate = tool_gate or Gate(confirm=[lambda call: call.tool_name == "qb_add_torrent"])

    def run(self, session_id: str, message: str) -> AgentRunResult:
        checkpoint = self.checkpoint_store.load(session_id)
        agent = self._build_agent()
        if checkpoint:
            self._restore_history(agent, checkpoint)

        answer = agent.run(message)
        pending_approvals = self._agent_pending_approvals(agent)
        saved_checkpoint = self._checkpoint_from_agent(
            session_id=session_id,
            agent=agent,
            prior_checkpoint=checkpoint,
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

    def _build_agent(self) -> ToolCallingAgent:
        settings = get_settings()
        llm = self.llm_factory(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
        )
        registry = ToolRegistry()
        registry.register_tool(
            MTeamSearchTool(
                self.mteam_adapter_factory(
                    base_url=settings.mteam_base_url,
                    api_key=settings.mteam_api_key,
                )
            )
        )
        registry.register_tool(
            QBAddTorrentTool(
                self.mteam_adapter_factory(
                    base_url=settings.mteam_base_url,
                    api_key=settings.mteam_api_key,
                ),
                self.qb_adapter_factory(
                    base_url=settings.qb_base_url,
                    username=settings.qb_username,
                    password=settings.qb_password,
                ),
            )
        )
        config_values = {
            "trace_enabled": False,
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
            system_prompt=AGENT_SESSION_PROMPT,
            config=Config(**config_values),
            max_steps=self.max_steps,
            tool_filter=self.tool_filter,
            tool_gate=self.tool_gate,
        )

    def approve(self, session_id: str, approval_id: str) -> AgentApprovalResult:
        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint is None:
            raise KeyError("Agent session not found")

        approval = self._find_approval(checkpoint, approval_id)
        if approval is None:
            raise KeyError("Approval not found")
        if approval.get("status") != "pending":
            raise ValueError("Approval has already been resolved")
        if approval.get("tool_name") != "qb_add_torrent":
            raise ValueError("Only qb_add_torrent approvals can be executed")

        response = self._execute_approved_tool(approval)
        decided_at = datetime.now().isoformat()

        if response.status.value == "error":
            message = f"下载请求执行失败：{response.text}"
            status = "failed"
            error = response.text
            receipt = None
            approval.update(
                {
                    "status": status,
                    "decided_at": decided_at,
                    "error": response.error_info or {"message": response.text},
                }
            )
        else:
            receipt = response.data.get("receipt")
            message = self._approval_success_message(approval, receipt)
            status = "approved"
            error = None
            approval.update(
                {
                    "status": status,
                    "decided_at": decided_at,
                    "result": response.to_dict(),
                }
            )

        saved_checkpoint = self._save_approval_decision(
            checkpoint=checkpoint,
            approval=approval,
            assistant_message=message,
            last_status="success" if status == "approved" else "tool_error",
        )
        self.checkpoint_store.save(saved_checkpoint)
        return AgentApprovalResult(
            session_id=session_id,
            approval_id=approval_id,
            status=status,
            message=message,
            receipt=receipt,
            error=error,
            checkpoint=saved_checkpoint,
        )

    def deny(self, session_id: str, approval_id: str) -> AgentApprovalResult:
        checkpoint = self.checkpoint_store.load(session_id)
        if checkpoint is None:
            raise KeyError("Agent session not found")

        approval = self._find_approval(checkpoint, approval_id)
        if approval is None:
            raise KeyError("Approval not found")
        if approval.get("status") != "pending":
            raise ValueError("Approval has already been resolved")

        approval.update(
            {
                "status": "denied",
                "decided_at": datetime.now().isoformat(),
            }
        )
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
            approval_id=approval_id,
            status="denied",
            message=message,
            checkpoint=saved_checkpoint,
        )

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

    def _execute_approved_tool(self, approval: dict[str, Any]) -> ToolResponse:
        settings = get_settings()
        tool = QBAddTorrentTool(
            self.mteam_adapter_factory(
                base_url=settings.mteam_base_url,
                api_key=settings.mteam_api_key,
            ),
            self.qb_adapter_factory(
                base_url=settings.qb_base_url,
                username=settings.qb_username,
                password=settings.qb_password,
            ),
        )
        return tool.run_with_timing(dict(approval.get("arguments", {})))

    @staticmethod
    def _find_approval(
        checkpoint: ConversationCheckpoint,
        approval_id: str,
    ) -> dict[str, Any] | None:
        for approval in checkpoint.metadata.get("pending_approvals", []):
            if approval.get("approval_id") == approval_id:
                return approval
        for approval in checkpoint.metadata.get("approvals", []):
            if approval.get("approval_id") == approval_id:
                return approval
        return None

    @staticmethod
    def _save_approval_decision(
        checkpoint: ConversationCheckpoint,
        approval: dict[str, Any],
        assistant_message: str,
        last_status: str,
    ) -> ConversationCheckpoint:
        now = datetime.now().isoformat()
        checkpoint.history.append(Message(assistant_message, "assistant").to_dict())
        checkpoint.saved_at = now
        checkpoint.metadata["last_status"] = last_status
        checkpoint.metadata["pending_approvals"] = [
            item
            for item in checkpoint.metadata.get("pending_approvals", [])
            if item.get("approval_id") != approval.get("approval_id")
        ]
        approvals = list(checkpoint.metadata.get("approvals", []))
        approvals.append(deepcopy(approval))
        checkpoint.metadata["approvals"] = approvals
        checkpoint.metadata["turn_count"] = sum(1 for message in checkpoint.history if message.get("role") == "user")
        return checkpoint

    @staticmethod
    def _approval_success_message(
        approval: dict[str, Any],
        receipt: dict[str, Any] | None,
    ) -> str:
        arguments = approval.get("arguments", {})
        torrent_id = str(arguments.get("torrent_id", ""))
        category = str(arguments.get("qb_category", ""))
        if receipt:
            title = receipt.get("resource_title") or torrent_id
            status = receipt.get("status") or "submitted_paused"
            return f"下载请求已提交到 qBittorrent（暂停状态）：{title}。torrent_id={torrent_id}, category={category}, status={status}。"
        return f"下载请求已提交到 qBittorrent（暂停状态）。torrent_id={torrent_id}, category={category}。"

    @staticmethod
    def _checkpoint_from_agent(
        session_id: str,
        agent: ToolCallingAgent,
        prior_checkpoint: ConversationCheckpoint | None,
    ) -> ConversationCheckpoint:
        now = datetime.now().isoformat()
        history = [message.to_dict() for message in agent.get_history()]
        archives = list(getattr(agent, "_conversation_archives", prior_checkpoint.archives if prior_checkpoint else []))
        metadata = dict(prior_checkpoint.metadata if prior_checkpoint else {})
        metadata.update(
            {
                "agent_name": agent.name,
                "model": getattr(agent.llm, "model", None),
                "tool_names": NasClawAgentRunner._tool_names(agent),
                "last_status": agent.last_result.status if agent.last_result else "success",
                "pending_approvals": NasClawAgentRunner._agent_pending_approvals(agent),
                "turn_count": sum(1 for message in agent.get_history() if message.role == "user"),
                "archive_count": len(archives),
            }
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

    @staticmethod
    def _agent_pending_approvals(agent: ToolCallingAgent) -> list[dict[str, Any]]:
        if not agent.last_result:
            return []
        return deepcopy(agent.last_result.pending_approvals)

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
