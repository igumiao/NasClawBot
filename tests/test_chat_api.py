from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

import pytest

from app.api import chat_routes
from app.api import qb_routes
from app.api.chat_routes import AdapterDownloadExecutor
from app.domain.models import ConfirmationPayload
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
    assert response.status_code == 200, "/health should respond with HTTP 200"
    assert response.json()["status"] == "ok", "/health should report ok status"


def test_index_page_is_served():
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200, "/ should serve the frontend page"
    assert "fnOS Media Agent" in response.text, "index page should contain the app title"


def test_create_app_allows_workflow_override():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 200, "/chat should accept the overridden workflow runner"
    assert response.json()["confirmation_payload"]["summary"] == "fake:hello", "overridden runner should shape the summary"


def test_chat_endpoint_returns_confirmation_payload():
    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "I want to watch Dune tonight"},
    )
    assert response.status_code == 200, "/chat should respond with HTTP 200"
    body = response.json()
    assert body["status"] == "awaiting_confirmation", "chat response should remain awaiting confirmation"
    assert body["confirmation_payload"]["recommended_result_id"] == "x1", "chat response should preserve the recommended result"
    assert body["confirmation_payload"]["results"], "chat response should include search results"


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
    assert response.status_code == 200, "/confirm should accept approved selections"
    body = response.json()
    assert body["status"] == "completed", "approve should complete the workflow"
    assert body["receipt"]["status"] == "submitted_paused", "approve should preserve the submitted_paused receipt status"
    assert body["receipt"]["external_id"] == payload["recommended_result_id"], "receipt should preserve the chosen external id"


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
    assert response.status_code == 200, "/confirm should return a route-level validation response"
    body = response.json()
    assert body["status"] == "error", "reject_and_refine should be rejected at the route level"
    assert body["error"] == "Phase 2A does not support reject_and_refine on /confirm.", "route error text should stay stable"


def test_confirm_endpoint_parses_confirmation_payload_to_model():
    captured: dict[str, object] = {}

    class CapturingRunner:
        def run_chat(self, session_id: str, message: str) -> dict:
            _ = (session_id, message)
            return {"session_id": session_id, "status": "awaiting_confirmation"}

        def run_confirm(
            self,
            session_id: str,
            *,
            action: str,
            confirmation_payload,
            selected_result_id: str | None = None,
        ) -> dict:
            captured["confirmation_payload"] = confirmation_payload
            captured["selected_result_id"] = selected_result_id
            return {"session_id": session_id, "status": "canceled", "messages": ["Request canceled by user."]}

    client = TestClient(create_app(workflow_runner=CapturingRunner()))
    response = client.post(
        "/confirm",
        json={
            "session_id": "s1",
            "action": "cancel",
            "selected_result_id": "x1",
            "confirmation_payload": {
                "summary": "pick one",
                "recommended_result_id": "x1",
                "results": [
                    {
                        "id": "x1",
                        "title": "Fake Item",
                        "seeders": 0,
                        "resolution": "1080p",
                        "size": "10 GB",
                    }
                ],
            },
        },
    )

    assert response.status_code == 200, "/confirm should accept a typed confirmation payload"
    assert isinstance(captured["confirmation_payload"], ConfirmationPayload), "route should coerce confirmation payload to model"
    assert captured["selected_result_id"] == "x1", "route should forward the selected result id"


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
    assert response.status_code == 200, "/confirm should accept cancel requests"
    assert response.json()["status"] == "canceled", "cancel should return canceled status"


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
    assert record is not None, "session store should return the inserted record"
    assert record["status"] == "awaiting_confirmation", "session store should persist the status"

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

    assert result["status"] == "download_url_invalid", "invalid torrent URL should be rejected before qB submission"
    assert result["qb_hash"] is None, "invalid torrent URL should not produce a qB hash"


def test_adapter_download_executor_submits_paused_and_returns_paused_status():
    calls: dict[str, object] = {}

    class FakeMTeamAdapter:
        def get_torrent_details(self, torrent_id: str):
            assert torrent_id == "1172412", "download executor should request details for the selected torrent"
            return {"name": "Fake Item"}

        def get_torrent_download_url(self, torrent_id: str):
            assert torrent_id == "1172412", "download executor should request a token for the selected torrent"
            return "https://download.local/file.torrent"

        def is_download_url_torrent(self, url: str) -> bool:
            return url.endswith(".torrent")

    class FakeQBAdapter:
        def generate_mteam_torrent_name(self, mteam_id, detail, qb_category):
            _ = detail
            assert mteam_id == "1172412", "qB name generation should use the M-Team id"
            assert qb_category == "movie", "qB name generation should receive the target category"
            return "[1172412][movie][Fake.Item]"

        def add_torrent_url(self, **kwargs):
            calls.update(kwargs)
            return {"ok": True, "status": "submitted_paused", "qb_hash": "abc123"}

    executor = AdapterDownloadExecutor(FakeMTeamAdapter(), FakeQBAdapter())
    result = executor({"id": "1172412", "title": "Fake"}, "movie")

    assert calls["paused"] is True, "download submission should pause the torrent by default"
    assert calls["category"] == "movie", "download submission should preserve the qB category"
    assert calls["tags"] == ["mteam"], "download submission should tag the torrent as mteam"
    assert result["status"] == "submitted_paused", "download submission should report submitted_paused"
    assert result["qb_hash"] == "abc123", "download submission should return the qB hash"


