from types import SimpleNamespace

import pytest

import app.adapters.qbittorrent as qb_module
from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.models import ConfirmationCandidate, ConfirmationPayload, ResourceCandidate
from app.services.receipt_service import build_receipt
from app.workflow.graph import build_workflow


class StubExtractor:
    def invoke(self, message: str):
        _ = message
        return "dune"


class StubSearchTool:
    def __call__(self, keyword: str):
        assert keyword == "dune"
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
    graph = build_workflow(keyword_finder=StubExtractor(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "I want to watch Dune tonight"})
    payload = result["confirmation_payload"]

    assert isinstance(payload, ConfirmationPayload)
    assert payload.recommended_result_id == "2"
    assert len(payload.results) == 2
    assert isinstance(payload.results[0], ConfirmationCandidate)
    assert payload.results[0].size == "12 GB"
    assert "score" not in payload.results[0].model_dump()
    assert "reasons" not in payload.results[0].model_dump()
    assert "explanation" not in payload.model_dump()
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
    graph = build_workflow(keyword_finder=StubExtractor(), search_tool=StubSearchTool())
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
                        "seeders": 120,
                        "resolution": "1080p",
                    }
                ],
            },
        }
    )

    assert result["status"] == "completed"
    assert result["confirmation_payload"].execution_result["external_id"] == "2"
    assert result["confirmation_payload"].receipt["status"] == "submitted_paused"
    assert result["confirmation_payload"].receipt["qb_hash"] == "stub-hash"


def test_workflow_uses_injected_download_executor():
    captured: dict[str, str] = {}

    def stub_download_executor(selected_result: dict, qb_category: str) -> dict:
        captured["selected_id"] = str(selected_result["id"])
        captured["category"] = qb_category
        return {"status": "submitted_paused", "qb_hash": "injected-hash"}

    graph = build_workflow(
        keyword_finder=StubExtractor(),
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
                        "seeders": 120,
                        "resolution": "1080p",
                    }
                ],
            },
        }
    )

    assert captured["selected_id"] == "2"
    assert captured["category"] == "movie"
    assert result["confirmation_payload"].receipt["external_id"] == "2"
    assert result["confirmation_payload"].receipt["qb_hash"] == "injected-hash"
    assert result["confirmation_payload"].receipt["status"] == "submitted_paused"


def test_workflow_limits_confirmation_payload_to_first_three_results():
    class FourResultSearchTool:
        def __call__(self, keyword: str):
            _ = keyword
            return [
                ResourceCandidate(
                    id="1",
                    title="A",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=10,
                    size="1 GB",
                    source="mteam",
                ),
                ResourceCandidate(
                    id="2",
                    title="B",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=20,
                    size="2 GB",
                    source="mteam",
                ),
                ResourceCandidate(
                    id="3",
                    title="C",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=30,
                    size="3 GB",
                    source="mteam",
                ),
                ResourceCandidate(
                    id="4",
                    title="D",
                    media_type="movie",
                    year=2024,
                    resolution="1080p",
                    seeders=40,
                    size="4 GB",
                    source="mteam",
                ),
            ]

    graph = build_workflow(keyword_finder=StubExtractor(), search_tool=FourResultSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "find dune"})

    assert [item.id for item in result["confirmation_payload"].results] == ["1", "2", "3"]


def test_build_workflow_uses_default_keyword_finder():
    graph = build_workflow(search_tool=StubSearchTool())
    assert graph is not None


def test_workflow_accepts_keyword_only_dict_payload():
    class DictKeywordFinder:
        def invoke(self, message: str):
            _ = message
            return {"keyword": "dune"}

    graph = build_workflow(keyword_finder=DictKeywordFinder(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "watch dune"})

    assert result["keyword"] == "dune"


def test_workflow_accepts_keyword_dict_with_extra_metadata():
    class KeywordWithMetadataFinder:
        def invoke(self, message: str):
            _ = message
            return {"keyword": "dune", "confidence": 0.97, "source": "llm"}

    graph = build_workflow(keyword_finder=KeywordWithMetadataFinder(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "watch dune"})

    assert result["keyword"] == "dune"


def test_workflow_rejects_legacy_constraint_extractor_output():
    class LegacyExtractor:
        def invoke(self, message: str):
            return {"query_text": message, "title": "Dune Part Two"}

    graph = build_workflow(keyword_finder=LegacyExtractor(), search_tool=StubSearchTool())

    with pytest.raises(TypeError, match="query_text"):
        graph.invoke({"session_id": "s1", "user_message": "watch dune"})


def test_workflow_executor_missing_status_defaults_to_submitted_paused():
    def missing_status_executor(selected_result: dict, qb_category: str) -> dict:
        _ = selected_result
        _ = qb_category
        return {"qb_hash": "hash-without-status"}

    graph = build_workflow(
        keyword_finder=StubExtractor(),
        search_tool=StubSearchTool(),
        download_executor=missing_status_executor,
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
                        "seeders": 120,
                        "resolution": "1080p",
                        "size": "12 GB",
                    }
                ],
            },
        }
    )

    assert result["confirmation_payload"].receipt["status"] == "submitted_paused"


def test_qb_add_torrent_url_requires_ok_body_not_only_http_200(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_add(self, **kwargs):
            _ = kwargs
            return "Queue accepted"

    adapter = QBittorrentAdapter(base_url="http://qb.local", username="u", password="p")
    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123][movie][title]",
    )

    assert result["ok"] is False
    assert result["status"] == "unknown"
