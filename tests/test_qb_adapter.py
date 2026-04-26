import pytest

import app.adapters.qbittorrent as qb_module
from app.adapters.qbittorrent import QBittorrentAdapter


def test_qb_add_payload_contains_url_and_category():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    payload = adapter.build_add_payload(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
    )

    assert payload["urls"] == "https://download.local/token"
    assert payload["category"] == "movie"
    assert payload["rename"] == "[123] Dune"
    assert payload["paused"] == "false"


def test_qb_add_payload_supports_tags_and_paused():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local/",
        username="user",
        password="pass",
    )
    payload = adapter.build_add_payload(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
        paused=True,
        tags=["mteam", "night-watch"],
    )

    assert payload["paused"] == "true"
    assert payload["tags"] == "mteam,night-watch"
    assert adapter.add_torrent_endpoint() == "http://qb.local/api/v2/torrents/add"


def test_qb_add_payload_rejects_empty_url():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    with pytest.raises(ValueError):
        adapter.build_add_payload(url=" ", category="movie", rename="x")


def test_qb_add_torrent_url_reports_submitted_paused_when_paused(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    monkeypatch.setattr(qb_module.QBittorrentAdapter, "login", lambda self: {"sid": "cookie"})
    captured: dict[str, object] = {}

    class FakeResponse:
        text = "Ok."

        @staticmethod
        def raise_for_status() -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        def post(self, url, data):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr(qb_module.httpx, "Client", FakeClient)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
        paused=True,
        tags=["mteam"],
    )

    assert captured["url"] == "http://qb.local/api/v2/torrents/add"
    assert isinstance(captured["data"], dict)
    assert captured["data"]["paused"] == "true"
    assert result["status"] == "submitted_paused"


def test_qb_add_torrent_url_reports_submitted_when_not_paused(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    monkeypatch.setattr(qb_module.QBittorrentAdapter, "login", lambda self: {"sid": "cookie"})

    class FakeResponse:
        text = "ok"

        @staticmethod
        def raise_for_status() -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

        def post(self, url, data):
            _ = url
            assert data["paused"] == "false"
            return FakeResponse()

    monkeypatch.setattr(qb_module.httpx, "Client", FakeClient)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
        paused=False,
    )

    assert result["status"] == "submitted"
