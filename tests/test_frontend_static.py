from fastapi.testclient import TestClient

from app.api import chat_routes
from app.main import create_app


class FakeRunner:
    def run_chat(self, session_id: str, message: str) -> dict:
        return {
            "session_id": session_id,
            "status": "awaiting_confirmation",
            "confirmation_payload": {"summary": f"fake:{message}", "results": []},
        }

    def run_confirm(
        self,
        session_id: str,
        *,
        action: str,
        confirmation_payload,
        selected_result_id: str | None = None,
    ) -> dict:
        _ = (action, confirmation_payload, selected_result_id)
        return {
            "session_id": session_id,
            "status": "completed",
            "messages": ["ok"],
        }


def test_index_route_serves_html():
    client = TestClient(create_app(workflow_runner=FakeRunner()))

    response = client.get("/")

    assert response.status_code == 200
    assert "<html" in response.text.lower() or "<!doctype html" in response.text.lower()


def test_static_mount_does_not_break_health():
    client = TestClient(create_app(workflow_runner=FakeRunner()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_route_prefers_built_dist_html(tmp_path, monkeypatch):
    source_index = tmp_path / "index.html"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    dist_index = dist_dir / "index.html"
    source_index.write_text("<!doctype html><html><body>source</body></html>", encoding="utf-8")
    dist_index.write_text("<!doctype html><html><body>built</body></html>", encoding="utf-8")
    monkeypatch.setattr(chat_routes, "_FRONTEND_INDEX", source_index)
    monkeypatch.setattr(chat_routes, "_FRONTEND_DIST_INDEX", dist_index)

    client = TestClient(create_app(workflow_runner=FakeRunner()))

    response = client.get("/")

    assert response.status_code == 200
    assert "built" in response.text
