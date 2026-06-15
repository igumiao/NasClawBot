from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agent import runner as agent_runner
from app.agent.runner import _reset_module_qb_adapter
from app.api import chat_routes, qb_routes
from app.api.schemas import AgentApprovalDecisionRequest, ChatRequest, DownloadRequest, QBTorrentActionRequest
from app.domain.authorization import DownloadAuthorizationPolicy, create_session_grant
from app.main import create_app
from app.services.download_authorization_store import DownloadAuthorizationPolicyStore
from hello_agents.checkpoints import ConversationCheckpoint, JSONConversationCheckpointStore
from hello_agents.core.llm_response import LLMResponse, LLMToolResponse, ToolCall


def _route_for(app, path: str, method: str):
    target_method = method.upper()
    for route in app.router.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", set())
        if target_method in methods:
            return route
    raise AssertionError(f"Route not found for {method} {path}")


class FakeSettings:
    mteam_base_url = "https://mteam.local"
    mteam_api_key = "key"
    qb_base_url = "https://qb.local"
    qb_username = "user"
    qb_password = "pass"
    llm_model = "fake-model"
    llm_api_key = "fake-key"
    llm_base_url = "https://llm.local"
    app_timezone = "Asia/Shanghai"
    tmdb_api_key = ""
    tavily_api_key = ""


class FakeMTeamAdapter:
    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        self.base_url = base_url
        self.api_key = api_key

    def search_torrents_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        _ = page
        _ = page_size
        _ = kwargs
        return [
            {"id": 123, "title": f"{keyword} 2160p", "seeders": 10, "size": "10 GiB", "size_bytes": 10737418240},
            {"id": 456, "title": f"{keyword} 1080p", "seeders": 5, "size": "8 GiB", "size_bytes": 8589934592},
        ]

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        return {"title": f"Detail for {torrent_id}", "id": torrent_id}

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        return f"https://mteam.local/download/{torrent_id}"

    def is_download_url_torrent(self, url: str) -> bool:
        return bool(url)


