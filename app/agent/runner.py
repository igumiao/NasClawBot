"""Application-level Agent runner for NasClawBot conversations."""

from dataclasses import dataclass
from datetime import datetime
import json
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
from hello_agents.tools import ToolRegistry


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
    ):
        self.checkpoint_store = checkpoint_store
        self.llm_factory = llm_factory or HelloAgentsLLM
        self.mteam_adapter_factory = mteam_adapter_factory or MTeamAdapter
        self.max_steps = max_steps

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
        return ToolCallingAgent(
            name="nasclawbot-agent",
            llm=llm,
            tool_registry=registry,
            system_prompt=AGENT_SESSION_PROMPT,
            config=Config(
                trace_enabled=False,
                session_enabled=False,
                skills_enabled=False,
                subagent_enabled=False,
                todowrite_enabled=False,
                devlog_enabled=False,
            ),
            max_steps=self.max_steps,
        )

    @staticmethod
    def _restore_history(agent: ToolCallingAgent, checkpoint: ConversationCheckpoint) -> None:
        agent.clear_history()
        for message_data in checkpoint.history:
            agent.history_manager.append(Message.from_dict(message_data))
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
        metadata = dict(prior_checkpoint.metadata if prior_checkpoint else {})
        metadata.update(
            {
                "agent_name": agent.name,
                "model": getattr(agent.llm, "model", None),
                "tool_names": NasClawAgentRunner._tool_names(agent),
                "last_status": agent.last_result.status if agent.last_result else "success",
                "turn_count": sum(1 for message in agent.get_history() if message.role == "user"),
            }
        )
        return ConversationCheckpoint(
            session_id=session_id,
            created_at=prior_checkpoint.created_at if prior_checkpoint else now,
            saved_at=now,
            history=history,
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
                "tool": record.tool_name,
                "tool_call_id": record.tool_call_id,
                "arguments": record.arguments,
            }
            for record in agent.last_result.tool_executions
        ]

    @staticmethod
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
