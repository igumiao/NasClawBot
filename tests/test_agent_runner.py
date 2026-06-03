from typing import Any

import pytest

from app.agent import runner as agent_runner
from app.agent.runner import NasClawAgentRunner
from hello_agents.checkpoints import JSONConversationCheckpointStore
from hello_agents.core.llm_response import LLMToolResponse, ToolCall


class FakeSettings:
    mteam_base_url = "https://mteam.local"
    mteam_api_key = "key"
    llm_model = "fake-model"
    llm_api_key = "fake-key"
    llm_base_url = "https://llm.local"


class FakeMTeamAdapter:
    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        self.base_url = base_url
        self.api_key = api_key

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        return [
            {"id": 123, "title": f"{keyword} 2160p", "seeders": 10, "size": "10 GiB", "size_bytes": 10737418240},
        ]


class FakeLLM:
    model = "fake-model"
    calls: list[list[dict[str, object]]] = []
    responses: list[LLMToolResponse] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
        FakeLLM.calls.append(messages)
        return FakeLLM.responses.pop(0)


def test_nasclaw_agent_runner_persists_and_restores_checkpoint(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    FakeLLM.calls = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-search",
                    name="mteam_search",
                    arguments='{"keyword":"Dune"}',
                )
            ],
            model="fake-model",
        ),
        LLMToolResponse(
            content="找到 Dune 2160p。",
            tool_calls=[],
            model="fake-model",
        ),
        LLMToolResponse(
            content="上一轮结果是 Dune 2160p。",
            tool_calls=[],
            model="fake-model",
        ),
    ]

    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(checkpoint_store=store)

    first = runner.run("session-1", "Dune")

    assert first.answer == "找到 Dune 2160p。"
    assert first.results[0].title == "Dune 2160p"
    checkpoint = store.load("session-1")
    assert checkpoint is not None
    assert checkpoint.session_id == "session-1"
    assert checkpoint.metadata["turn_count"] == 1
    assert [message["role"] for message in checkpoint.history] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]

    second = runner.run("session-1", "上一轮有哪些结果？")

    assert second.answer == "上一轮结果是 Dune 2160p。"
    assert len(FakeLLM.calls) == 3
    assert any(message["role"] == "tool" for message in FakeLLM.calls[-1])
    assert second.checkpoint.metadata["turn_count"] == 2
