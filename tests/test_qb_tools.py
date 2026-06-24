"""Tests for qBittorrent Agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.downloads import (
    BatchDownloadSubmissionResult,
    DownloadSubmissionResult,
)
from app.tools.qb_add_torrent import MAX_BATCH_ITEMS, QBAddTorrentTool
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
    """qb_category has been removed — downloads go directly to inbox without categorization."""
    tool = QBAddTorrentTool(MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert "qb_category" not in params, "qb_category should no longer be exposed to the LLM"


def test_qb_add_torrent_internal_tag_not_in_agent_schema():
    """internal_tag must NOT appear in the Agent tool schema (handled by coordinator)."""
    tool = QBAddTorrentTool(MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert "internal_tag" not in params, "internal_tag must not be exposed in the Agent tool schema"


def test_qb_add_torrent_submits_through_automation():
    """The tool delegates a typed request to the download automation boundary."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[DownloadSubmissionResult(
            receipt_id="r1", torrent_id="123", status="accepted", watch_task_id="wt-1",
            submission_receipt={
                "resource_title": "Test Movie", "external_id": "123", "qb_category": "电影",
                "qb_hash": "fake-hash", "status": "submitted_paused", "subtitle_count": 0,
            },
        )],
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({
        "torrent_id": "123",
        "qb_category": "电影",
        "save_path": "/downloads/movies",
        "tag": "4K",
        "completion_action": "notify",
    })

    assert response.status.value == "success"
    assert response.data["receipt"]["resource_title"] == "Test Movie"
    coord.submit_downloads.assert_called_once()
    req = coord.submit_downloads.call_args[0][0][0]
    assert req.torrent_id == "123"
    assert req.qb_category == "电影"
    assert req.save_path == "/downloads/movies"
    assert req.tag == "4K"


def test_qb_add_torrent_has_save_path_param():
    """save_path should be an optional new parameter."""
    tool = QBAddTorrentTool(MagicMock())
    params = {p.name: p for p in tool.get_parameters()}

    assert "save_path" in params
    assert params["save_path"].required is False
    assert params["save_path"].type == "string"


def test_qb_add_torrent_passes_save_path_to_coordinator():
    """save_path should be forwarded to the coordinator via the request."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[DownloadSubmissionResult(
            receipt_id="r1", torrent_id="123", status="accepted", watch_task_id="wt-1",
            submission_receipt={
                "resource_title": "Test Movie", "external_id": "123", "qb_category": "电影",
                "qb_hash": "fake-hash", "status": "submitted_paused", "subtitle_count": 0,
            },
        )],
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({
        "torrent_id": "123",
        "qb_category": "电影",
        "save_path": "/downloads/movies",
        "completion_action": "notify",
    })

    assert response.status.value == "success"
    req = coord.submit_downloads.call_args[0][0][0]
    assert req.save_path == "/downloads/movies"


def test_qb_add_torrent_default_category_when_omitted():
    """When category is omitted, should still proceed."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[DownloadSubmissionResult(
            receipt_id="r1", torrent_id="123", status="accepted", watch_task_id="wt-1",
            submission_receipt={
                "resource_title": "Test", "external_id": "123", "qb_category": "",
                "qb_hash": "fake-hash", "status": "submitted_paused", "subtitle_count": 0,
            },
        )],
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({"torrent_id": "123", "completion_action": "notify"})

    assert response.status.value == "success"


def test_qb_add_torrents_submits_all_items_paused():
    """Batch add should add each item through the coordinator."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[
            DownloadSubmissionResult(
                receipt_id="r1", torrent_id="101", status="accepted",
                watch_task_id="wt-1",
                submission_receipt={"resource_title": "Episode 1", "external_id": "101",
                                    "qb_category": "电视剧", "qb_hash": "h1", "status": "submitted_paused",
                                    "subtitle_count": 0},
            ),
            DownloadSubmissionResult(
                receipt_id="r2", torrent_id="102", status="accepted",
                watch_task_id="wt-2",
                submission_receipt={"resource_title": "Episode 2", "external_id": "102",
                                    "qb_category": "电视剧", "qb_hash": "h2", "status": "submitted_paused",
                                    "subtitle_count": 0},
            ),
        ],
        summary={"accepted": 2},
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({
        "items": [
            {"torrent_id": "101", "qb_category": "电视剧", "save_path": "/downloads/tv"},
            {"torrent_id": "102", "qb_category": "电视剧", "save_path": "/downloads/tv"},
        ],
        "completion_action": "notify",
    })

    assert response.status.value == "success"
    assert response.data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert response.data["receipt"]["type"] == "batch"
    assert len(response.data["receipts"]) == 2


def test_qb_add_torrents_reports_partial_success():
    """A failed item should not hide successfully submitted paused tasks."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[
            DownloadSubmissionResult(
                receipt_id="r1", torrent_id="101", status="accepted",
                watch_task_id="wt-1",
                submission_receipt={"resource_title": "Episode 1", "external_id": "101",
                                    "qb_category": "电视剧", "qb_hash": "h1", "status": "submitted_paused",
                                    "subtitle_count": 0},
            ),
            DownloadSubmissionResult(
                receipt_id="r2", torrent_id="102", status="failed",
                watch_task_id="",
                error="Torrent detail not found",
            ),
        ],
        summary={"accepted": 1, "failed": 1},
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({
        "items": [
            {"torrent_id": "101", "qb_category": "电视剧"},
            {"torrent_id": "102", "qb_category": "电视剧"},
        ],
        "completion_action": "notify",
    })

    assert response.status.value == "partial"
    assert response.data["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    assert response.data["items"][1]["status"] == "error"


def test_qb_add_torrents_rejects_oversized_batch():
    tool = QBAddTorrentTool(MagicMock())
    response = tool.run({
        "items": [{"torrent_id": str(i)} for i in range(MAX_BATCH_ITEMS + 1)],
        "completion_action": "notify",
    })

    assert response.status.value == "error"
    assert response.error_info["code"] == "BATCH_TOO_LARGE"


def test_qb_add_torrents_handles_single_item():
    """Batch tool should correctly delegate a single item through the coordinator."""
    coord = MagicMock()
    coord.submit_downloads.return_value = BatchDownloadSubmissionResult(
        items=[
            DownloadSubmissionResult(
                receipt_id="r1", torrent_id="101", status="accepted",
                watch_task_id="wt-1",
                submission_receipt={"resource_title": "Episode 1", "external_id": "101",
                                    "qb_category": "电视剧", "qb_hash": "h1", "status": "submitted_paused",
                                    "subtitle_count": 0},
            ),
        ],
        summary={"accepted": 1},
    )

    tool = QBAddTorrentTool(coord)
    response = tool.run({
        "items": [
            {"torrent_id": "101", "qb_category": "电视剧"},
        ],
        "completion_action": "notify",
    })

    assert response.status.value == "success"
    assert len(response.data["receipts"]) == 1
