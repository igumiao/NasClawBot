from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.agent_runtime.runner import HelloAgentWorkflowRunner
from app.api import chat_routes
from app.api import qb_routes
from app.api.chat_routes import AdapterDownloadExecutor
from app.api.schemas import ChatRequest, ConfirmRequest, QBTorrentActionRequest
from app.config import Settings
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


def _route_for(app, path: str, method: str):
    target_method = method.upper()
    for route in app.router.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", set())
        if target_method in methods:
            return route
    raise AssertionError(f"Route not found for {method} {path}")


def test_health_endpoint_returns_ok():
    response = _route_for(create_app(), "/health", "GET").endpoint()
    assert response["status"] == "ok", "/health should report ok status"


def test_index_page_is_served():
    response = _route_for(create_app(), "/", "GET").endpoint()
    assert "<html" in response.lower() or "<!doctype html" in response.lower(), "/ should serve html"


def test_create_app_allows_workflow_override():
    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/chat", "POST").endpoint
    response = endpoint(ChatRequest(session_id="s1", message="hello"))
    assert response.confirmation_payload.summary == "fake:hello", "overridden runner should shape the summary"


def test_chat_endpoint_returns_confirmation_payload():
    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/chat", "POST").endpoint
    body = endpoint(ChatRequest(session_id="s1", message="I want to watch Dune tonight"))
    assert body.status == "awaiting_confirmation", "chat response should remain awaiting confirmation"
    assert body.confirmation_payload.recommended_result_id == "x1", "chat response should preserve the recommended result"
    assert body.confirmation_payload.results, "chat response should include search results"


