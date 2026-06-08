"""Tests for qBittorrent Agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
        category="movie", status_filter="downloading", limit=10
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
