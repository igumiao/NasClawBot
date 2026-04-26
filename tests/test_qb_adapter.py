from types import SimpleNamespace

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
    assert payload["is_paused"] is False


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

    assert payload["is_paused"] is True
    assert payload["tags"] == ["mteam", "night-watch"]


def test_qb_add_payload_rejects_empty_url():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    with pytest.raises(ValueError):
        adapter.build_add_payload(url=" ", category="movie", rename="x")


def test_qb_add_torrent_url_delegates_to_qbittorrent_api_client(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def auth_log_in(self):
            captured["logged_in"] = True

        def torrents_add(self, **kwargs):
            captured["add_kwargs"] = kwargs
            return "Ok."

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
        paused=True,
        tags=["mteam"],
    )

    assert captured["client_kwargs"]["host"] == "http://qb.local"
    assert captured["logged_in"] is True
    assert captured["add_kwargs"]["urls"] == "https://download.local/token"
    assert captured["add_kwargs"]["category"] == "movie"
    assert captured["add_kwargs"]["rename"] == "[123] Dune"
    assert captured["add_kwargs"]["is_paused"] is True
    assert captured["add_kwargs"]["tags"] == ["mteam"]
    assert result["status"] == "submitted_paused"


def test_qb_add_torrent_url_reports_submitted_when_not_paused(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_add(self, **kwargs):
            assert kwargs["is_paused"] is False
            return "ok"

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.add_torrent_url(
        url="https://download.local/token",
        category="movie",
        rename="[123] Dune",
        paused=False,
    )

    assert result["status"] == "submitted"


def test_qb_list_categories_reads_qbittorrent_api_categories(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs
            self.torrent_categories = SimpleNamespace(
                categories={
                    "movie": {"savePath": "/downloads/movie"},
                    "tv": {"savePath": "/downloads/tv"},
                }
            )

        def auth_log_in(self):
            return None

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    categories = adapter.list_categories()

    assert categories["movie"]["savePath"] == "/downloads/movie"
    assert categories["tv"]["savePath"] == "/downloads/tv"


def test_qb_list_torrents_returns_structured_rows(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_info(self, **kwargs):
            captured["list_kwargs"] = kwargs
            return [
                SimpleNamespace(
                    hash="abc123",
                    name="Dune Part Two",
                    category="movie",
                    tags="mteam",
                    state="pausedDL",
                    progress=0.42,
                    dlspeed=1024,
                    upspeed=128,
                    eta=3600,
                    save_path="/downloads/movie",
                    size=123456,
                    total_size=654321,
                )
            ]

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    rows = adapter.list_torrents(category="movie", tag="mteam", limit=5)

    assert captured["list_kwargs"]["category"] == "movie"
    assert captured["list_kwargs"]["tag"] == "mteam"
    assert captured["list_kwargs"]["limit"] == 5
    assert rows == [
        {
            "hash": "abc123",
            "name": "Dune Part Two",
            "category": "movie",
            "tags": ["mteam"],
            "state": "pausedDL",
            "progress": 0.42,
            "download_speed": 1024,
            "upload_speed": 128,
            "eta": 3600,
            "save_path": "/downloads/movie",
            "size": 123456,
            "total_size": 654321,
        }
    ]


def test_qb_get_torrent_returns_combined_info_and_properties(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_info(self, **kwargs):
            assert kwargs["torrent_hashes"] == "abc123"
            return [
                SimpleNamespace(
                    hash="abc123",
                    name="Dune Part Two",
                    category="movie",
                    tags="mteam,watchlist",
                    state="downloading",
                    progress=0.6,
                    dlspeed=4096,
                    upspeed=512,
                    eta=1800,
                    save_path="/downloads/movie",
                    size=123456,
                    total_size=654321,
                )
            ]

        def torrents_properties(self, **kwargs):
            assert kwargs["torrent_hash"] == "abc123"
            return SimpleNamespace(
                comment="from mteam",
                total_uploaded=999,
                share_ratio=0.5,
                creation_date=1710000000,
            )

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    row = adapter.get_torrent("abc123")

    assert row == {
        "hash": "abc123",
        "name": "Dune Part Two",
        "category": "movie",
        "tags": ["mteam", "watchlist"],
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


def test_qb_get_torrent_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_info(self, **kwargs):
            _ = kwargs
            return []

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    assert adapter.get_torrent("missing") is None


@pytest.mark.parametrize(
    ("action", "extra_kwargs", "expected_call", "expected_payload"),
    [
        ("pause", {}, "torrents_pause", {"torrent_hashes": "abc123"}),
        ("resume", {}, "torrents_resume", {"torrent_hashes": "abc123"}),
        ("recheck", {}, "torrents_recheck", {"torrent_hashes": "abc123"}),
        ("reannounce", {}, "torrents_reannounce", {"torrent_hashes": "abc123"}),
        ("delete", {"delete_files": True}, "torrents_delete", {"torrent_hashes": "abc123", "delete_files": True}),
    ],
)
def test_qb_control_torrent_dispatches_actions(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    extra_kwargs: dict[str, object],
    expected_call: str,
    expected_payload: dict[str, object],
):
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            _ = kwargs

        def auth_log_in(self):
            return None

        def torrents_pause(self, **kwargs):
            captured["call"] = "torrents_pause"
            captured["kwargs"] = kwargs

        def torrents_resume(self, **kwargs):
            captured["call"] = "torrents_resume"
            captured["kwargs"] = kwargs

        def torrents_recheck(self, **kwargs):
            captured["call"] = "torrents_recheck"
            captured["kwargs"] = kwargs

        def torrents_reannounce(self, **kwargs):
            captured["call"] = "torrents_reannounce"
            captured["kwargs"] = kwargs

        def torrents_delete(self, **kwargs):
            captured["call"] = "torrents_delete"
            captured["kwargs"] = kwargs

    monkeypatch.setattr(qb_module, "qbittorrentapi", SimpleNamespace(Client=FakeClient), raising=False)

    result = adapter.control_torrent("abc123", action=action, **extra_kwargs)

    assert captured["call"] == expected_call
    assert captured["kwargs"] == expected_payload
    assert result == {"ok": True, "status": action, "qb_hash": "abc123"}


def test_qb_control_torrent_rejects_unknown_action():
    adapter = QBittorrentAdapter(
        base_url="http://qb.local",
        username="user",
        password="pass",
    )

    with pytest.raises(ValueError, match="Unsupported torrent action"):
        adapter.control_torrent("abc123", action="start-now")
