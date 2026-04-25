import pytest

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