def test_confirm_approve_returns_completed_with_receipt():
    app = create_app(workflow_runner=FakeRunner())
    chat_endpoint = _route_for(app, "/chat", "POST").endpoint
    confirm_endpoint = _route_for(app, "/confirm", "POST").endpoint
    payload = chat_endpoint(ChatRequest(session_id="s1", message="I want to watch Dune tonight")).confirmation_payload
    body = confirm_endpoint(
        ConfirmRequest(
            session_id="s1",
            action="approve",
            selected_result_id=payload.recommended_result_id,
            confirmation_payload=payload,
        )
    )
    assert body.status == "completed", "approve should complete the workflow"
    assert body.receipt["status"] == "submitted_paused", "approve should preserve the submitted_paused receipt status"
    assert body.receipt["external_id"] == payload.recommended_result_id, "receipt should preserve the chosen external id"


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

    endpoint = _route_for(create_app(workflow_runner=MustNotCallRunner()), "/confirm", "POST").endpoint
    body = endpoint(ConfirmRequest(session_id="s1", action="reject_and_refine", confirmation_payload={"results": []}))
    assert body.status == "error", "reject_and_refine should be rejected at the route level"
    assert body.error == "Phase 2A does not support reject_and_refine on /confirm.", "route error text should stay stable"


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

    endpoint = _route_for(create_app(workflow_runner=CapturingRunner()), "/confirm", "POST").endpoint
    endpoint(
        ConfirmRequest(
            session_id="s1",
            action="cancel",
            selected_result_id="x1",
            confirmation_payload={
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
        )
    )
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

    endpoint = _route_for(create_app(workflow_runner=StrictRunner()), "/confirm", "POST").endpoint
    response = endpoint(
        ConfirmRequest(
            session_id="s1",
            action="cancel",
            confirmation_payload={"results": []},
            feedback_text="should be ignored",
        )
    )
    assert response.status == "canceled", "cancel should return canceled status"


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
        workflow_runner = "langgraph"

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


def test_create_app_health_does_not_build_default_runner(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(chat_routes, "_build_default_runner", lambda: (_ for _ in ()).throw(AssertionError("runner should stay lazy")))
    response = _route_for(create_app(), "/health", "GET").endpoint()
    assert response == {"status": "ok"}


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

    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/qb/torrents", "GET").endpoint
    body = endpoint(category="movie", tag="mteam", limit=10)
    assert captured["init"] == ("https://qb.local", "user", "pass"), "qb adapter should be initialized with the configured settings"
    assert captured["list_kwargs"] == {
        "category": "movie",
        "tag": "mteam",
        "limit": 10,
        "status_filter": None,
        "sort": None,
        "reverse": None,
    }, "qb torrent listing should forward query params"
    assert body.items[0].hash == "abc123", "qb torrent listing should include the hash"
    assert body.items[0].progress == 0.42, "qb torrent listing should include the progress"


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

    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/qb/torrents/{torrent_hash}", "GET").endpoint
    with pytest.raises(HTTPException) as excinfo:
        endpoint("missing")
    assert excinfo.value.status_code == 404, "/qb/torrents/{hash} should return 404 when missing"
    assert excinfo.value.detail == "Torrent not found: missing", "missing torrent response should preserve the hash"


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

    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/qb/torrents/{torrent_hash}", "GET").endpoint
    body = endpoint("abc123")
    assert body.hash == "abc123", "detail response should include the torrent hash"
    assert body.progress == 0.6, "detail response should include the progress"
    assert body.download_speed == 4096, "detail response should include the download speed"


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

    endpoint = _route_for(create_app(workflow_runner=FakeRunner()), "/qb/torrents/{torrent_hash}/actions", "POST").endpoint
    response = endpoint("abc123", QBTorrentActionRequest(action="pause"))
    assert captured["control"] == {
        "torrent_hash": "abc123",
        "action": "pause",
        "delete_files": False,
    }, "qb action endpoint should forward the control request"
    assert response.status == "pause", "qb action endpoint should echo the returned action"


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

    with pytest.raises(ValidationError):
        QBTorrentActionRequest(action="start-now")


# ---------------------------------------------------------------------------
# HelloAgents runner through the API boundary
# ---------------------------------------------------------------------------


class _FakeKeywordExtractor:
    """Returns the user message as the keyword without LLM call."""

    def invoke(self, message: str) -> dict[str, str]:
        return {"keyword": message}


def _build_helloagents_runner(
    *,
    mteam: MTeamAdapter,
    qb: QBittorrentAdapter,
    db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> HelloAgentWorkflowRunner:
    """Create a HelloAgentWorkflowRunner with fake adapters and keyword extractor."""
    fake_settings = Settings(
        mteam_base_url="https://mteam.local",
        mteam_api_key="key",
        qb_base_url="https://qb.local",
        qb_username="user",
        qb_password="pass",
        database_path=db_path,
    )
    monkeypatch.setattr("app.agent_runtime.runner.get_settings", lambda: fake_settings)
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)
    runner = HelloAgentWorkflowRunner(mteam_adapter=mteam, qb_adapter=qb)
    runner._keyword_extractor = _FakeKeywordExtractor()  # type: ignore[assignment]
    return runner


class TestHelloAgentsAPIBoundary:
    """Exercise HelloAgentWorkflowRunner through the FastAPI /chat and /confirm endpoints."""

    def test_chat_returns_awaiting_confirmation(self, tmp_path, monkeypatch):
        """Tracer bullet: HelloAgents runner wired through the API returns valid confirmation."""
        fake_mteam = FakeMTeamAdapter()
        fake_qb = FakeQBAdapter()
        db_path = str(tmp_path / "test.db")
        runner = _build_helloagents_runner(
            mteam=fake_mteam, qb=fake_qb, db_path=db_path, monkeypatch=monkeypatch
        )
        app = create_app(workflow_runner=runner)

        endpoint = _route_for(app, "/chat", "POST").endpoint
        response = endpoint(ChatRequest(session_id="s1", message="Dune 2021"))

        assert response.status == "awaiting_confirmation"
        assert response.confirmation_payload is not None
        assert response.confirmation_payload.recommended_result_id == "123"
        assert len(response.confirmation_payload.results) > 0
        assert response.error is None

    def test_confirm_approve_completes_workflow(self, tmp_path, monkeypatch):
        """Full round-trip: chat → approve → completed with receipt through the API."""
        fake_mteam = FakeMTeamAdapter()
        fake_qb = FakeQBAdapter()
        db_path = str(tmp_path / "test.db")
        runner = _build_helloagents_runner(
            mteam=fake_mteam, qb=fake_qb, db_path=db_path, monkeypatch=monkeypatch
        )
        app = create_app(workflow_runner=runner)

        chat_ep = _route_for(app, "/chat", "POST").endpoint
        chat_resp = chat_ep(ChatRequest(session_id="s2", message="Dune"))
        payload = chat_resp.confirmation_payload

        confirm_ep = _route_for(app, "/confirm", "POST").endpoint
        result = confirm_ep(
            ConfirmRequest(
                session_id="s2",
                action="approve",
                selected_result_id=payload.recommended_result_id,
                confirmation_payload=payload,
            )
        )

        assert result.status == "completed"
        assert result.receipt is not None
        assert result.receipt["status"] == "submitted_paused"
        assert result.receipt["external_id"] == "123"

    def test_confirm_cancel_returns_canceled(self, tmp_path, monkeypatch):
        """Cancel action through the API boundary."""
        fake_mteam = FakeMTeamAdapter()
        fake_qb = FakeQBAdapter()
        db_path = str(tmp_path / "test.db")
        runner = _build_helloagents_runner(
            mteam=fake_mteam, qb=fake_qb, db_path=db_path, monkeypatch=monkeypatch
        )
        app = create_app(workflow_runner=runner)

        chat_ep = _route_for(app, "/chat", "POST").endpoint
        chat_ep(ChatRequest(session_id="s3", message="Dune"))

        confirm_ep = _route_for(app, "/confirm", "POST").endpoint
        result = confirm_ep(
            ConfirmRequest(session_id="s3", action="cancel", confirmation_payload=None)
        )

        assert result.status == "canceled"

    def test_config_switch_builds_helloagents_runner(self, tmp_path, monkeypatch):
        """When workflow_runner='helloagents', _build_default_runner returns HelloAgentWorkflowRunner."""
        db_path = str(tmp_path / "test.db")

        class FakeSettings:
            mteam_base_url = "https://mteam.local"
            mteam_api_key = "key"
            qb_base_url = "https://qb.local"
            qb_username = "user"
            qb_password = "pass"
            workflow_runner = "helloagents"
            database_path = db_path

        monkeypatch.setattr(chat_routes, "MTeamAdapter", FakeMTeamAdapter)
        monkeypatch.setattr(chat_routes, "QBittorrentAdapter", FakeQBAdapter)
        monkeypatch.setattr(chat_routes, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(
            "app.agent_runtime.runner.get_settings", lambda: FakeSettings()
        )

        runner = chat_routes._build_default_runner()
        assert isinstance(runner, HelloAgentWorkflowRunner)


# ---------------------------------------------------------------------------
# Fake adapters for HelloAgents API boundary tests
# ---------------------------------------------------------------------------


class FakeMTeamAdapter(MTeamAdapter):
    """Returns canned search results without hitting the network."""

    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        pass

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        return [
            {"id": 123, "title": "Dune 2021 2160p", "seeders": 10, "size": "10 GiB", "size_bytes": 10737418240},
            {"id": 456, "title": "Dune Part Two 2024", "seeders": 5, "size": "20 GiB", "size_bytes": 21474836480},
        ]

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        return {"title": f"Detail for {torrent_id}", "id": torrent_id}

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        return f"https://mteam.local/download/{torrent_id}"

    def is_download_url_torrent(self, url: str) -> bool:
        return bool(url)


class FakeQBAdapter(QBittorrentAdapter):
    """Records add calls without touching a real qB instance."""

    def __init__(self, base_url: str = "", username: str = "", password: str = "") -> None:
        pass

    def add_torrent_url(self, *, url: str, category: str, rename: str, tags: list[str], paused: bool) -> dict[str, Any]:
        return {"ok": True, "status": "submitted_paused", "qb_hash": "fake-hash"}

    def generate_mteam_torrent_name(self, mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        return f"{mteam_id}.torrent"

    def login(self) -> None:
        pass
