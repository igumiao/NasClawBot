from datetime import datetime, timedelta
from typing import Any

import pytest

from app.agent import runner as agent_runner
from app.agent.runner import NasClawAgentRunner
from hello_agents.checkpoints import ConversationCheckpoint, JSONConversationCheckpointStore
from hello_agents.core.llm_response import LLMResponse, LLMToolResponse, ToolCall
from hello_agents.tools import Gate


class FakeSettings:
    mteam_base_url = "https://mteam.local"
    mteam_api_key = "key"
    qb_base_url = "https://qb.local"
    qb_username = "user"
    qb_password = "pass"
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

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        return {"id": torrent_id, "title": f"Detail for {torrent_id}"}

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        return f"https://mteam.local/download/{torrent_id}"

    def is_download_url_torrent(self, url: str) -> bool:
        return bool(url)


class FakeQBAdapter:
    calls: list[dict[str, Any]] = []

    def __init__(self, base_url: str = "", username: str = "", password: str = "") -> None:
        self.base_url = base_url
        self.username = username
        self.password = password

    def generate_mteam_torrent_name(self, mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        return f"{mteam_id}-{qb_category}.torrent"

    def add_torrent_url(self, *, url: str, category: str, rename: str, tags: list[str], paused: bool) -> dict[str, Any]:
        self.calls.append(
            {
                "url": url,
                "category": category,
                "rename": rename,
                "tags": tags,
                "paused": paused,
            }
        )
        return {"ok": True, "status": "submitted_paused", "qb_hash": "fake-hash"}


class FakeLLM:
    model = "fake-model"
    calls: list[list[dict[str, object]]] = []
    tool_choices: list[str] = []
    invoke_calls: list[list[dict[str, object]]] = []
    responses: list[LLMToolResponse] = []
    text_response = "compressed summary"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
        FakeLLM.calls.append(messages)
        FakeLLM.tool_choices.append(tool_choice)
        return FakeLLM.responses.pop(0)

    def invoke(self, messages, **kwargs):
        FakeLLM.invoke_calls.append(messages)
        return LLMResponse(content=FakeLLM.text_response, model=self.model)


class FailingSummaryLLM(FakeLLM):
    def invoke(self, messages, **kwargs):
        FailingSummaryLLM.invoke_calls.append(messages)
        raise RuntimeError("summary failed")


def test_nasclaw_agent_runner_persists_and_restores_checkpoint(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.invoke_calls = []
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
    assert second.checkpoint.metadata["tool_names"] == ["mteam_search", "qb_add_torrent"]


def test_nasclaw_agent_runner_persists_preflight_compression_archives(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.invoke_calls = []
    FakeLLM.text_response = "旧搜索对话摘要。"
    FakeLLM.responses = [
        LLMToolResponse(
            content="基于摘要继续回答。",
            tool_calls=[],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-compress",
            created_at="2026-06-03T10:00:00",
            saved_at="2026-06-03T10:01:00",
            history=[
                {
                    "role": "user",
                    "content": f"old user {index} " * 20,
                    "timestamp": "2026-06-03T10:00:00",
                    "metadata": {},
                }
                if item == "user"
                else {
                    "role": "assistant",
                    "content": f"old assistant {index} " * 20,
                    "timestamp": "2026-06-03T10:00:00",
                    "metadata": {},
                }
                for index in range(3)
                for item in ("user", "assistant")
            ],
            metadata={},
        )
    )
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        agent_config_overrides={
            "context_window": 40,
            "compression_threshold": 0.2,
            "min_retain_rounds": 1,
        },
    )

    result = runner.run("session-compress", "继续")

    assert result.answer == "基于摘要继续回答。"
    checkpoint = store.load("session-compress")
    assert checkpoint is not None
    assert checkpoint.history[0]["role"] == "summary"
    assert "旧搜索对话摘要。" in checkpoint.history[0]["content"]
    assert len(checkpoint.archives) == 1
    assert checkpoint.archives[0]["source_message_count"] == 6
    assert checkpoint.metadata["archive_count"] == 1


def test_nasclaw_agent_runner_persists_pending_approvals(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.invoke_calls = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-search-approval",
                    name="mteam_search",
                    arguments='{"keyword":"Dune"}',
                )
            ],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        tool_gate=Gate(confirm=[lambda call: call.tool_name == "mteam_search"]),
    )

    result = runner.run("session-approval", "Dune")

    assert result.status == "awaiting_approval"
    assert result.pending_approvals[0]["tool_name"] == "mteam_search"
    assert result.pending_approvals[0]["session_id"] == "session-approval"
    assert result.pending_approvals[0]["expires_at"]
    assert result.pending_approvals[0]["risk"]["level"] == "side_effect"
    assert result.tool_calls[0]["gate_result"] == "ask_user"
    checkpoint = store.load("session-approval")
    assert checkpoint is not None
    assert checkpoint.metadata["last_status"] == "awaiting_approval"
    assert checkpoint.metadata["pending_approvals"] == result.pending_approvals
    assert checkpoint.metadata["paused_loop"]["approval_id"] == result.pending_approvals[0]["approval_id"]
    assert [message["role"] for message in checkpoint.history] == ["user", "assistant"]
    assert result.checkpoint.metadata["pending_approvals"] is not result.pending_approvals


