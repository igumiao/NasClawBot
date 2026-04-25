from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

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
        feedback_text: str | None = None,
    ) -> dict:
        _ = feedback_text
        if action == "approve":
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
                    "status": "submitted",
                },
            }
        return {"session_id": session_id, "status": "canceled", "messages": ["Request canceled by user."]}


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
    assert body["receipt"]["status"] == "submitted"
    assert body["receipt"]["external_id"] == payload["recommended_result_id"]


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
