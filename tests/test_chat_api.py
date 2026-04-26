from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

import pytest

from app.api import chat_routes
from app.api.chat_routes import AdapterDownloadExecutor
from app.main import create_app
from app.storage.session_store import SessionStore


class FakeRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {
            "session_id": session_id,
            "status": "awaiting_confirmation",
            "confirmation_payload": {
                "summary": f"fake:{message}",
                "recommended_result_id": "x1",
                "results": [
                    {
                        "id": "x1",
                        "title": "Fake Item",
                        "score": 1.0,
                        "seeders": 0,
                        "resolution": "1080p",
                        "reasons": ["fake"],
                    }
                ],
            },
        }

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload: dict | None,
        selected_result_id: str | None = None,
    ) -> dict:
        normalized_action = action.strip().lower()
        if normalized_action == "approve":
            chosen_id = selected_result_id or (confirmation_payload or {}).get("recommended_result_id", "x1")
            return {
                "session_id": session_id,
                "status": "completed",
                "confirmation_payload": confirmation_payload,
                "receipt": {
                    "resource_title": "Fake Item",
                    "external_id": chosen_id,
                    "qb_category": "movie",
                    "qb_hash": "fake-hash",
                    "status": "submitted_paused",
                },
            }
        if normalized_action == "cancel":
            return {"session_id": session_id, "status": "canceled", "messages": ["Request canceled by user."]}
        return {
            "session_id": session_id,
            "status": "error",
            "error": f"Unsupported action: {action}",
        }


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_page_is_served():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "fnOS Media Agent" in response.text


def test_create_app_allows_workflow_override():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 200
    assert response.json()["confirmation_payload"]["summary"] == "fake:hello"


def test_chat_endpoint_returns_confirmation_payload():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "I want to watch Dune tonight"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["confirmation_payload"]["recommended_result_id"] == "x1"
    assert body["confirmation_payload"]["results"]


