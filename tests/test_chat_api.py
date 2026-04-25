from fastapi.testclient import TestClient
from pathlib import Path
from uuid import uuid4

from app.main import create_app
from app.storage.session_store import SessionStore


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


def test_chat_endpoint_returns_confirmation_payload():
    client = TestClient(create_app())
    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "I want to watch Dune tonight"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["confirmation_payload"]["recommended_result_id"] == "2"
    assert body["confirmation_payload"]["results"]


def test_confirm_approve_returns_completed_with_receipt():
    client = TestClient(create_app())
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