class FakeQBAdapter:
    def __init__(self, base_url: str = "", username: str = "", password: str = "") -> None:
        self.base_url = base_url
        self.username = username
        self.password = password

    def add_torrent_url(self, *, url: str, category: str, rename: str, tags: list[str], paused: bool, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        assert paused is True
        return {"ok": True, "status": "submitted_paused", "qb_hash": "fake-hash"}

    def generate_mteam_torrent_name(self, mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        return f"{mteam_id}.torrent"


class FakeApprovalLLM:
    model = "fake-model"
    invoke_calls: list[list[dict[str, object]]] = []
    text_response = "已提交到 qBittorrent，任务保持暂停。"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def invoke(self, messages, **kwargs):
        FakeApprovalLLM.invoke_calls.append(messages)
        return LLMResponse(content=self.text_response, model=self.model)


@pytest.fixture(autouse=True)
def _reset_qb_adapter_before_each_test_in_chat():
    """Ensure the module-level qB adapter cache does not leak between tests."""
    _reset_module_qb_adapter()
    yield
    _reset_module_qb_adapter()


def _patch_chat_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_routes, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(chat_routes, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(chat_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(agent_runner, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeApprovalLLM)


def test_health_endpoint_returns_ok():
    response = _route_for(create_app(), "/health", "GET").endpoint()
    assert response["status"] == "ok"


def test_index_page_is_served():
    response = _route_for(create_app(), "/", "GET").endpoint()
    assert "<html" in response.lower() or "<!doctype html" in response.lower()


def test_download_authorization_settings_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_routes, "_SETTINGS_DIR", tmp_path)
    app = create_app()
    get_endpoint = _route_for(app, "/settings/download-authorization", "GET").endpoint
    put_endpoint = _route_for(app, "/settings/download-authorization", "PUT").endpoint

    initial = get_endpoint()
    assert initial.enabled is False
    assert initial.paused_required is True

    saved = put_endpoint(
        DownloadAuthorizationPolicy(
            enabled=True,
            categories=["电视剧"],
            save_path_prefixes=["/downloads/tv"],
            max_items_per_batch=4,
            max_total_items_per_session=12,
        )
    )

    assert saved.enabled is True
    assert saved.categories == ["电视剧"]
    assert get_endpoint().save_path_prefixes == ["/downloads/tv"]


def test_chat_agent_endpoint_uses_readonly_agent_and_persists_session(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)

    class FakeLLM:
        model = "fake-model"
        calls: list[list[dict[str, object]]] = []
        responses = [
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
                content="找到 Dune 2160p 和 Dune 1080p。",
                tool_calls=[],
                model="fake-model",
            ),
            LLMToolResponse(
                content="上一轮结果包括 Dune 2160p 和 Dune 1080p。",
                tool_calls=[],
                model="fake-model",
            ),
        ]

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            FakeLLM.calls.append(messages)
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)

    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    first = endpoint(ChatRequest(session_id="agent-session-1", message="Dune"))

    assert first.status == "completed"
    assert first.message == "找到 Dune 2160p 和 Dune 1080p。"
    assert first.results[0].title == "Dune 2160p"
    assert first.tool_calls[0]["tool"] == "mteam_search"
    assert first.tool_calls[0]["status"] == "success"
    assert first.tool_calls[0]["truncated"] is False
    assert first.pending_approvals == []
    assert (tmp_path / "agent-session-1.json").exists()

    second = endpoint(ChatRequest(session_id="agent-session-1", message="上一轮有哪些结果？"))

    assert second.status == "completed"
    assert second.message == "上一轮结果包括 Dune 2160p 和 Dune 1080p。"
    assert len(FakeLLM.calls) == 3
    assert any(message["role"] == "tool" for message in FakeLLM.calls[-1])


def test_chat_agent_endpoint_returns_download_pending_approval(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)

    class FakeLLM:
        model = "fake-model"
        tools_seen: list[list[str]] = []
        responses = [
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

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            FakeLLM.tools_seen.append([tool["function"]["name"] for tool in tools])
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    body = endpoint(ChatRequest(session_id="agent-download", message="下载 123"))

    assert body.status == "awaiting_approval"
    assert body.pending_approvals[0]["tool_name"] == "qb_add_torrent"
    assert body.pending_approvals[0]["arguments"] == {"torrent_id": "123", "qb_category": "movie"}
    assert body.tool_calls[0]["gate_result"] == "ask_user"
    assert "qb_add_torrent" in FakeLLM.tools_seen[0]
    checkpoint = JSONConversationCheckpointStore(tmp_path).load("agent-download")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == body.pending_approvals


def test_chat_agent_batch_approval_includes_session_authorization_eligibility(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setattr(chat_routes, "_SETTINGS_DIR", tmp_path / "settings")
    monkeypatch.setattr(agent_runner, "_SETTINGS_DIR", tmp_path / "settings")
    DownloadAuthorizationPolicyStore(tmp_path / "settings").save(
        DownloadAuthorizationPolicy(
            enabled=True,
            categories=["电视剧"],
            save_path_prefixes=["/downloads/tv"],
            max_items_per_batch=10,
            max_total_items_per_session=20,
        )
    )

    class FakeLLM:
        model = "fake-model"
        responses = [
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-batch-download",
                        name="qb_add_torrents",
                        arguments=(
                            '{"items":['
                            '{"torrent_id":"101","qb_category":"电视剧","save_path":"/downloads/tv/show"},'
                            '{"torrent_id":"102","qb_category":"电视剧","save_path":"/downloads/tv/show"}'
                            ']}'
                        ),
                    )
                ],
                model="fake-model",
            ),
        ]

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    body = endpoint(ChatRequest(session_id="agent-batch-auth", message="下载两集"))

    assert body.status == "awaiting_approval"
    approval = body.pending_approvals[0]
    assert approval["tool_name"] == "qb_add_torrents"
    assert approval["authorization"]["eligible"] is True
    assert approval["authorization"]["policy_id"] == "download-add-torrents-v1"