def test_confirm_approve_returns_completed_with_receipt():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    chat = client.post(
        "/chat",
        json={"session_id": "s1", "message": "I want to watch Dune tonight"},
    )
    payload = chat.json()["confirmation_payload"]
    response = client.post(
        "/confirm",
        json={
            "session_id": "s1",
            "action": "approve",
            "selected_result_id": payload["recommended_result_id"],
            "confirmation_payload": payload,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["receipt"]["status"] == "submitted_paused"
    assert body["receipt"]["external_id"] == payload["recommended_result_id"]


def test_confirm_reject_and_refine_returns_route_level_phase2a_error():
    class MustNotCallRunner:
        def run_chat(self, session_id: str, message: str) -> dict:
            _ = (session_id, message)
            return {"session_id": session_id, "status": "awaiting_confirmation"}

        def run_confirm(
            self,
            session_id: str,
            *,
            action: str,
            confirmation_payload: dict | None,
            selected_result_id: str | None = None,
        ) -> dict:
            _ = (session_id, action, confirmation_payload, selected_result_id)
            raise AssertionError("runner.run_confirm must not be called for reject_and_refine in Phase 2A")

    client = TestClient(create_app(workflow_runner=MustNotCallRunner()))
    response = client.post(
        "/confirm",
        json={
            "session_id": "s1",
            "action": "reject_and_refine",
            "confirmation_payload": {"results": []},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == "Phase 2A does not support reject_and_refine on /confirm."


def test_confirm_does_not_forward_feedback_text_kwarg():
    class StrictRunner:
        def run_chat(self, session_id: str, message: str) -> dict:
            _ = (session_id, message)
            return {"session_id": "s1", "status": "awaiting_confirmation", "confirmation_payload": {"results": []}}

        def run_confirm(
            self,
            session_id: str,
            *,
            action: str,
            confirmation_payload: dict | None,
            selected_result_id: str | None = None,
        ) -> dict:
            _ = (session_id, action, confirmation_payload, selected_result_id)
            return {"session_id": session_id, "status": "canceled", "messages": ["Request canceled by user."]}

    client = TestClient(create_app(workflow_runner=StrictRunner()))
    response = client.post(
        "/confirm",
        json={
            "session_id": "s1",
            "action": "cancel",
            "feedback_text": "should be ignored",
            "confirmation_payload": {"results": []},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"


def test_session_store_round_trip():
    test_data_dir = Path("tests_runtime")
    test_data_dir.mkdir(exist_ok=True)
    db_path = test_data_dir / f"session-{uuid4().hex}.db"
    store = SessionStore(db_path=db_path)
    store.upsert(
        session_id="s1",
        latest_user_message="find dune",
        constraints_json='{"title":"Dune"}',
        confirmation_payload_json='{"summary":"pick one"}',
        status="awaiting_confirmation",
    )

    record = store.get("s1")
    assert record is not None
    assert record["status"] == "awaiting_confirmation"

    db_path.unlink(missing_ok=True)


def test_adapter_download_executor_blocks_non_torrent_download_url():
    class FakeMTeamAdapter:
        def get_torrent_details(self, torrent_id: str):
            _ = torrent_id
            return {"name": "Fake Item"}

        def get_torrent_download_url(self, torrent_id: str):
            _ = torrent_id
            return "https://download.local/not-torrent"

        def is_download_url_torrent(self, url: str) -> bool:
            _ = url
            return False

    class FakeQBAdapter:
        def generate_mteam_torrent_name(self, mteam_id, detail, qb_category):
            _ = mteam_id
            _ = detail
            _ = qb_category
            return "[fake]"

        def add_torrent_url(self, **kwargs):
            _ = kwargs
            raise AssertionError("qB add_torrent_url must not be called for invalid download URL")

    executor = AdapterDownloadExecutor(FakeMTeamAdapter(), FakeQBAdapter())
    result = executor({"id": "1172412", "title": "Fake"}, "movie")

    assert result["status"] == "download_url_invalid"
    assert result["qb_hash"] is None


def test_adapter_download_executor_submits_paused_and_returns_paused_status():
    calls: dict[str, object] = {}

    class FakeMTeamAdapter:
        def get_torrent_details(self, torrent_id: str):
            assert torrent_id == "1172412"
            return {"name": "Fake Item"}

        def get_torrent_download_url(self, torrent_id: str):
            assert torrent_id == "1172412"
            return "https://download.local/file.torrent"

        def is_download_url_torrent(self, url: str) -> bool:
            return url.endswith(".torrent")

    class FakeQBAdapter:
        def generate_mteam_torrent_name(self, mteam_id, detail, qb_category):
            _ = detail
            assert mteam_id == "1172412"
            assert qb_category == "movie"
            return "[1172412][movie][Fake.Item]"

        def add_torrent_url(self, **kwargs):
            calls.update(kwargs)
            return {"ok": True, "status": "submitted_paused", "qb_hash": "abc123"}

    executor = AdapterDownloadExecutor(FakeMTeamAdapter(), FakeQBAdapter())
    result = executor({"id": "1172412", "title": "Fake"}, "movie")

    assert calls["paused"] is True
    assert calls["category"] == "movie"
    assert calls["tags"] == ["mteam"]
    assert result["status"] == "submitted_paused"
    assert result["qb_hash"] == "abc123"


def test_adapter_search_tool_accepts_keyword_string():
    class FakeMTeamAdapter:
        def search_torrents_by_keyword(self, *, keyword: str, page: int, page_size: int):
            assert keyword == "dune"
            assert page == 1
            assert page_size == 20
            return [{"id": "1", "title": "Dune.2021.2160p", "seeders": 42, "size": "1.2 GB"}]

    tool = chat_routes.AdapterSearchTool(FakeMTeamAdapter())
    results = tool("dune")

    assert len(results) == 1
    assert results[0].title == "Dune.2021.2160p"
    assert results[0].resolution == "2160p"


def test_build_default_runner_wires_find_keyword_llm(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeFindKeywordLLM:
        pass

    class FakeMTeamAdapter:
        def __init__(self, base_url: str, api_key: str):
            _ = (base_url, api_key)

    class FakeQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

    class FakeRunner:
        def __init__(self, graph):
            self.graph = graph

    class FakeSettings:
        mteam_base_url = "https://mteam.local"
        mteam_api_key = "key"
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    def fake_build_workflow(*, keyword_finder=None, search_tool=None, download_executor=None):
        captured["keyword_finder"] = keyword_finder
        captured["search_tool"] = search_tool
        captured["download_executor"] = download_executor
        return "fake-graph"

    monkeypatch.setattr(chat_routes, "FindKeywordLLM", FakeFindKeywordLLM)
    monkeypatch.setattr(chat_routes, "MTeamAdapter", FakeMTeamAdapter)
    monkeypatch.setattr(chat_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(chat_routes, "LangGraphWorkflowRunner", FakeRunner)
    monkeypatch.setattr(chat_routes, "build_workflow", fake_build_workflow)
    monkeypatch.setattr(chat_routes, "get_settings", lambda: FakeSettings())

    runner = chat_routes._build_default_runner()

    assert isinstance(captured["keyword_finder"], FakeFindKeywordLLM)
    assert isinstance(captured["search_tool"], chat_routes.AdapterSearchTool)
    assert callable(captured["download_executor"])
    assert isinstance(runner, FakeRunner)