def test_nasclaw_agent_runner_gates_download_tool_by_default(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    FakeQBAdapter.calls = []
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.invoke_calls = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-download",
                    name="qb_add_torrent",
                    arguments='{"torrent_id":"123","qb_category":"movie"}',
                )
            ],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(checkpoint_store=store)

    result = runner.run("session-download", "下载 123")

    assert result.status == "awaiting_approval"
    assert result.pending_approvals[0]["tool_name"] == "qb_add_torrent"
    assert result.pending_approvals[0]["arguments"] == {"torrent_id": "123", "qb_category": "movie"}
    assert result.pending_approvals[0]["session_id"] == "session-download"
    assert result.pending_approvals[0]["expires_at"]
    assert result.pending_approvals[0]["decision"] is None
    assert result.pending_approvals[0]["result"] is None
    assert result.pending_approvals[0]["error"] is None
    assert result.pending_approvals[0]["risk"] == {
        "level": "side_effect",
        "summary": "Submit torrent to qBittorrent in paused state",
    }
    assert result.tool_calls[0]["gate_result"] == "ask_user"
    assert FakeQBAdapter.calls == []
    checkpoint = store.load("session-download")
    assert checkpoint is not None
    assert checkpoint.metadata["paused_loop"]["pending_tool_call"]["id"] == "call-download"
    assert [message["role"] for message in checkpoint.history] == ["user", "assistant"]


def test_nasclaw_agent_runner_rejects_new_message_while_approval_pending(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-pending",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[
                {"role": "user", "content": "下载 123", "timestamp": "2026-06-04T10:00:00", "metadata": {}},
                {"role": "assistant", "content": "", "timestamp": "2026-06-04T10:01:00", "metadata": {"tool_calls": []}},
            ],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "pending",
                    }
                ],
            },
        )
    )
    runner = NasClawAgentRunner(checkpoint_store=store)

    result = runner.run("session-pending", "继续搜索")

    assert result.status == "awaiting_approval"
    assert result.pending_approvals[0]["approval_id"] == "approval-1"
    checkpoint = store.load("session-pending")
    assert checkpoint is not None
    assert [message["content"] for message in checkpoint.history if message["role"] == "user"] == ["下载 123"]


