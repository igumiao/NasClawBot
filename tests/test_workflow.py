import httpx

import app.adapters.qbittorrent as qb_module
from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.models import ResourceCandidate
from app.services.receipt_service import build_receipt
from app.workflow.graph import build_workflow


class StubExtractor:
    def invoke(self, message: str):
        return {
            "query_text": message,
            "title": "Dune Part Two",
            "media_type": "movie",
            "optimization_goal": "speed",
            "urgency": "high",
        }


class StubSearchTool:
    def __call__(self, constraints):
        return [
            ResourceCandidate(
                id="2",
                title="Dune Part Two 2024 1080p",
                media_type="movie",
                year=2024,
                resolution="1080p",
                seeders=120,
                size="12 GB",
                source="mteam",
            ),
            ResourceCandidate(
                id="1",
                title="Dune Part Two 2024 1080p",
                media_type="movie",
                year=2024,
                resolution="1080p",
                seeders=20,
                size="10 GB",
                source="mteam",
            ),
        ]


def test_workflow_returns_confirmation_payload():
    graph = build_workflow(extractor=StubExtractor(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "I want to watch Dune tonight"})

    assert result["confirmation_payload"]["recommended_result_id"] == "2"
    assert result["status"] == "awaiting_confirmation"


def test_receipt_builder_reports_duplicate_result():
    receipt = build_receipt(
        resource_title="Dune Part Two",
        external_id="123",
        qb_category="movie",
        qb_hash=None,
        status="already_exists",
    )

    assert receipt["status"] == "already_exists"
    assert receipt["external_id"] == "123"


def test_workflow_executes_approved_selection_and_returns_receipt():
    graph = build_workflow(extractor=StubExtractor(), search_tool=StubSearchTool())
    result = graph.invoke(
        {
            "session_id": "s1",
            "confirmation_payload": {
                "qb_category": "movie",
                "selected_result_id": "2",
                "results": [
                    {
                        "id": "2",
                        "title": "Dune Part Two 2024 1080p",
                        "score": 99.0,
                        "seeders": 120,
                        "resolution": "1080p",
                        "reasons": ["title-match"],
                    }
                ],
            },
        }
    )

    assert result["status"] == "completed"
    assert result["confirmation_payload"]["execution_result"]["external_id"] == "2"
    assert result["confirmation_payload"]["receipt"]["status"] == "submitted"
    assert result["confirmation_payload"]["receipt"]["qb_hash"] == "stub-hash"


def test_workflow_uses_injected_download_executor():
    captured: dict[str, str] = {}

    def stub_download_executor(selected_result: dict, qb_category: str) -> dict:
        captured["selected_id"] = str(selected_result["id"])
        captured["category"] = qb_category
        return {"status": "submitted", "qb_hash": "injected-hash"}

    graph = build_workflow(
        extractor=StubExtractor(),
        search_tool=StubSearchTool(),
        download_executor=stub_download_executor,
    )
    result = graph.invoke(
        {
            "session_id": "s1",
            "confirmation_payload": {
                "qb_category": "movie",
                "selected_result_id": "2",
                "results": [
                    {
                        "id": "2",
                        "title": "Dune Part Two 2024 1080p",
                        "score": 99.0,
                        "seeders": 120,
                        "resolution": "1080p",
                        "reasons": ["title-match"],
                    }
                ],
            },
        }
    )

    assert captured["selected_id"] == "2"
    assert captured["category"] == "movie"
    assert result["confirmation_payload"]["receipt"]["external_id"] == "2"
    assert result["confirmation_payload"]["receipt"]["qb_hash"] == "injected-hash"


def test_qb_add_torrent_url_requires_ok_body_not_only_http_200(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type
            _ = exc
            _ = tb
            return False

        def post(self, *args, **kwargs):
            _ = args
            _ = kwargs
            return FakeResponse("Queue accepted")

    adapter = QBittorrentAdapter(base_url="http://qb.local", username="u", password="p")
    monkeypatch.setattr(QBittorrentAdapter, "login", lambda self: httpx.Cookies())
    monkeypatch.setattr(qb_module.httpx, "Client", FakeClient)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123][movie][title]",
    )

    assert result["ok"] is False
    assert result["status"] == "unknown"