def test_chat_agent_single_approval_includes_session_authorization_eligibility(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setattr(chat_routes, "_SETTINGS_DIR", tmp_path / "settings")
    monkeypatch.setattr(agent_runner, "_SETTINGS_DIR", tmp_path / "settings")
    DownloadAuthorizationPolicyStore(tmp_path / "settings").save(
        DownloadAuthorizationPolicy(
            enabled=True,
            categories=["电视剧"],
            save_path_prefixes=["/downloads/tv"],
            max_items_per_batch=10,
            max_total_items_per_session=20,
        )
    )

    class FakeLLM:
        model = "fake-model"
        responses = [
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-single-download",
                        name="qb_add_torrent",
                        arguments='{"torrent_id":"101","qb_category":"电视剧","save_path":"/downloads/tv/show"}',
                    )
                ],
                model="fake-model",
            ),
        ]

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    body = endpoint(ChatRequest(session_id="agent-single-auth", message="下载一集"))

    assert body.status == "awaiting_approval"
    approval = body.pending_approvals[0]
    assert approval["tool_name"] == "qb_add_torrent"
    assert approval["authorization"]["eligible"] is True
    assert approval["authorization"]["item_count"] == 1


def test_chat_agent_session_grant_auto_authorizes_batch_download(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    session_dir = tmp_path / "sessions"
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", session_dir)
    monkeypatch.setattr(chat_routes, "_SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(agent_runner, "_SETTINGS_DIR", settings_dir)
    policy = DownloadAuthorizationPolicy(
        enabled=True,
        categories=["电视剧"],
        save_path_prefixes=["/downloads/tv"],
        max_items_per_batch=10,
        max_total_items_per_session=20,
    )
    DownloadAuthorizationPolicyStore(settings_dir).save(policy)
    args = {
        "items": [
            {"torrent_id": "101", "qb_category": "电视剧", "save_path": "/downloads/tv/show"},
            {"torrent_id": "102", "qb_category": "电视剧", "save_path": "/downloads/tv/show"},
        ]
    }
    grant = create_session_grant(policy, "qb_add_torrents", args)
    store = JSONConversationCheckpointStore(session_dir)
    store.save(
        ConversationCheckpoint(
            session_id="agent-auto-grant",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={"authorization_grants": [grant]},
        )
    )

    class FakeLLM:
        model = "fake-model"
        responses = [
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-auto-download",
                        name="qb_add_torrents",
                        arguments='{"items":[{"torrent_id":"101","qb_category":"电视剧","save_path":"/downloads/tv/show"},{"torrent_id":"102","qb_category":"电视剧","save_path":"/downloads/tv/show"}]}',
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="已自动提交到 qBittorrent，任务保持暂停。",
                tool_calls=[],
                model="fake-model",
            ),
        ]

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    body = endpoint(ChatRequest(session_id="agent-auto-grant", message="继续下载"))

    assert body.status == "completed"
    assert body.pending_approvals == []
    assert body.tool_calls[0]["tool"] == "qb_add_torrents"
    assert body.tool_calls[0]["gate_result"] == "allow"
    checkpoint = store.load("agent-auto-grant")
    assert checkpoint is not None
    assert checkpoint.metadata["authorization_grants"][0]["used_total_items"] == 2


def test_chat_agent_session_grant_auto_authorizes_single_download(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    session_dir = tmp_path / "sessions"
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", session_dir)
    monkeypatch.setattr(chat_routes, "_SETTINGS_DIR", settings_dir)
    monkeypatch.setattr(agent_runner, "_SETTINGS_DIR", settings_dir)
    policy = DownloadAuthorizationPolicy(
        enabled=True,
        categories=["电视剧"],
        save_path_prefixes=["/downloads/tv"],
        max_items_per_batch=10,
        max_total_items_per_session=20,
    )
    DownloadAuthorizationPolicyStore(settings_dir).save(policy)
    grant = create_session_grant(
        policy,
        "qb_add_torrent",
        {"torrent_id": "101", "qb_category": "电视剧", "save_path": "/downloads/tv/show"},
    )
    store = JSONConversationCheckpointStore(session_dir)
    store.save(
        ConversationCheckpoint(
            session_id="agent-single-auto-grant",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={"authorization_grants": [grant]},
        )
    )

    class FakeLLM:
        model = "fake-model"
        responses = [
            LLMToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call-auto-single-download",
                        name="qb_add_torrent",
                        arguments='{"torrent_id":"101","qb_category":"电视剧","save_path":"/downloads/tv/show"}',
                    )
                ],
                model="fake-model",
            ),
            LLMToolResponse(
                content="已自动提交到 qBittorrent，任务保持暂停。",
                tool_calls=[],
                model="fake-model",
            ),
        ]

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def invoke_with_tools(self, messages, tools, tool_choice="auto", **kwargs):
            return FakeLLM.responses.pop(0)

    monkeypatch.setattr(agent_runner, "HelloAgentsLLM", FakeLLM)
    endpoint = _route_for(create_app(), "/chat/agent", "POST").endpoint

    body = endpoint(ChatRequest(session_id="agent-single-auto-grant", message="继续下载"))

    assert body.status == "completed"
    assert body.pending_approvals == []
    assert body.tool_calls[0]["tool"] == "qb_add_torrent"
    assert body.tool_calls[0]["gate_result"] == "allow"
    checkpoint = store.load("agent-single-auto-grant")
    assert checkpoint is not None
    assert checkpoint.metadata["authorization_grants"][0]["used_total_items"] == 1