def test_nasclaw_agent_runner_approve_resumes_provider_tool_call_loop(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.invoke_calls = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-download",
                    name="qb_add_torrent",
                    arguments='{"torrent_id":"123","qb_category":"movie"}',
                )
            ],
            model="fake-model",
        ),
        LLMToolResponse(
            content="已提交到 qBittorrent，任务保持暂停。",
            tool_calls=[],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FakeLLM,
    )
    pending = runner.run("session-resume-approve", "下载 123")

    result = runner.approve("session-resume-approve", pending.pending_approvals[0]["approval_id"])

    assert result.status == "approved"
    assert result.message == "已提交到 qBittorrent，任务保持暂停。"
    assert result.receipt is not None
    assert FakeQBAdapter.calls[0]["paused"] is True
    assert FakeLLM.tool_choices == ["auto", "none"]
    assert FakeLLM.invoke_calls == []
    resume_messages = FakeLLM.calls[-1]
    assert resume_messages[-1]["role"] == "tool"
    assert resume_messages[-1]["tool_call_id"] == "call-download"
    checkpoint = store.load("session-resume-approve")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert "paused_loop" not in checkpoint.metadata
    assert checkpoint.metadata["approvals"][0]["status"] == "approved"
    assert [message["role"] for message in checkpoint.history] == ["user", "assistant", "tool", "assistant"]


def test_nasclaw_agent_runner_approve_rejects_mismatched_paused_loop_without_qb_execution(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-download",
                    name="qb_add_torrent",
                    arguments='{"torrent_id":"123","qb_category":"movie"}',
                )
            ],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FakeLLM,
    )
    pending = runner.run("session-mismatch-approve", "下载 123")
    approval_id = pending.pending_approvals[0]["approval_id"]
    checkpoint = store.load("session-mismatch-approve")
    assert checkpoint is not None
    checkpoint.metadata["paused_loop"]["pending_tool_call"]["id"] = "call-other"
    store.save(checkpoint)

    with pytest.raises(ValueError, match="tool_call_id"):
        runner.approve("session-mismatch-approve", approval_id)

    assert FakeQBAdapter.calls == []
    assert FakeLLM.tool_choices == ["auto"]
    checkpoint = store.load("session-mismatch-approve")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"][0]["approval_id"] == approval_id
    assert "approvals" not in checkpoint.metadata
    assert [message["role"] for message in checkpoint.history] == ["user", "assistant"]


def test_nasclaw_agent_runner_deny_resumes_with_user_denied_tool_result(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-download",
                    name="qb_add_torrent",
                    arguments='{"torrent_id":"123","qb_category":"movie"}',
                )
            ],
            model="fake-model",
        ),
        LLMToolResponse(
            content="已取消这次下载请求。",
            tool_calls=[],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FakeLLM,
    )
    pending = runner.run("session-resume-deny", "下载 123")

    result = runner.deny("session-resume-deny", pending.pending_approvals[0]["approval_id"])

    assert result.status == "denied"
    assert result.message == "已取消这次下载请求。"
    assert FakeQBAdapter.calls == []
    assert FakeLLM.tool_choices == ["auto", "none"]
    tool_payload = FakeLLM.calls[-1][-1]["content"]
    assert "USER_DENIED" in tool_payload
    checkpoint = store.load("session-resume-deny")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert "paused_loop" not in checkpoint.metadata
    assert checkpoint.metadata["approvals"][0]["status"] == "denied"


def test_nasclaw_agent_runner_deny_rejects_mismatched_paused_loop_without_resume(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FakeLLM.calls = []
    FakeLLM.tool_choices = []
    FakeLLM.responses = [
        LLMToolResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="call-download",
                    name="qb_add_torrent",
                    arguments='{"torrent_id":"123","qb_category":"movie"}',
                )
            ],
            model="fake-model",
        ),
    ]
    store = JSONConversationCheckpointStore(tmp_path)
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FakeLLM,
    )
    pending = runner.run("session-mismatch-deny", "下载 123")
    approval_id = pending.pending_approvals[0]["approval_id"]
    checkpoint = store.load("session-mismatch-deny")
    assert checkpoint is not None
    checkpoint.metadata["paused_loop"]["pending_tool_call"]["arguments"] = {"torrent_id": "999", "qb_category": "movie"}
    store.save(checkpoint)

    with pytest.raises(ValueError, match="arguments"):
        runner.deny("session-mismatch-deny", approval_id)

    assert FakeQBAdapter.calls == []
    assert FakeLLM.tool_choices == ["auto"]
    checkpoint = store.load("session-mismatch-deny")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"][0]["approval_id"] == approval_id
    assert "approvals" not in checkpoint.metadata
    assert [message["role"] for message in checkpoint.history] == ["user", "assistant"]


