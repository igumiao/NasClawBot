"""Tests for qBittorrent Agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tools.qb_add_torrent import QBAddTorrentTool
from app.tools.qb_control_torrent import QBControlTorrentTool
from app.tools.qb_get_torrent import QBGetTorrentTool
from app.tools.qb_list_categories import QBListCategoriesTool
from app.tools.qb_set_global_speed import QBSetGlobalSpeedTool
from app.tools.qb_list_torrents import QBListTorrentsTool
from app.tools.qb_set_torrent_speed import QBSetTorrentSpeedTool


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


def test_qb_list_categories_returns_categories():
    qb = MagicMock()
    qb.list_categories.return_value = {
        "movie": {"savePath": "/downloads/movie"},
        "tvshow": {"savePath": "/downloads/tvshow"},
    }

    tool = QBListCategoriesTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert len(response.data["categories"]) == 2
    assert "movie" in response.data["categories"]


def test_qb_list_categories_empty():
    qb = MagicMock()
    qb.list_categories.return_value = {}

    tool = QBListCategoriesTool(qb)
    response = tool.run({})

    assert response.status.value == "success"
    assert response.data["categories"] == {}


def test_qb_control_torrent_pause():
    qb = MagicMock()
    qb.control_torrent.return_value = {"ok": True, "status": "pause", "qb_hash": "abc123"}

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "pause"})

    assert response.status.value == "success"
    qb.control_torrent.assert_called_once_with("abc123", action="pause", delete_files=False)


def test_qb_control_torrent_delete_with_files():
    qb = MagicMock()
    qb.control_torrent.return_value = {"ok": True, "status": "delete", "qb_hash": "abc123"}

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "delete", "delete_files": True})

    assert response.status.value == "success"
    qb.control_torrent.assert_called_once_with("abc123", action="delete", delete_files=True)


def test_qb_control_torrent_invalid_action():
    qb = MagicMock()
    qb.control_torrent.side_effect = ValueError("Unsupported torrent action: invalid")

    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "abc123", "action": "invalid"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_control_torrent_empty_hash():
    qb = MagicMock()
    tool = QBControlTorrentTool(qb)
    response = tool.run({"torrent_hash": "  ", "action": "pause"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_set_global_speed_both_limits():
    qb = MagicMock()
    qb.set_global_speed_limits.return_value = {"ok": True, "upload_limit": 10485760, "download_limit": 52428800}

    tool = QBSetGlobalSpeedTool(qb)
    response = tool.run({"upload_limit": 10485760, "download_limit": 52428800})

    assert response.status.value == "success"
    qb.set_global_speed_limits.assert_called_once_with(upload_limit=10485760, download_limit=52428800)


def test_qb_set_global_speed_no_params():
    qb = MagicMock()

    tool = QBSetGlobalSpeedTool(qb)
    response = tool.run({})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_set_torrent_speed_both_limits():
    qb = MagicMock()
    qb.set_torrent_speed_limits.return_value = {
        "ok": True,
        "torrent_hash": "abc123",
        "upload_limit": 5242880,
        "download_limit": 20971520,
    }

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "abc123", "upload_limit": 5242880, "download_limit": 20971520})

    assert response.status.value == "success"
    qb.set_torrent_speed_limits.assert_called_once_with(
        torrent_hash="abc123", upload_limit=5242880, download_limit=20971520
    )


def test_qb_set_torrent_speed_no_limits():
    qb = MagicMock()

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "abc123"})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_set_torrent_speed_empty_hash():
    qb = MagicMock()
    qb.set_torrent_speed_limits.side_effect = ValueError("torrent_hash must not be empty")

    tool = QBSetTorrentSpeedTool(qb)
    response = tool.run({"torrent_hash": "  ", "upload_limit": 1024})

    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_PARAM"


def test_qb_add_torrent_category_optional_with_presets():
    """qb_category should be optional with preset enum values."""
    tool = QBAddTorrentTool(MagicMock(), MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert params["qb_category"].required is False
    assert params["qb_category"].enum == ["电影", "电视剧", "综艺", "动漫", "纪录片"]


def test_qb_add_torrent_has_save_path_param():
    """save_path should be an optional new parameter."""
    tool = QBAddTorrentTool(MagicMock(), MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert "save_path" in params
    assert params["save_path"].required is False
    assert params["save_path"].type == "string"


def test_qb_add_torrent_passes_save_path_to_adapter():
    """save_path should be forwarded to the adapter's add_torrent_url."""
    mteam = MagicMock()
    mteam.get_torrent_details.return_value = {"title": "Test Movie", "smallDescr": "1080p"}
    mteam.get_torrent_download_url.return_value = "https://example.com/dl/token"
    mteam.is_download_url_torrent.return_value = True

    qb = MagicMock()
    qb.generate_mteam_torrent_name.return_value = "[123][电影][Test.Movie]"
    qb.add_torrent_url.return_value = {"ok": True, "status": "submitted_paused", "qb_hash": None}

    tool = QBAddTorrentTool(mteam, qb)
    response = tool.run({
        "torrent_id": "123",
        "qb_category": "电影",
        "save_path": "/downloads/movies",
    })

    assert response.status.value == "success"
    call_kwargs = qb.add_torrent_url.call_args.kwargs
    assert call_kwargs.get("save_path") == "/downloads/movies"


def test_qb_add_torrent_default_category_when_omitted():
    """When category is omitted, should still proceed."""
    mteam = MagicMock()
    mteam.get_torrent_details.return_value = {"title": "Test"}
    mteam.get_torrent_download_url.return_value = "https://example.com/dl/token"
    mteam.is_download_url_torrent.return_value = True

    qb = MagicMock()
    qb.generate_mteam_torrent_name.return_value = "[123][other][Test]"
    qb.add_torrent_url.return_value = {"ok": True, "status": "submitted_paused", "qb_hash": None}

    tool = QBAddTorrentTool(mteam, qb)
    response = tool.run({"torrent_id": "123"})

    assert response.status.value == "success"
