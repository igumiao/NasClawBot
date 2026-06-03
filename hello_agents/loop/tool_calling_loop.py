"""Generic tool-calling conversation loop.

This module contains the framework-level loop mechanics shared by production
tool-calling agents. Teaching-oriented ReAct behavior lives in agent presets,
not in this loop.
"""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..context import ContextWindowManager
from ..core.message import Message
from ..tools import ToolResponse

if TYPE_CHECKING:
    from ..core.agent import Agent


DEFAULT_MAX_STEPS_MESSAGE = "抱歉，我无法在限定步数内完成这个任务。"
MAX_STEPS_FINALIZATION_PROMPT = """工具调用步数已经达到上限。

不要再调用任何工具。请基于当前对话和已经得到的工具结果，给用户一个简洁的最终回答：
- 总结目前已经确认的信息
- 说明哪些部分仍然没有完成或不确定
- 不要声称执行了尚未执行的操作
"""


@dataclass
class ToolObservation:
    """Structured observation produced by one model-requested tool call."""

    tool_name: str
    tool_call_id: str
    arguments: Dict[str, Any]
    response: ToolResponse
    observation_text: str
    truncated: bool = False
    # Loop/truncation stats, not tool execution stats. Tool stats live on response.stats.
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallingLoopResult:
    """Result returned by the generic loop."""

    final_answer: str
    steps: int
    tool_observations: List[ToolObservation] = field(default_factory=list)
    status: str = "success"

    @property
    def tool_executions(self) -> List[ToolObservation]:
        """Backward-compatible alias for older callers."""
        return self.tool_observations