def test_adapter_search_tool_accepts_keyword_string():
    class FakeMTeamAdapter:
        def search_torrents_by_keyword(self, *, keyword: str, page: int, page_size: int):
            assert keyword == "dune", "search tool should forward the normalized keyword"
            assert page == 1, "search tool should use the default page"
            assert page_size == 20, "search tool should use the default page size"
            return [{"id": "1", "title": "Dune.2021.2160p", "seeders": 42, "size": "1.2 GB"}]

    tool = chat_routes.AdapterSearchTool(FakeMTeamAdapter())
    results = tool("dune")

    assert len(results) == 1, "search tool should return one normalized result"
    assert results[0].title == "Dune.2021.2160p", "search tool should preserve the title"
    assert results[0].resolution == "2160p", "search tool should infer resolution from the title"


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

    assert isinstance(captured["keyword_finder"], FakeFindKeywordLLM), "default runner should wire the keyword finder"
    assert isinstance(captured["search_tool"], chat_routes.AdapterSearchTool), "default runner should wire the search tool"
    assert callable(captured["download_executor"]), "default runner should wire the download executor"
    assert isinstance(runner, FakeRunner), "default runner should build the workflow runner"


def test_list_qb_torrents_endpoint_returns_adapter_rows(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeQBAdapter:
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

    class FakeSettings:
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.get("/qb/torrents", params={"category": "movie", "tag": "mteam", "limit": 10})

    assert response.status_code == 200, "/qb/torrents should respond with HTTP 200"
    assert captured["init"] == ("https://qb.local", "user", "pass"), "qb adapter should be initialized with the configured settings"
    assert captured["list_kwargs"] == {
        "category": "movie",
        "tag": "mteam",
        "limit": 10,
        "status_filter": None,
        "sort": None,
        "reverse": None,
    }, "qb torrent listing should forward query params"
    body = response.json()
    assert body["items"][0]["hash"] == "abc123", "qb torrent listing should include the hash"
    assert body["items"][0]["progress"] == 0.42, "qb torrent listing should include the progress"


def test_get_qb_torrent_endpoint_returns_not_found_when_missing(monkeypatch: pytest.MonkeyPatch):
    class FakeQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def get_torrent(self, torrent_hash: str):
            assert torrent_hash == "missing", "missing torrent lookup should query the missing hash"
            return None

    class FakeSettings:
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.get("/qb/torrents/missing")

    assert response.status_code == 404, "/qb/torrents/{hash} should return 404 when missing"
    assert response.json()["detail"] == "Torrent not found: missing", "missing torrent response should preserve the hash"


def test_get_qb_torrent_endpoint_returns_detail_payload(monkeypatch: pytest.MonkeyPatch):
    class FakeQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def get_torrent(self, torrent_hash: str):
            assert torrent_hash == "abc123", "detail lookup should query the requested hash"
            return {
                "hash": "abc123",
                "name": "Dune Part Two",
                "category": "movie",
                "tags": ["mteam"],
                "state": "downloading",
                "progress": 0.6,
                "download_speed": 4096,
                "upload_speed": 512,
                "eta": 1800,
                "save_path": "/downloads/movie",
                "size": 123456,
                "total_size": 654321,
                "comment": "from mteam",
                "total_uploaded": 999,
                "share_ratio": 0.5,
                "creation_date": 1710000000,
            }

    class FakeSettings:
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.get("/qb/torrents/abc123")

    assert response.status_code == 200, "/qb/torrents/{hash} should return HTTP 200 for found torrents"
    body = response.json()
    assert body["hash"] == "abc123", "detail response should include the torrent hash"
    assert body["progress"] == 0.6, "detail response should include the progress"
    assert body["download_speed"] == 4096, "detail response should include the download speed"


def test_qb_torrent_action_endpoint_dispatches_control(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    class FakeQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def control_torrent(self, torrent_hash: str, *, action: str, delete_files: bool = False):
            captured["control"] = {
                "torrent_hash": torrent_hash,
                "action": action,
                "delete_files": delete_files,
            }
            return {"ok": True, "status": "pause", "qb_hash": torrent_hash}

    class FakeSettings:
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post("/qb/torrents/abc123/actions", json={"action": "pause"})

    assert response.status_code == 200, "/qb/torrents/{hash}/actions should accept supported actions"
    assert captured["control"] == {
        "torrent_hash": "abc123",
        "action": "pause",
        "delete_files": False,
    }, "qb action endpoint should forward the control request"
    assert response.json()["status"] == "pause", "qb action endpoint should echo the returned action"


def test_qb_torrent_action_endpoint_rejects_invalid_action(monkeypatch: pytest.MonkeyPatch):
    class FakeQBAdapter:
        def __init__(self, base_url: str, username: str, password: str):
            _ = (base_url, username, password)

        def control_torrent(self, torrent_hash: str, *, action: str, delete_files: bool = False):
            _ = (torrent_hash, action, delete_files)
            raise AssertionError("route validation should reject invalid action before adapter call")

    class FakeSettings:
        qb_base_url = "https://qb.local"
        qb_username = "user"
        qb_password = "pass"

    monkeypatch.setattr(qb_routes, "QBittorrentAdapter", FakeQBAdapter)
    monkeypatch.setattr(qb_routes, "get_settings", lambda: FakeSettings())

    client = TestClient(create_app(workflow_runner=FakeRunner()))
    response = client.post("/qb/torrents/abc123/actions", json={"action": "start-now"})

    assert response.status_code == 422, "invalid qB action should be rejected by route validation"
