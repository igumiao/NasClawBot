"""Application-level Agent runner for NasClawBot conversations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.adapters.mteam import MTeamAdapter
from app.config import get_settings
from app.domain.models import ResourceCandidate
from app.tools import MTeamSearchTool
from hello_agents.agents import ToolCallingAgent
from hello_agents.checkpoints import ConversationCheckpoint, ConversationCheckpointStore
from hello_agents.core.config import Config
from hello_agents.core.llm import HelloAgentsLLM
from hello_agents.core.message import Message
from hello_agents.tools import Filter, Gate, ToolRegistry


AGENT_SESSION_PROMPT = """你是 NasClawBot 的只读媒体搜索助手。

你只能使用 mteam_search 搜索候选资源。不要承诺、触发或暗示已经下载。
如果用户追问上一轮搜索结果，可以结合当前会话历史回答。
当需要搜索时，调用 mteam_search；当已有信息足够时，直接回答。
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


class NasClawAgentRunner:
    """Run a NasClawBot Agent turn with durable conversation checkpoints.

    The current tool set is readonly `mteam_search`. The runner is intentionally
    named for the app instead of for readonly behavior so more tools can be
    added behind policy gates later.
    """

    def __init__(
        self,
        checkpoint_store: ConversationCheckpointStore,
        llm_factory: Callable[..., Any] | None = None,
        mteam_adapter_factory: Callable[..., MTeamAdapter] | None = None,
        max_steps: int = 4,
        agent_config_overrides: dict[str, Any] | None = None,
        tool_filter: Filter | None = None,
        tool_gate: Gate | None = None,
    ):
        self.checkpoint_store = checkpoint_store
        self.llm_factory = llm_factory or HelloAgentsLLM
        self.mteam_adapter_factory = mteam_adapter_factory or MTeamAdapter
        self.max_steps = max_steps
        self.agent_config_overrides = agent_config_overrides or {}
        self.tool_filter = tool_filter or Filter(allow=["mteam_search"])
        self.tool_gate = tool_gate or Gate()

    def run(self, session_id: str, message: str) -> AgentRunResult:
        checkpoint = self.checkpoint_store.load(session_id)
        agent = self._build_agent()
        if checkpoint:
            self._restore_history(agent, checkpoint)

        answer = agent.run(message)
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
            pending_approvals=agent.last_result.pending_approvals if agent.last_result else [],
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
                "pending_approvals": agent.last_result.pending_approvals if agent.last_result else [],
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
