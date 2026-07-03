"""Generic tool-calling conversation loop.

This module contains the framework-level loop mechanics shared by production
tool-calling agents. Teaching-oriented ReAct behavior lives in agent presets,
not in this loop.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import uuid4

from ..context import ContextWindowManager
from ..core.message import Message
from ..tools import ToolResponse
from ..tools.gate import GateResult, ToolCall as GateToolCall

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
    gate_result: Optional[str] = None
    gate_reason: Optional[str] = None
    approval_id: Optional[str] = None
    # Loop/truncation stats, not tool execution stats. Tool stats live on response.stats.
    stats: Dict[str, Any] = field(default_factory=dict)
    # Intermediate assistant text emitted before this round of tool calls.
    assistant_text: str = ""
    # Thinking-model chain-of-thought (e.g. DeepSeek-R1 reasoning_content).
    reasoning_content: Optional[str] = None


@dataclass
class ToolCallingLoopResult:
    """Result returned by the generic loop."""

    final_answer: str
    steps: int
    tool_observations: List[ToolObservation] = field(default_factory=list)
    status: str = "success"
    pending_approvals: List[Dict[str, Any]] = field(default_factory=list)
    paused_loop: Optional[Dict[str, Any]] = None

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
        tool_schemas = self._build_visible_tool_schemas()
        visible_tool_names = self._tool_schema_names(tool_schemas)
        filter_active = bool(getattr(self.agent, "tool_filter", None))
        tool_observations: List[ToolObservation] = []
        pending_approvals: List[Dict[str, Any]] = []

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
            gate_plan = self._build_gate_plan(
                tool_calls=tool_calls,
                filter_active=filter_active,
                visible_tool_names=visible_tool_names,
            )
            ask_user_items = [item for item in gate_plan if item["gate_result_enum"] == GateResult.ASK_USER]
            if len(ask_user_items) > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": self._approval_conflict_replan_message(ask_user_items),
                    }
                )
                continue

            messages.append(assistant_message)
            assistant_meta: Dict[str, Any] = {"tool_calls": assistant_message["tool_calls"]}
            llm_reasoning = getattr(response, "reasoning_content", None)
            if llm_reasoning:
                assistant_meta["reasoning_content"] = llm_reasoning
            self.agent.add_message(
                Message(
                    response.content or "",
                    "assistant",
                    metadata=assistant_meta,
                )
            )
            if ask_user_items:
                ask_item = ask_user_items[0]
                gate_reason = "Tool call requires user approval."
                approval = self._build_pending_approval(
                    tool_call_id=ask_item["tool_call"].id,
                    tool_name=ask_item["tool_call"].name,
                    arguments=ask_item["arguments"] or {},
                    reason=gate_reason,
                )
                pending_approvals.append(approval)
                observation = self._pending_approval_observation(ask_item, approval, response.content or "", getattr(response, "reasoning_content", None))
                tool_observations.append(observation)
                self._log_tool_result(step, observation)
                approval_message = self._pending_approval_message(pending_approvals)
                paused_loop = self._build_paused_loop_state(
                    approval=approval,
                    assistant_message=assistant_message,
                    pending_item=ask_item,
                    gate_plan=gate_plan,
                    step=step,
                )
                self._save_session_if_enabled()
                return ToolCallingLoopResult(
                    final_answer=approval_message,
                    steps=step,
                    tool_observations=tool_observations,
                    status="awaiting_approval",
                    pending_approvals=pending_approvals,
                    paused_loop=paused_loop,
                )

            _llm_content = response.content or ""
            _llm_reasoning = getattr(response, "reasoning_content", None)
            for item in gate_plan:
                tool_call = item["tool_call"]
                arguments = item["arguments"]
                gate_result = item["gate_result"]
                gate_reason = item["gate_reason"]
                tool_response = item["response"]
                if tool_response is None:
                    tool_response = self._execute_tool_call(tool_call.name, arguments or {})
                observation_text, truncation = self._build_observation_text(tool_call.name, tool_response)
                observation = ToolObservation(
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                    arguments=arguments or {},
                    response=tool_response,
                    observation_text=observation_text,
                    truncated=bool(truncation.get("truncated", False)),
                    gate_result=gate_result,
                    gate_reason=gate_reason,
                    stats=truncation.get("stats", {}),
                    assistant_text=_llm_content,
                    reasoning_content=_llm_reasoning,
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
            pending_approvals=pending_approvals,
        )

    def resume(
        self,
        paused_loop: Dict[str, Any],
        tool_response: ToolResponse,
        **kwargs: Any,
    ) -> ToolCallingLoopResult:
        """Resume a provider tool-call turn after an external approval decision."""

        messages = self._build_api_messages()
        tool_schemas = self._build_visible_tool_schemas()
        pending_call = dict(paused_loop.get("pending_tool_call") or {})
        pending_tool_name = str(pending_call.get("name") or "")
        pending_tool_call_id = str(pending_call.get("id") or "")
        pending_arguments = dict(pending_call.get("arguments") or {})
        step = int(paused_loop.get("step") or 1)

        tool_observations: List[ToolObservation] = []
        pending_approvals: List[Dict[str, Any]] = []
        response_by_id = {pending_tool_call_id: tool_response}
        for skipped_call in paused_loop.get("other_tool_calls") or []:
            skipped_id = str(skipped_call.get("id") or "")
            if skipped_id:
                response_by_id[skipped_id] = ToolResponse.error(
                    code="TOOL_SKIPPED_DURING_APPROVAL",
                    message="本轮工具调用因等待用户确认而未执行。",
                    context={"tool_name": skipped_call.get("name", "")},
                )

        for raw_call in paused_loop.get("tool_calls") or [pending_call]:
            tool_call_id = str(raw_call.get("id") or "")
            tool_name = str(raw_call.get("name") or "")
            arguments = dict(raw_call.get("arguments") or {})
            response = response_by_id.get(tool_call_id)
            if response is None:
                response = ToolResponse.error(
                    code="TOOL_SKIPPED_DURING_APPROVAL",
                    message="本轮工具调用因等待用户确认而未执行。",
                    context={"tool_name": tool_name},
                )
            observation_text, truncation = self._build_observation_text(tool_name, response)
            assistant_msg = paused_loop.get("assistant_message") or {}
            observation = ToolObservation(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                response=response,
                observation_text=observation_text,
                truncated=bool(truncation.get("truncated", False)),
                approval_id=paused_loop.get("approval_id") if tool_call_id == pending_tool_call_id else None,
                stats=truncation.get("stats", {}),
                assistant_text=str(assistant_msg.get("content") or ""),
            )
            self._log_tool_result(step, observation)
            tool_observations.append(observation)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": observation.observation_text,
                }
            )
            self.agent.add_message(
                Message(
                    observation.observation_text,
                    "tool",
                    metadata={
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                    },
                )
            )

        return self._continue_after_tool_messages(
            messages=messages,
            tool_schemas=tool_schemas,
            tool_observations=tool_observations,
            pending_approvals=pending_approvals,
            start_step=step + 1,
            **kwargs,
        )

    def _continue_after_tool_messages(
        self,
        messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        tool_observations: List[ToolObservation],
        pending_approvals: List[Dict[str, Any]],
        start_step: int,
        **kwargs: Any,
    ) -> ToolCallingLoopResult:
        visible_tool_names = self._tool_schema_names(tool_schemas)
        filter_active = bool(getattr(self.agent, "tool_filter", None))

        for step in range(start_step, self.max_steps + 1):
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
            gate_plan = self._build_gate_plan(
                tool_calls=tool_calls,
                filter_active=filter_active,
                visible_tool_names=visible_tool_names,
            )
            ask_user_items = [item for item in gate_plan if item["gate_result_enum"] == GateResult.ASK_USER]
            if len(ask_user_items) > 1:
                messages.append(
                    {
                        "role": "system",
                        "content": self._approval_conflict_replan_message(ask_user_items),
                    }
                )
                continue

            messages.append(assistant_message)
            assistant_meta: Dict[str, Any] = {"tool_calls": assistant_message["tool_calls"]}
            llm_reasoning = getattr(response, "reasoning_content", None)
            if llm_reasoning:
                assistant_meta["reasoning_content"] = llm_reasoning
            self.agent.add_message(
                Message(
                    response.content or "",
                    "assistant",
                    metadata=assistant_meta,
                )
            )
            if ask_user_items:
                ask_item = ask_user_items[0]
                gate_reason = "Tool call requires user approval."
                approval = self._build_pending_approval(
                    tool_call_id=ask_item["tool_call"].id,
                    tool_name=ask_item["tool_call"].name,
                    arguments=ask_item["arguments"] or {},
                    reason=gate_reason,
                )
                pending_approvals.append(approval)
                observation = self._pending_approval_observation(ask_item, approval, response.content or "", getattr(response, "reasoning_content", None))
                tool_observations.append(observation)
                self._log_tool_result(step, observation)
                approval_message = self._pending_approval_message(pending_approvals)
                paused_loop = self._build_paused_loop_state(
                    approval=approval,
                    assistant_message=assistant_message,
                    pending_item=ask_item,
                    gate_plan=gate_plan,
                    step=step,
                )
                self._save_session_if_enabled()
                return ToolCallingLoopResult(
                    final_answer=approval_message,
                    steps=step,
                    tool_observations=tool_observations,
                    status="awaiting_approval",
                    pending_approvals=pending_approvals,
                    paused_loop=paused_loop,
                )

            _llm_content = response.content or ""
            _llm_reasoning = getattr(response, "reasoning_content", None)
            for item in gate_plan:
                tool_call = item["tool_call"]
                arguments = item["arguments"]
                gate_result = item["gate_result"]
                gate_reason = item["gate_reason"]
                tool_response = item["response"]
                if tool_response is None:
                    tool_response = self._execute_tool_call(tool_call.name, arguments or {})
                observation_text, truncation = self._build_observation_text(tool_call.name, tool_response)
                observation = ToolObservation(
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                    arguments=arguments or {},
                    response=tool_response,
                    observation_text=observation_text,
                    truncated=bool(truncation.get("truncated", False)),
                    gate_result=gate_result,
                    gate_reason=gate_reason,
                    stats=truncation.get("stats", {}),
                    assistant_text=_llm_content,
                    reasoning_content=_llm_reasoning,
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
            pending_approvals=pending_approvals,
        )

    def _build_gate_plan(
        self,
        tool_calls: List[Any],
        filter_active: bool,
        visible_tool_names: set[str],
    ) -> List[Dict[str, Any]]:
        plan: List[Dict[str, Any]] = []
        for tool_call in tool_calls:
            arguments = self._parse_arguments(tool_call.arguments)
            gate_result: Optional[str] = None
            gate_reason: Optional[str] = None
            gate_result_enum = GateResult.ALLOW
            response: ToolResponse | None = None

            if arguments is None:
                response = ToolResponse.error(
                    code="INVALID_ARGUMENTS",
                    message=f"参数格式不正确 - {tool_call.arguments}",
                    context={"tool_name": tool_call.name},
                )
            elif filter_active and tool_call.name not in visible_tool_names:
                gate_result_enum = GateResult.DENY
                gate_result = "deny"
                gate_reason = "Tool is not visible in this agent turn."
                response = ToolResponse.error(
                    code="TOOL_NOT_VISIBLE",
                    message=f"工具 '{tool_call.name}' 当前不可用。",
                    context={"tool_name": tool_call.name},
                )
            else:
                gate_result_enum = self._check_gate(tool_call.name, arguments)
                gate_result = self._gate_result_name(gate_result_enum)
                if gate_result_enum == GateResult.ASK_USER:
                    authorization = self._authorize_tool_call(tool_call.name, arguments)
                    if authorization:
                        gate_result_enum = GateResult.ALLOW
                        gate_result = "allow"
                        gate_reason = str(authorization.get("reason") or "Allowed by session authorization grant")
                if gate_result_enum == GateResult.DENY:
                    gate_reason = "Tool call was denied by the permission gate."
                    response = ToolResponse.error(
                        code="PERMISSION_DENIED",
                        message=f"工具调用被权限规则拒绝: {tool_call.name}",
                        context={"tool_name": tool_call.name},
                    )

            plan.append(
                {
                    "tool_call": tool_call,
                    "arguments": arguments,
                    "gate_result": gate_result,
                    "gate_reason": gate_reason,
                    "gate_result_enum": gate_result_enum,
                    "response": response,
                }
            )
        return plan

    def _pending_approval_observation(
        self,
        item: Dict[str, Any],
        approval: Dict[str, Any],
        assistant_text: str = "",
        reasoning_content: Optional[str] = None,
    ) -> ToolObservation:
        tool_call = item["tool_call"]
        response = ToolResponse.pending_approval(
            text=f"工具调用需要用户确认后才能执行: {tool_call.name}",
            data={"approval": approval},
            context={"tool_name": tool_call.name},
        )
        return ToolObservation(
            tool_name=tool_call.name,
            tool_call_id=tool_call.id,
            arguments=item["arguments"] or {},
            response=response,
            observation_text=response.to_json(),
            gate_result="ask_user",
            gate_reason="Tool call requires user approval.",
            approval_id=approval["approval_id"],
            assistant_text=assistant_text,
            reasoning_content=reasoning_content,
        )

    def _build_visible_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = self.agent._build_tool_schemas()
        tool_filter = getattr(self.agent, "tool_filter", None)
        if not tool_filter:
            return schemas

        allowed_names = set(tool_filter.apply(list(self._tool_schema_names(schemas))))
        return [
            schema
            for schema in schemas
            if schema.get("function", {}).get("name") in allowed_names
        ]

    @staticmethod
    def _tool_schema_names(tool_schemas: List[Dict[str, Any]]) -> set[str]:
        return {
            str(schema.get("function", {}).get("name"))
            for schema in tool_schemas
            if schema.get("function", {}).get("name")
        }

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

    def _check_gate(self, tool_name: str, arguments: Dict[str, Any]) -> GateResult:
        gate = getattr(self.agent, "tool_gate", None)
        if not gate:
            return GateResult.ALLOW
        return gate.check(GateToolCall(tool_name=tool_name, params=arguments))

    def _authorize_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any] | None:
        hook = getattr(self.agent, "authorize_tool_call", None)
        if not callable(hook):
            return None
        result = hook(tool_name, arguments)
        if isinstance(result, dict) and result.get("authorized") is True:
            return result
        return None

    @staticmethod
    def _gate_result_name(result: GateResult) -> str:
        return result.name.lower()

    @staticmethod
    def _build_pending_approval(
        tool_call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "approval_id": f"approval_{uuid4().hex}",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "status": "pending",
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _approval_conflict_replan_message(ask_user_items: List[Dict[str, Any]]) -> str:
        tool_names = [
            str(item["tool_call"].name)
            for item in ask_user_items
            if item.get("tool_call") is not None
        ]
        names = ", ".join(tool_names)
        return (
            "Runtime constraint: your previous response requested multiple approval-gated tool calls "
            f"({names}). The application can pause for only one user approval at a time. "
            "Retry this turn by requesting exactly one approval-gated tool call. "
            "If the action is a same-kind batch and a batch tool is available, use the batch tool instead. "
            "Do not tell the user about this internal retry unless you cannot continue."
        )

    @staticmethod
    def _serialize_tool_call(tool_call: Any, arguments: Dict[str, Any] | None) -> Dict[str, Any]:
        return {
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": arguments or {},
            "raw_arguments": tool_call.arguments,
        }

    def _build_paused_loop_state(
        self,
        approval: Dict[str, Any],
        assistant_message: Dict[str, Any],
        pending_item: Dict[str, Any],
        gate_plan: List[Dict[str, Any]],
        step: int,
    ) -> Dict[str, Any]:
        pending_tool_call = self._serialize_tool_call(
            pending_item["tool_call"],
            pending_item["arguments"],
        )
        tool_calls = [
            self._serialize_tool_call(item["tool_call"], item["arguments"])
            for item in gate_plan
        ]
        return {
            "approval_id": approval["approval_id"],
            "assistant_message": assistant_message,
            "pending_tool_call": pending_tool_call,
            "tool_calls": tool_calls,
            "other_tool_calls": [
                tool_call
                for tool_call in tool_calls
                if tool_call["id"] != pending_tool_call["id"]
            ],
            "step": step,
            "resume_policy": {
                "final_tool_choice": "none",
                "append_user_message": False,
            },
        }

    @staticmethod
    def _pending_approval_message(pending_approvals: List[Dict[str, Any]]) -> str:
        if len(pending_approvals) == 1:
            return f"工具调用需要用户确认后才能执行: {pending_approvals[0].get('tool_name', '')}"
        return f"有 {len(pending_approvals)} 个工具调用需要用户确认后才能执行。"

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

    def _finalize_after_resume(
        self,
        messages: List[Dict[str, Any]],
        tool_schemas: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        try:
            response = self.agent.llm.invoke_with_tools(
                messages=messages,
                tools=tool_schemas,
                tool_choice="none",
                **kwargs,
            )
        except Exception as exc:
            if self.agent.config.debug:
                print(f"审批恢复后的最终总结失败: {exc}")
            return "审批结果已记录，但生成最终回复失败。"

        self._log_model_output(0, response)
        if response.tool_calls:
            return "审批结果已记录。"
        return response.content or "审批结果已记录。"

    def _log_model_output(self, step: int, response: Any) -> None:
        usage = response.usage or {}

        # 记录上次模型请求的输入上下文用量，供前端指示器使用。
        if usage.get("prompt_tokens"):
            self.agent._last_context_usage = {
                "context_window": self.agent.config.context_window,
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
                "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
            }
            metadata = getattr(self.agent, "_session_metadata", None)
            if not isinstance(metadata, dict):
                metadata = {}
                setattr(self.agent, "_session_metadata", metadata)
            previous = metadata.get("session_usage")
            if not isinstance(previous, dict):
                previous = {}
            total_tokens = usage.get("total_tokens", 0)
            if not total_tokens:
                total_tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
            cache_miss_tokens = usage.get("prompt_cache_miss_tokens", 0)
            latency_ms = int(getattr(response, "latency_ms", 0) or 0)
            metadata["session_usage"] = {
                "context_window": self.agent.config.context_window,
                "model_calls": int(previous.get("model_calls") or 0) + 1,
                "total_tokens": int(previous.get("total_tokens") or 0) + total_tokens,
                "total_prompt_tokens": int(previous.get("total_prompt_tokens") or 0) + prompt_tokens,
                "total_completion_tokens": int(previous.get("total_completion_tokens") or 0) + completion_tokens,
                "total_cache_hit_tokens": int(previous.get("total_cache_hit_tokens") or 0) + cache_hit_tokens,
                "total_cache_miss_tokens": int(previous.get("total_cache_miss_tokens") or 0) + cache_miss_tokens,
                "llm_latency_ms": int(previous.get("llm_latency_ms") or 0) + latency_ms,
            }

        if not self.agent.trace_logger:
            return

        self.agent.trace_logger.log_event(
            "model_output",
            {
                "content": response.content or "",
                "tool_calls": len(response.tool_calls or []),
                "usage": dict(usage),
                "latency_ms": int(getattr(response, "latency_ms", 0) or 0),
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

        tool_latency_ms = (observation.response.stats or {}).get("time_ms", 0)

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
                "gate_result": observation.gate_result,
                "gate_reason": observation.gate_reason,
                "approval_id": observation.approval_id,
                "latency_ms": tool_latency_ms,
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