def test_nasclaw_agent_runner_approve_executes_pending_download(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FakeLLM.invoke_calls = []
    FakeLLM.text_response = "已为你提交到 qBittorrent，任务当前保持暂停。"
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-approve",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[
                {"role": "user", "content": "下载 123", "timestamp": "2026-06-04T10:00:00", "metadata": {}},
                {
                    "role": "assistant",
                    "content": "工具调用需要用户确认后才能执行: qb_add_torrent",
                    "timestamp": "2026-06-04T10:01:00",
                    "metadata": {},
                },
            ],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "pending",
                        "reason": "Tool call requires user approval.",
                        "created_at": "2026-06-04T10:01:00",
                    }
                ],
            },
        )
    )
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FakeLLM,
    )

    result = runner.approve("session-approve", "approval-1")

    assert result.status == "approved"
    assert result.message == "已为你提交到 qBittorrent，任务当前保持暂停。"
    assert result.receipt is not None
    assert result.receipt["external_id"] == "123"
    assert FakeQBAdapter.calls[0]["paused"] is True
    assert len(FakeLLM.invoke_calls) == 1
    summary_payload = FakeLLM.invoke_calls[0][1]["content"]
    assert "qb_add_torrent" in summary_payload
    assert "https://mteam.local/download" not in summary_payload
    checkpoint = store.load("session-approve")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["status"] == "approved"
    assert checkpoint.metadata["approvals"][0]["decision"] == {"action": "approve"}
    assert checkpoint.metadata["approvals"][0]["result"]["status"] == "success"
    assert checkpoint.metadata["approvals"][0]["error"] is None
    assert checkpoint.history[-1]["role"] == "assistant"
    assert checkpoint.history[-1]["content"] == "已为你提交到 qBittorrent，任务当前保持暂停。"


def test_nasclaw_agent_runner_approve_falls_back_when_summary_fails(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    FailingSummaryLLM.invoke_calls = []
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-fallback",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "pending",
                    }
                ],
            },
        )
    )
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
        llm_factory=FailingSummaryLLM,
    )

    result = runner.approve("session-fallback", "approval-1")

    assert result.status == "approved"
    assert "下载请求已提交到 qBittorrent" in result.message
    assert result.receipt is not None
    assert len(FailingSummaryLLM.invoke_calls) == 1


def test_nasclaw_agent_runner_deny_does_not_execute_pending_download(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-deny",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "pending",
                    }
                ],
            },
        )
    )
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
    )

    result = runner.deny("session-deny", "approval-1")

    assert result.status == "denied"
    assert FakeQBAdapter.calls == []
    checkpoint = store.load("session-deny")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["status"] == "denied"
    assert checkpoint.metadata["approvals"][0]["decision"] == {"action": "deny"}
    assert checkpoint.history[-1]["content"] == "已取消这次下载请求。"


def test_nasclaw_agent_runner_rejects_expired_approval_without_executing_tool(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    FakeQBAdapter.calls = []
    now = datetime.now()
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-expired",
            created_at=now.isoformat(),
            saved_at=now.isoformat(),
            history=[],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-expired",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "pending",
                        "created_at": (now - timedelta(hours=1)).isoformat(),
                        "expires_at": (now - timedelta(minutes=1)).isoformat(),
                    }
                ],
            },
        )
    )
    runner = NasClawAgentRunner(
        checkpoint_store=store,
        mteam_adapter_factory=FakeMTeamAdapter,
        qb_adapter_factory=FakeQBAdapter,
    )

    with pytest.raises(ValueError, match="expired"):
        runner.approve("session-expired", "approval-expired")

    assert FakeQBAdapter.calls == []
    checkpoint = store.load("session-expired")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["status"] == "expired"
    assert checkpoint.metadata["approvals"][0]["decision"] is None
    assert checkpoint.metadata["approvals"][0]["decided_at"] is None
    assert checkpoint.metadata["approvals"][0]["expired_at"]
    assert checkpoint.history[-1]["content"] == "这次下载确认已过期，请重新发起下载请求。"
