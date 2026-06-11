import json

from hello_agents.agents import ToolCallingAgent, create_agent
from hello_agents.core.config import Config
from hello_agents.core.message import Message
from hello_agents.core.llm_response import LLMResponse, LLMToolResponse, ToolCall
from hello_agents.tools import Filter, Gate, Tool, ToolParameter, ToolRegistry, ToolResponse


class FakeLLM:
    model = "fake-model"

    def __init__(self, tool_responses=None, text_response: str = "final"):
        self.tool_responses = list(tool_responses or [])
        self.text_response = text_response
        self.invoke_with_tools_calls = []
        self.invoke_calls = []

    def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
        self.invoke_with_tools_calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "kwargs": kwargs,
            }
        )
        if self.tool_responses:
            return self.tool_responses.pop(0)
        return LLMToolResponse(
            content=self.text_response,
            tool_calls=[],
            model=self.model,
        )

    def invoke(self, messages, **kwargs):
        self.invoke_calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(content=self.text_response, model=self.model)


class EchoTool(Tool):
    def __init__(self):
        super().__init__(name="echo", description="Echo text")
        self.calls = []

    def run(self, parameters):
        self.calls.append(parameters)
        return ToolResponse.success(text=f"echo: {parameters['text']}", data={"seen": parameters["text"]})

    def get_parameters(self):
        return [
            ToolParameter(
                name="text",
                type="string",
                description="Text to echo",
            )
        ]


class OtherTool(Tool):
    def __init__(self):
        super().__init__(name="other", description="Other tool")
        self.calls = []

    def run(self, parameters):
        self.calls.append(parameters)
        return ToolResponse.success(text="other", data={"other": True})

    def get_parameters(self):
        return []


def _config() -> Config:
    return Config(
        trace_enabled=False,
        session_enabled=False,
        skills_enabled=False,
        subagent_enabled=False,
        todowrite_enabled=False,
        devlog_enabled=False,
    )


def test_tool_calling_agent_returns_direct_text_when_no_tool_call():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content="direct answer",
                tool_calls=[],
                model="fake-model",
            )
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
    )

    answer = agent.run("hello")

    assert answer == "direct answer"
    assert len(llm.invoke_with_tools_calls) == 1
    assert [message.role for message in agent.get_history()] == ["user", "assistant"]