def test_list_agent_sessions_returns_checkpoint_summaries(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="older",
            created_at="2026-06-03T09:00:00",
            saved_at="2026-06-03T09:01:00",
            history=[
                {"role": "user", "content": "old", "timestamp": "2026-06-03T09:00:00", "metadata": {}},
            ],
            metadata={"turn_count": 1},
        )
    )
    store.save(
        ConversationCheckpoint(
            session_id="newer",
            created_at="2026-06-03T10:00:00",
            saved_at="2026-06-03T10:01:00",
            history=[
                {"role": "user", "content": "new", "timestamp": "2026-06-03T10:00:00", "metadata": {}},
                {"role": "assistant", "content": "answer", "timestamp": "2026-06-03T10:01:00", "metadata": {}},
            ],
            archives=[
                {
                    "id": "archive-1",
                    "created_at": "2026-06-03T10:00:30",
                    "reason": "preflight_compression",
                    "messages": [],
                }
            ],
            metadata={"turn_count": 1},
        )
    )

    endpoint = _route_for(create_app(), "/chat/agent/sessions", "GET").endpoint
    body = endpoint()

    assert [session.session_id for session in body.sessions] == ["newer", "older"]
    assert body.sessions[0].message_count == 2
    assert body.sessions[0].archive_count == 1
    assert body.sessions[0].metadata["turn_count"] == 1


def test_get_agent_session_returns_checkpoint_messages(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="session-1",
            created_at="2026-06-03T10:00:00",
            saved_at="2026-06-03T10:01:00",
            history=[
                {"role": "user", "content": "Dune", "timestamp": "2026-06-03T10:00:00", "metadata": {}},
                {
                    "role": "assistant",
                    "content": "找到 Dune。",
                    "timestamp": "2026-06-03T10:01:00",
                    "metadata": {},
                },
            ],
            archives=[
                {
                    "id": "archive-1",
                    "created_at": "2026-06-03T10:00:30",
                    "reason": "preflight_compression",
                    "messages": [
                        {"role": "user", "content": "old", "timestamp": "2026-06-03T09:00:00", "metadata": {}},
                    ],
                }
            ],
            metadata={"agent_name": "nasclawbot-agent"},
        )
    )

    endpoint = _route_for(create_app(), "/chat/agent/sessions/{session_id}", "GET").endpoint
    body = endpoint("session-1")

    assert body.session_id == "session-1"
    assert body.messages[0]["role"] == "user"
    assert body.messages[0]["content"] == "Dune"
    assert body.archives[0]["id"] == "archive-1"
    assert body.metadata["agent_name"] == "nasclawbot-agent"


