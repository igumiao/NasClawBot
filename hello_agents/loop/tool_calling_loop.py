"""Generic tool-calling conversation loop.

This module contains the framework-level loop mechanics shared by production
tool-calling agents. Teaching-oriented ReAct behavior lives in agent presets,
not in this loop.
"""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..core.message import Message

if TYPE_CHECKING:
    from ..core.agent import Agent


DEFAULT_MAX_STEPS_MESSAGE = "抱歉，我无法在限定步数内完成这个任务。"


@dataclass
class ToolExecutionRecord:
    """A compact trace record for one tool call."""

    tool_name: str
    tool_call_id: str
    arguments: Dict[str, Any]
    result: str


@dataclass
class ToolCallingLoopResult:
    """Result returned by the generic loop."""

    final_answer: str
    steps: int
    tool_executions: List[ToolExecutionRecord] = field(default_factory=list)
    status: str = "success"


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

    def run(self, input_text: str, **kwargs: Any) -> ToolCallingLoopResult:
        """Run one user turn through the generic tool-calling loop."""

        self.agent.add_message(Message(input_text, "user"))
        messages = self._build_api_messages()
        tool_schemas = self.agent._build_tool_schemas()
        tool_executions: List[ToolExecutionRecord] = []

        if not tool_schemas:
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
                    tool_executions=tool_executions,
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
                    result = f"错误：参数格式不正确 - {tool_call.arguments}"
                else:
                    result = self._execute_tool_call(tool_call.name, arguments)
                    self._log_tool_result(step, tool_call.name, tool_call.id, arguments, result)
                    tool_executions.append(
                        ToolExecutionRecord(
                            tool_name=tool_call.name,
                            tool_call_id=tool_call.id,
                            arguments=arguments,
                            result=result,
                        )
                    )

                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
                messages.append(tool_message)
                self.agent.add_message(
                    Message(
                        result,
                        "tool",
                        metadata={
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_call.name,
                        },
                    )
                )

        self.agent.add_message(Message(self.max_steps_message, "assistant"))
        self._save_session_if_enabled()
        return ToolCallingLoopResult(
            final_answer=self.max_steps_message,
            steps=self.max_steps,
            tool_executions=tool_executions,
            status="max_steps",
        )

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

    def _execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if not self.agent.tool_registry:
            return "错误：未配置工具注册表"

        response = self.agent.tool_registry.execute_tool(tool_name, arguments)
        output = response.to_json()
        truncate_result = self.agent.truncator.truncate(
            tool_name=tool_name,
            output=output,
        )
        return truncate_result.get("preview", output)

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
        tool_name: str,
        tool_call_id: str,
        arguments: Dict[str, Any],
        result: str,
    ) -> None:
        if not self.agent.trace_logger:
            return

        self.agent.trace_logger.log_event(
            "tool_call",
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "args": arguments,
            },
            step=step,
        )
        self.agent.trace_logger.log_event(
            "tool_result",
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "result": result,
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