def test_tool_calling_agent_executes_tool_and_continues_to_final_answer():
    echo_tool = EchoTool()
    registry = ToolRegistry()
    registry.register_tool(echo_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="echo",
                        arguments=json.dumps({"text": "Dune"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="I saw echo: Dune",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
    )

    answer = agent.run("search Dune")

    assert answer == "I saw echo: Dune"
    assert echo_tool.calls == [{"text": "Dune"}]
    second_messages = llm.invoke_with_tools_calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"][0]["function"]["name"] == "echo"
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_call_id"] == "call-1"
    tool_payload = json.loads(second_messages[-1]["content"])
    assert tool_payload["text"] == "echo: Dune"
    assert tool_payload["data"] == {"seen": "Dune"}
    observation = agent.last_result.tool_observations[0]
    assert observation.tool_name == "echo"
    assert observation.tool_call_id == "call-1"
    assert observation.arguments == {"text": "Dune"}
    assert observation.response.data == {"seen": "Dune"}
    assert observation.observation_text == second_messages[-1]["content"]
    assert observation.truncated is False
    assert "time_ms" in observation.stats


def test_tool_filter_limits_tool_schemas_visible_to_model():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(OtherTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content="filtered",
                tool_calls=[],
                model="fake-model",
            )
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_filter=Filter(allow=["echo"]),
    )

    answer = agent.run("hello")

    assert answer == "filtered"
    visible_names = {
        schema["function"]["name"]
        for schema in llm.invoke_with_tools_calls[0]["tools"]
    }
    assert visible_names == {"echo"}


def test_tool_filter_blocks_hidden_tool_call_even_if_model_returns_it():
    hidden_tool = OtherTool()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(hidden_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-hidden",
                        name="other",
                        arguments="{}",
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="The tool is unavailable.",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_filter=Filter(allow=["echo"]),
    )

    answer = agent.run("use other")

    assert answer == "The tool is unavailable."
    assert hidden_tool.calls == []
    observation = agent.last_result.tool_observations[0]
    assert observation.gate_result == "deny"
    assert observation.gate_reason == "Tool is not visible in this agent turn."
    assert observation.response.error_info["code"] == "TOOL_NOT_VISIBLE"


def test_gate_deny_records_observation_without_executing_tool():
    echo_tool = EchoTool()
    registry = ToolRegistry()
    registry.register_tool(echo_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-denied",
                        name="echo",
                        arguments=json.dumps({"text": "blocked"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="I cannot run that tool.",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(deny=[lambda call: call.tool_name == "echo"]),
    )

    answer = agent.run("use echo")

    assert answer == "I cannot run that tool."
    assert echo_tool.calls == []
    observation = agent.last_result.tool_observations[0]
    assert observation.gate_result == "deny"
    assert observation.gate_reason == "Tool call was denied by the permission gate."
    assert observation.response.status.value == "error"
    assert observation.response.error_info["code"] == "PERMISSION_DENIED"
    assert agent.last_result.pending_approvals == []


def test_gate_ask_user_returns_pending_approval_without_executing_tool():
    echo_tool = EchoTool()
    registry = ToolRegistry()
    registry.register_tool(echo_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval",
                        name="echo",
                        arguments=json.dumps({"text": "needs approval"}),
                    )
                ],
                model="fake-model",
            )
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: call.tool_name == "echo"]),
    )

    answer = agent.run("use echo")

    assert answer == "工具调用需要用户确认后才能执行: echo"
    assert echo_tool.calls == []
    assert len(llm.invoke_with_tools_calls) == 1
    assert agent.last_result.status == "awaiting_approval"
    pending = agent.last_result.pending_approvals[0]
    assert pending["approval_id"].startswith("approval_")
    assert pending["tool_call_id"] == "call-approval"
    assert pending["tool_name"] == "echo"
    assert pending["arguments"] == {"text": "needs approval"}
    assert pending["status"] == "pending"
    observation = agent.last_result.tool_observations[0]
    assert observation.gate_result == "ask_user"
    assert observation.approval_id == pending["approval_id"]
    assert observation.response.status.value == "pending_approval"
    assert [message.role for message in agent.get_history()] == ["user", "assistant"]
    assert agent.last_result.paused_loop is not None
    assert agent.last_result.paused_loop["approval_id"] == pending["approval_id"]
    assert agent.last_result.paused_loop["pending_tool_call"]["id"] == "call-approval"
    assert agent.last_result.paused_loop["resume_policy"]["final_tool_choice"] == "none"


def test_gate_ask_user_pauses_before_executing_any_tool_in_the_round():
    other_tool = OtherTool()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(other_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval",
                        name="echo",
                        arguments=json.dumps({"text": "needs approval"}),
                    ),
                    ToolCall(
                        id="call-other",
                        name="other",
                        arguments="{}",
                    ),
                ],
                model="fake-model",
            )
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: call.tool_name == "echo"]),
    )

    answer = agent.run("use tools")

    assert answer == "工具调用需要用户确认后才能执行: echo"
    assert agent.last_result.status == "awaiting_approval"
    assert other_tool.calls == []
    history = agent.get_history()
    assert [message.role for message in history] == ["user", "assistant"]
    assert agent.last_result.paused_loop is not None
    assert agent.last_result.paused_loop["pending_tool_call"]["id"] == "call-approval"
    assert agent.last_result.paused_loop["other_tool_calls"][0]["id"] == "call-other"


def test_tool_calling_loop_resume_appends_tool_result_and_forces_no_tools_final_answer():
    echo_tool = EchoTool()
    registry = ToolRegistry()
    registry.register_tool(echo_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval",
                        name="echo",
                        arguments=json.dumps({"text": "needs approval"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="approved final",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: call.tool_name == "echo"]),
    )
    agent.run("use echo")
    paused_loop = agent.last_result.paused_loop

    answer = agent.resume_tool_call(
        paused_loop,
        ToolResponse.success(text="echo: needs approval", data={"seen": "needs approval"}),
    )

    assert answer == "approved final"
    assert echo_tool.calls == []
    assert len(llm.invoke_with_tools_calls) == 2
    assert llm.invoke_with_tools_calls[1]["tool_choice"] == "auto"
    resume_messages = llm.invoke_with_tools_calls[1]["messages"]
    assert resume_messages[-1]["role"] == "tool"
    assert resume_messages[-1]["tool_call_id"] == "call-approval"
    assert [message.role for message in agent.get_history()] == ["user", "assistant", "tool", "assistant"]