def test_get_agent_session_returns_404_when_missing(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    endpoint = _route_for(create_app(), "/chat/agent/sessions/{session_id}", "GET").endpoint

    with pytest.raises(HTTPException) as excinfo:
        endpoint("missing")

    assert excinfo.value.status_code == 404


def test_approve_agent_approval_executes_download_and_updates_checkpoint(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    FakeApprovalLLM.invoke_calls = []
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="agent-approve",
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

    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve",
        "POST",
    ).endpoint
    body = endpoint("agent-approve", "approval-1")

    assert body.status == "approved"
    assert body.message == "已提交到 qBittorrent，任务保持暂停。"
    assert body.receipt is not None
    assert body.receipt["external_id"] == "123"
    assert len(FakeApprovalLLM.invoke_calls) == 1
    checkpoint = store.load("agent-approve")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["status"] == "approved"
    assert checkpoint.history[-1]["content"] == "已提交到 qBittorrent，任务保持暂停。"


def test_approve_agent_batch_approval_executes_downloads(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    FakeApprovalLLM.invoke_calls = []
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="agent-batch-approve",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrents",
                        "arguments": {
                            "items": [
                                {"torrent_id": "101", "qb_category": "电视剧"},
                                {"torrent_id": "102", "qb_category": "电视剧"},
                            ]
                        },
                        "status": "pending",
                    }
                ],
            },
        )
    )

    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve",
        "POST",
    ).endpoint
    body = endpoint("agent-batch-approve", "approval-1")

    assert body.status == "approved"
    assert body.receipt is not None
    assert body.receipt["type"] == "batch"
    assert body.receipt["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    checkpoint = store.load("agent-batch-approve")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["tool_name"] == "qb_add_torrents"


def test_approve_agent_batch_approval_can_create_session_grant(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    session_dir = tmp_path / "sessions"
    settings_dir = tmp_path / "settings"
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", session_dir)
    monkeypatch.setattr(agent_runner, "_SETTINGS_DIR", settings_dir)
    DownloadAuthorizationPolicyStore(settings_dir).save(
        DownloadAuthorizationPolicy(
            enabled=True,
            categories=["电视剧"],
            save_path_prefixes=["/downloads/tv"],
            max_items_per_batch=10,
            max_total_items_per_session=20,
        )
    )
    store = JSONConversationCheckpointStore(session_dir)
    store.save(
        ConversationCheckpoint(
            session_id="agent-batch-grant",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "last_status": "awaiting_approval",
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-download",
                        "tool_name": "qb_add_torrents",
                        "arguments": {
                            "items": [
                                {"torrent_id": "101", "qb_category": "电视剧", "save_path": "/downloads/tv/show"},
                                {"torrent_id": "102", "qb_category": "电视剧", "save_path": "/downloads/tv/show"},
                            ]
                        },
                        "status": "pending",
                    }
                ],
            },
        )
    )

    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve",
        "POST",
    ).endpoint
    body = endpoint("agent-batch-grant", "approval-1", AgentApprovalDecisionRequest(decision="approve_and_grant_session"))

    assert body.status == "approved"
    checkpoint = store.load("agent-batch-grant")
    assert checkpoint is not None
    grant = checkpoint.metadata["authorization_grants"][0]
    assert grant["tool_name"] == "download_add"
    assert grant["used_total_items"] == 2


def test_approve_agent_grant_rejects_non_policy_tool(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    JSONConversationCheckpointStore(tmp_path).save(
        ConversationCheckpoint(
            session_id="agent-grant-reject",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "pending_approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_call_id": "call-speed",
                        "tool_name": "qb_set_global_speed",
                        "arguments": {"download_limit": 1024},
                        "status": "pending",
                    }
                ],
            },
        )
    )
    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve",
        "POST",
    ).endpoint

    with pytest.raises(HTTPException) as excinfo:
        endpoint("agent-grant-reject", "approval-1", AgentApprovalDecisionRequest(decision="approve_and_grant_session"))

    assert excinfo.value.status_code == 409


