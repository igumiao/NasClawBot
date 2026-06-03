import json

from hello_agents.agents import ToolCallingAgent, create_agent
from hello_agents.core.config import Config
from hello_agents.core.llm_response import LLMResponse, LLMToolResponse, ToolCall
from hello_agents.tools import Tool, ToolParameter, ToolRegistry, ToolResponse


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