def test_tool_calling_loop_deny_resume_uses_user_denied_tool_error():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval",
                        name="echo",
                        arguments=json.dumps({"text": "blocked"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="denied final",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: call.tool_name == "echo"]),
    )
    agent.run("use echo")

    answer = agent.resume_tool_call(
        agent.last_result.paused_loop,
        ToolResponse.error(code="USER_DENIED", message="用户拒绝了这次工具调用。"),
    )

    assert answer == "denied final"
    assert llm.invoke_with_tools_calls[1]["tool_choice"] == "auto"
    tool_payload = json.loads(llm.invoke_with_tools_calls[1]["messages"][-1]["content"])
    assert tool_payload["error"]["code"] == "USER_DENIED"
    assert agent.last_result.status == "success"


def test_tool_calling_loop_approval_resume_can_pause_for_next_gated_tool():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(OtherTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval-a",
                        name="echo",
                        arguments=json.dumps({"text": "first"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval-b",
                        name="other",
                        arguments="{}",
                    )
                ],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: call.tool_name in {"echo", "other"}]),
    )
    agent.run("do two gated actions")

    answer = agent.resume_tool_call(
        agent.last_result.paused_loop,
        ToolResponse.success(text="echo approved", data={"ok": True}),
    )

    assert answer == "工具调用需要用户确认后才能执行: other"
    assert agent.last_result.status == "awaiting_approval"
    assert agent.last_result.pending_approvals[0]["tool_name"] == "other"
    assert agent.last_result.paused_loop["pending_tool_call"]["id"] == "call-approval-b"
    assert [message.role for message in agent.get_history()] == ["user", "assistant", "tool", "assistant"]


def test_multiple_ask_user_tool_calls_are_returned_to_model_for_replanning():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(OtherTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval-1",
                        name="echo",
                        arguments=json.dumps({"text": "one"}),
                    ),
                    ToolCall(
                        id="call-approval-2",
                        name="other",
                        arguments="{}",
                    ),
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-approval-1-retry",
                        name="echo",
                        arguments=json.dumps({"text": "one"}),
                    ),
                ],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        tool_gate=Gate(confirm=[lambda call: True]),
    )

    answer = agent.run("use both")

    assert answer == "工具调用需要用户确认后才能执行: echo"
    assert agent.last_result.status == "awaiting_approval"
    assert len(llm.invoke_with_tools_calls) == 2
    assert any(
        message["role"] == "system" and "multiple approval-gated tool calls" in message["content"]
        for message in llm.invoke_with_tools_calls[1]["messages"]
    )
    assert [message.role for message in agent.get_history()] == ["user", "assistant"]
    assert agent.get_history()[-1].metadata["tool_calls"][0]["id"] == "call-approval-1-retry"
    assert agent.last_result.paused_loop is not None


def test_tool_calling_agent_feeds_missing_tool_error_back_to_model():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-missing",
                        name="missing_tool",
                        arguments=json.dumps({"text": "x"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="The tool was unavailable.",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
    )

    answer = agent.run("use a missing tool")

    assert answer == "The tool was unavailable."
    tool_message = llm.invoke_with_tools_calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    tool_payload = json.loads(tool_message["content"])
    assert "missing_tool" in tool_payload["text"]
    observation = agent.last_result.tool_observations[0]
    assert observation.response.status.value == "error"
    assert observation.response.error_info["code"] == "NOT_FOUND"


def test_tool_calling_agent_runs_no_tools_finalization_at_max_steps():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="echo",
                        arguments=json.dumps({"text": "again"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="I only confirmed echo: again; the rest is unresolved.",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        max_steps=1,
    )

    answer = agent.run("loop")

    assert answer == "I only confirmed echo: again; the rest is unresolved."
    assert len(llm.invoke_with_tools_calls) == 2
    assert llm.invoke_with_tools_calls[0]["tool_choice"] == "auto"
    assert llm.invoke_with_tools_calls[1]["tool_choice"] == "none"
    assert "工具调用步数已经达到上限" in llm.invoke_with_tools_calls[1]["messages"][-1]["content"]
    assert agent.get_history()[-1].role == "assistant"
    assert agent.last_result.status == "max_steps"


def test_tool_calling_agent_falls_back_if_max_steps_finalization_requests_tool_again():
    echo_tool = EchoTool()
    registry = ToolRegistry()
    registry.register_tool(echo_tool)
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="echo",
                        arguments=json.dumps({"text": "again"}),
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="echo",
                        arguments=json.dumps({"text": "should-not-run"}),
                    )
                ],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=_config(),
        max_steps=1,
    )

    answer = agent.run("loop")

    assert answer == "抱歉，我无法在限定步数内完成这个任务。"
    assert echo_tool.calls == [{"text": "again"}]
    assert len(llm.invoke_with_tools_calls) == 2
    assert llm.invoke_with_tools_calls[1]["tool_choice"] == "none"
    assert agent.last_result.tool_observations[0].response.data == {"seen": "again"}