def test_deny_agent_approval_does_not_execute_download(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    store = JSONConversationCheckpointStore(tmp_path)
    store.save(
        ConversationCheckpoint(
            session_id="agent-deny",
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

    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/deny",
        "POST",
    ).endpoint
    body = endpoint("agent-deny", "approval-1")

    assert body.status == "denied"
    assert body.receipt is None
    checkpoint = store.load("agent-deny")
    assert checkpoint is not None
    assert checkpoint.metadata["pending_approvals"] == []
    assert checkpoint.metadata["approvals"][0]["status"] == "denied"
    assert checkpoint.history[-1]["content"] == "已取消这次下载请求。"


def test_approve_agent_approval_rejects_repeated_decision(tmp_path, monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    monkeypatch.setattr(chat_routes, "_AGENT_SESSION_DIR", tmp_path)
    JSONConversationCheckpointStore(tmp_path).save(
        ConversationCheckpoint(
            session_id="agent-repeat",
            created_at="2026-06-04T10:00:00",
            saved_at="2026-06-04T10:01:00",
            history=[],
            metadata={
                "pending_approvals": [],
                "approvals": [
                    {
                        "approval_id": "approval-1",
                        "tool_name": "qb_add_torrent",
                        "arguments": {"torrent_id": "123", "qb_category": "movie"},
                        "status": "approved",
                    }
                ],
            },
        )
    )

    endpoint = _route_for(
        create_app(),
        "/chat/agent/sessions/{session_id}/approvals/{approval_id}/approve",
        "POST",
    ).endpoint
    with pytest.raises(HTTPException) as excinfo:
        endpoint("agent-repeat", "approval-1")

    assert excinfo.value.status_code == 409


def test_download_endpoint_adds_paused_qb_task(monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    endpoint = _route_for(create_app(), "/download", "POST").endpoint

    body = endpoint(DownloadRequest(torrent_id="123"))

    assert body.status == "completed"
    assert body.receipt is not None
    assert body.receipt["external_id"] == "123"
    assert body.receipt["status"] == "submitted_paused"


def test_list_qb_torrents_endpoint_returns_adapter_rows(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class ListQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            captured["init"] = (base_url, username, password)

        def list_torrents(self, **kwargs):
            captured["list_kwargs"] = kwargs
            return [
                {
                    "hash": "abc123",
                    "name": "Dune Part Two",
                    "category": "movie",
                    "tags": ["mteam"],
                    "state": "downloading",
                    "progress": 0.42,
                    "download_speed": 1024,
                    "upload_speed": 128,
                    "eta": 3600,
                    "save_path": "/downloads/movie",
                    "size": 123456,
                    "total_size": 654321,
                }
            ]

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", ListQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    endpoint = _route_for(create_app(), "/qb/torrents", "GET").endpoint
    body = endpoint(category="movie", tag="mteam", limit=10)
    assert captured["init"] == ("https://qb.local", "user", "pass")
    assert captured["list_kwargs"] == {
        "category": "movie",
        "tag": "mteam",
        "limit": 10,
        "status_filter": None,
        "sort": None,
        "reverse": None,
    }
    assert body.items[0].hash == "abc123"


def test_get_qb_torrent_endpoint_returns_not_found_when_missing(monkeypatch: pytest.MonkeyPatch):
    class MissingQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def get_torrent(self, torrent_hash: str):
            assert torrent_hash == "missing"
            return None

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", MissingQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    endpoint = _route_for(create_app(), "/qb/torrents/{torrent_hash}", "GET").endpoint
    with pytest.raises(HTTPException) as excinfo:
        endpoint("missing")
    assert excinfo.value.status_code == 404


def test_qb_torrent_action_endpoint_dispatches_control(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class ControlQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def control_torrent(self, torrent_hash: str, *, action: str, delete_files: bool = False):
            captured["control"] = {
                "torrent_hash": torrent_hash,
                "action": action,
                "delete_files": delete_files,
            }
            return {"ok": True, "status": "pause", "qb_hash": torrent_hash}

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", ControlQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    endpoint = _route_for(create_app(), "/qb/torrents/{torrent_hash}/actions", "POST").endpoint
    response = endpoint("abc123", QBTorrentActionRequest(action="pause"))
    assert captured["control"] == {
        "torrent_hash": "abc123",
        "action": "pause",
        "delete_files": False,
    }
    assert response.status == "pause"


def test_qb_torrent_action_endpoint_rejects_invalid_action():
    with pytest.raises(ValidationError):
        QBTorrentActionRequest(action="start-now")