class ToolCallingLoop:
    """Run LLM tool calls until the model returns final text.

    The loop deliberately relies on the owning Agent for framework services:
    history, tool schema construction, tool execution, compression, tracing,
    and session persistence.
    """

    def __init__(
        self,
        agent: "Agent",
        max_steps: int = 5,
        max_steps_message: str = DEFAULT_MAX_STEPS_MESSAGE,
        session_name: Optional[str] = None,
    ):
        self.agent = agent
        self.max_steps = max_steps
        self.max_steps_message = max_steps_message
        self.session_name = session_name
        self.context_window_manager = ContextWindowManager(agent)

    def run(self, input_text: str, **kwargs: Any) -> ToolCallingLoopResult:
        """Run one user turn through the generic tool-calling loop."""

        self.agent.add_message(Message(input_text, "user"))
        messages = self._build_api_messages()
        tool_schemas = self.agent._build_tool_schemas()
        tool_observations: List[ToolObservation] = []

        if not tool_schemas:
            messages = self._prepare_messages_for_model_call(messages, [])
            response = self.agent.llm.invoke(messages, **kwargs)
            final_answer = response.content if hasattr(response, "content") else str(response)
            self.agent.add_message(Message(final_answer, "assistant"))
            self._save_session_if_enabled()
            return ToolCallingLoopResult(
                final_answer=final_answer,
                steps=1,
                status="success",
            )

        for step in range(1, self.max_steps + 1):
            messages = self._prepare_messages_for_model_call(messages, tool_schemas)
            response = self.agent.llm.invoke_with_tools(
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                **kwargs,
            )
            self._log_model_output(step, response)

            tool_calls = response.tool_calls or []
            if not tool_calls:
                final_answer = response.content or ""
                self.agent.add_message(Message(final_answer, "assistant"))
                self._save_session_if_enabled()
                return ToolCallingLoopResult(
                    final_answer=final_answer,
                    steps=step,
                    tool_observations=tool_observations,
                    status="success",
                )

            assistant_message = self._assistant_tool_call_message(response)
            messages.append(assistant_message)
            self.agent.add_message(
                Message(
                    response.content or "",
                    "assistant",
                    metadata={"tool_calls": assistant_message["tool_calls"]},
                )
            )

            for tool_call in tool_calls:
                arguments = self._parse_arguments(tool_call.arguments)
                if arguments is None:
                    response = ToolResponse.error(
                        code="INVALID_ARGUMENTS",
                        message=f"参数格式不正确 - {tool_call.arguments}",
                        context={"tool_name": tool_call.name},
                    )
                else:
                    response = self._execute_tool_call(tool_call.name, arguments)

                observation_text, truncation = self._build_observation_text(tool_call.name, response)
                observation = ToolObservation(
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                    arguments=arguments or {},
                    response=response,
                    observation_text=observation_text,
                    truncated=bool(truncation.get("truncated", False)),
                    stats=truncation.get("stats", {}),
                )
                self._log_tool_result(step, observation)
                tool_observations.append(observation)

                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": observation.observation_text,
                }
                messages.append(tool_message)
                self.agent.add_message(
                    Message(
                        observation.observation_text,
                        "tool",
                        metadata={
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_call.name,
                        },
                    )
                )

        final_answer = self._finalize_after_max_steps(
            messages=messages,
            tool_schemas=tool_schemas,
            **kwargs,
        )
        self.agent.add_message(Message(final_answer, "assistant"))
        self._save_session_if_enabled()
        return ToolCallingLoopResult(
            final_answer=final_answer,
            steps=self.max_steps,
            tool_observations=tool_observations,
            status="max_steps",
        )

    def _prepare_messages_for_model_call(
        self,
        messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        compressed = self.context_window_manager.prepare_for_model_call(
            messages=messages,
            tools=tool_schemas,
        )
        if compressed:
            return self._build_api_messages()
        return messages

    def _build_api_messages(self) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []

        if self.agent.system_prompt:
            messages.append({"role": "system", "content": self.agent.system_prompt})

        for message in self.agent.history_manager.get_history():
            if message.role == "system":
                continue

            metadata = message.metadata or {}
            if message.role == "assistant" and metadata.get("tool_calls"):
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": metadata["tool_calls"],
                    }
                )
            elif message.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": metadata.get("tool_call_id", ""),
                        "content": message.content,
                    }
                )
            elif message.role in {"user", "assistant"}:
                messages.append({"role": message.role, "content": message.content})
            elif message.role == "summary":
                messages.append({"role": "system", "content": message.content})

        return messages

    @staticmethod
    def _assistant_tool_call_message(response: Any) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                }
                for tool_call in response.tool_calls
            ],
        }

    @staticmethod
    def _parse_arguments(raw_arguments: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return {"input": parsed}
        return parsed

    def _execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResponse:
        if not self.agent.tool_registry:
            return ToolResponse.error(
                code="TOOL_REGISTRY_MISSING",
                message="未配置工具注册表",
                context={"tool_name": tool_name},
            )

        return self.agent.tool_registry.execute_tool(tool_name, arguments)

    def _build_observation_text(
        self,
        tool_name: str,
        response: ToolResponse,
    ) -> tuple[str, Dict[str, Any]]:
        output = response.to_json()
        truncate_result = self.agent.truncator.truncate(
            tool_name=tool_name,
            output=output,
        )
        return truncate_result.get("preview", output), truncate_result

    def _finalize_after_max_steps(
        self,
        messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        final_messages = messages + [
            {
                "role": "system",
                "content": MAX_STEPS_FINALIZATION_PROMPT,
            }
        ]

        try:
            response = self.agent.llm.invoke_with_tools(
                messages=final_messages,
                tools=tool_schemas,
                tool_choice="none",
                **kwargs,
            )
        except Exception as exc:
            if self.agent.config.debug:
                print(f"达到最大步数后的最终总结失败: {exc}")
            return self.max_steps_message

        self._log_model_output(self.max_steps + 1, response)
        if response.tool_calls:
            return self.max_steps_message
        return response.content or self.max_steps_message

    def _log_model_output(self, step: int, response: Any) -> None:
        if not self.agent.trace_logger:
            return

        usage = response.usage or {}
        self.agent.trace_logger.log_event(
            "model_output",
            {
                "content": response.content or "",
                "tool_calls": len(response.tool_calls or []),
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            },
            step=step,
        )

    def _log_tool_result(
        self,
        step: int,
        observation: ToolObservation,
    ) -> None:
        if not self.agent.trace_logger:
            return

        self.agent.trace_logger.log_event(
            "tool_call",
            {
                "tool_name": observation.tool_name,
                "tool_call_id": observation.tool_call_id,
                "args": observation.arguments,
            },
            step=step,
        )
        self.agent.trace_logger.log_event(
            "tool_result",
            {
                "tool_name": observation.tool_name,
                "tool_call_id": observation.tool_call_id,
                "status": observation.response.status.value,
                "text": observation.response.text,
                "data": observation.response.data,
                "error": observation.response.error_info,
                "tool_stats": observation.response.stats,
                "observation_text": observation.observation_text,
                "truncated": observation.truncated,
                "observation_stats": observation.stats,
            },
            step=step,
        )

    def _save_session_if_enabled(self) -> None:
        if not self.agent.session_store:
            return

        try:
            self.agent.save_session(self.session_name or "session-auto")
        except Exception as exc:
            if self.agent.config.debug:
                print(f"自动保存会话失败: {exc}")