def test_tool_calling_agent_preflight_compresses_history_before_model_call():
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content="final after compression",
                tool_calls=[],
                model="fake-model",
            )
        ],
        text_response="compressed summary",
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=Config(
            trace_enabled=False,
            session_enabled=False,
            skills_enabled=False,
            subagent_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            context_window=40,
            compression_threshold=0.2,
            min_retain_rounds=1,
            enable_smart_compression=True,
            preflight_compression_enabled=True,
            write_time_compression_enabled=False,
        ),
    )
    for index in range(3):
        agent.history_manager.append(Message(f"old user message {index} " * 8, "user"))
        agent.history_manager.append(Message(f"old assistant message {index} " * 8, "assistant"))

    answer = agent.run("new user message")

    assert answer == "final after compression"
    assert len(llm.invoke_calls) == 1
    assert len(llm.invoke_with_tools_calls) == 1
    model_messages = llm.invoke_with_tools_calls[0]["messages"]
    assert any(
        message["role"] == "system" and "compressed summary" in message["content"]
        for message in model_messages
    )
    history = agent.get_history()
    assert history[0].role == "summary"
    assert "compressed summary" in history[0].content
    archives = getattr(agent, "_conversation_archives")
    assert len(archives) == 1
    assert archives[0]["reason"] == "preflight_compression"
    assert archives[0]["source_message_count"] == 6
    assert len(archives[0]["messages"]) == 6


def test_tool_observation_keeps_structured_response_when_observation_text_is_truncated():
    class LargeTool(Tool):
        def __init__(self):
            super().__init__(name="large", description="Large output")

        def run(self, parameters):
            return ToolResponse.success(
                text="large output",
                data={"payload": "line1\nline2\nline3\nline4"},
            )

        def get_parameters(self):
            return []

    registry = ToolRegistry()
    registry.register_tool(LargeTool())
    llm = FakeLLM(
        tool_responses=[
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-large",
                        name="large",
                        arguments="{}",
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="done",
                tool_calls=[],
                model="fake-model",
            ),
        ]
    )
    agent = ToolCallingAgent(
        name="assistant",
        llm=llm,
        tool_registry=registry,
        config=Config(
            trace_enabled=False,
            session_enabled=False,
            skills_enabled=False,
            subagent_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            tool_output_max_lines=1,
        ),
    )

    answer = agent.run("large")

    assert answer == "done"
    observation = agent.last_result.tool_observations[0]
    assert observation.truncated is True
    assert observation.response.data == {"payload": "line1\nline2\nline3\nline4"}
    assert observation.observation_text != observation.response.to_json()
    assert observation.stats["original_lines"] > observation.stats["kept_lines"]


def test_factory_keeps_react_compatibility_and_adds_tool_calling_type():
    react_agent = create_agent(
        "react",
        name="react",
        llm=FakeLLM(),
        config=_config(),
    )
    tool_calling_agent = create_agent(
        "tool_calling",
        name="tool-calling",
        llm=FakeLLM(),
        tool_registry=ToolRegistry(),
        config=_config(),
    )

    assert react_agent.__class__.__name__ == "ReActAgent"
    assert isinstance(tool_calling_agent, ToolCallingAgent)
