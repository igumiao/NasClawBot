"""Tests for qBittorrent Agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_torrents import QBListTorrentsTool


def test_qb_list_torrents_returns_serialized_rows():
    qb = MagicMock()
    qb.list_torrents.return_value = [
        {
            "hash": "abc123",
            "name": "Dune Part Two",
            "category": "movie",
            "tags": ["mteam"],
            "state": "downloading",
            "progress": 0.75,
            "download_speed": 10485760,
            "upload_speed": 524288,
            "eta": 1800,
            "save_path": "/downloads/movie",
            "size": 123456,
            "total_size": 654321,
        }
    ]

    tool = QBListTorrentsTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert len(response.data["torrents"]) == 1
    assert response.data["torrents"][0]["hash"] == "abc123"


def test_qb_list_torrents_forwards_filters():
    qb = MagicMock()
    qb.list_torrents.return_value = []

    tool = QBListTorrentsTool(qb)
    tool.run({"category": "movie", "status_filter": "downloading", "limit": 10})

    qb.list_torrents.assert_called_once_with(
        category="movie", tag=None, status_filter="downloading", sort=None, limit=10
    )


def test_qb_list_torrents_empty_result():
    qb = MagicMock()
    qb.list_torrents.return_value = []

    tool = QBListTorrentsTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert response.data["torrents"] == []
    assert response.data["count"] == 0


def test_qb_list_torrents_rejects_invalid_limit():
    qb = MagicMock()

    tool = QBListTorrentsTool(qb)
    response = tool.run({"limit": 0})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_list_torrents_rejects_negative_limit():
    qb = MagicMock()

    tool = QBListTorrentsTool(qb)
    response = tool.run({"limit": -1})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_list_torrents_strips_empty_string_filters():
    qb = MagicMock()
    qb.list_torrents.return_value = []

    tool = QBListTorrentsTool(qb)
    tool.run({"category": "", "tag": "  "})

    qb.list_torrents.assert_called_once_with(
        category=None, tag=None, status_filter=None, sort=None, limit=None
    )


def test_qb_list_torrents_parameters():
    qb = MagicMock()
    tool = QBListTorrentsTool(qb)
    params = {p.name: p for p in tool.get_parameters()}

    assert "category" in params
    assert params["category"].required is False
    assert "limit" in params
    assert params["limit"].type == "integer"
    assert params["limit"].required is False


def test_qb_get_torrent_returns_detail():
    qb = MagicMock()
    qb.get_torrent.return_value = {
        "hash": "abc123",
        "name": "Dune Part Two",
        "category": "movie",
        "state": "downloading",
        "progress": 0.75,
        "download_speed": 10485760,
        "upload_speed": 524288,
        "save_path": "/downloads/movie",
        "size": 123456,
        "total_size": 654321,
        "comment": "from mteam",
        "share_ratio": 1.5,
    }

    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123"})

    assert response.status.value == "success"
    assert response.data["torrent"]["hash"] == "abc123"
    qb.get_torrent.assert_called_once_with("abc123")


def test_qb_get_torrent_not_found():
    qb = MagicMock()
    qb.get_torrent.return_value = None

    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "missing"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "NOT_FOUND"


def test_qb_get_torrent_empty_hash():
    qb = MagicMock()
    tool = QBGetTorrentTool(qb)
    response = tool.run({"torrent_hash": "  "})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"
