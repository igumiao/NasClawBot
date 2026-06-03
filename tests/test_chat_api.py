from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agent import runner as agent_runner
from app.api import chat_routes, qb_routes
from app.api.schemas import ChatRequest, DownloadRequest, QBTorrentActionRequest
from app.main import create_app
from hello_agents.core.llm_response import LLMToolResponse, ToolCall


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


class FakeMTeamAdapter:
    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        self.base_url = base_url
        self.api_key = api_key

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
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

    def add_torrent_url(self, *, url: str, category: str, rename: str, tags: list[str], paused: bool) -> dict[str, Any]:
        assert paused is True
        return {"ok": True, "status": "submitted_paused", "qb_hash": "fake-hash"}

    def generate_mteam_torrent_name(self, mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        return f"{mteam_id}.torrent"


def _patch_chat_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_routes, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(chat_routes, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(chat_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(agent_runner, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(agent_runner, "MTeamAdapter", FakeMTeamAdapter)


def test_health_endpoint_returns_ok():
    response = _route_for(create_app(), "/health", "GET").endpoint()
    assert response["status"] == "ok"


def test_index_page_is_served():
    response = _route_for(create_app(), "/", "GET").endpoint()
    assert "<html" in response.lower() or "<!doctype html" in response.lower()


def test_chat_endpoint_returns_search_results(monkeypatch: pytest.MonkeyPatch):
    _patch_chat_adapters(monkeypatch)
    endpoint = _route_for(create_app(), "/chat", "POST").endpoint

    body = endpoint(ChatRequest(session_id="s1", message="Dune"))

    assert body.status == "completed"
    assert body.message == "找到 2 个搜索结果。"
    assert body.results[0].id == "123"
    assert body.results[0].title == "Dune 2160p"
    assert body.tool_calls[0]["tool"] == "mteam_search"


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
    assert (tmp_path / "agent-session-1.json").exists()

    second = endpoint(ChatRequest(session_id="agent-session-1", message="上一轮有哪些结果？"))

    assert second.status == "completed"
    assert second.message == "上一轮结果包括 Dune 2160p 和 Dune 1080p。"
    assert len(FakeLLM.calls) == 3
    assert any(message["role"] == "tool" for message in FakeLLM.calls[-1])


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
