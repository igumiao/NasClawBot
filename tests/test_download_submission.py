"""Tests for the DownloadSubmission service.

Tests the full submission chain from M-Team detail/token through qB add
with real-ish adapter behavior, tag injection, subtitle preservation, and
error paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.domain.downloads import DownloadSubmissionRequest
from app.services.download_submission import DownloadSubmission


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMTeamAdapter:
    """Configurable fake for MTeamAdapter.

    Defaults simulate a successful detail/token/subtitle chain.
    Override by setting attributes directly.
    """

    def __init__(self) -> None:
        self.detail: dict[str, Any] | None = {
            "title": "Test Movie 2160p",
            "id": "123",
        }
        self.download_url: str | None = "https://mteam.local/dl/123"
        self.is_torrent: bool = True
        self.subtitles: list[dict[str, Any]] = []
        self.subtitle_bytes: bytes | None = b"subtitle content"

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        return self.detail

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        return self.download_url

    def is_download_url_torrent(self, url: str) -> bool:
        return self.is_torrent

    def list_subtitles(self, torrent_id: str) -> list[dict[str, Any]]:
        return self.subtitles

    def download_subtitle_bytes(self, subtitle_id: str) -> bytes | None:
        return self.subtitle_bytes


class FakeQBAdapter:
    """Configurable fake for QBittorrentAdapter."""

    def __init__(self) -> None:
        self.add_result: dict[str, Any] = {
            "ok": True,
            "status": "submitted_paused",
            "qb_hash": "fake-hash",
        }
        self.captured_kwargs: dict[str, Any] | None = None

    def add_torrent_url(self, **kwargs: Any) -> dict[str, Any]:
        self.captured_kwargs = dict(kwargs)
        return self.add_result

    def generate_mteam_torrent_name(
        self, mteam_id: str, detail: dict[str, Any], qb_category: str
    ) -> str:
        return f"{mteam_id}.torrent"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mteam() -> FakeMTeamAdapter:
    return FakeMTeamAdapter()


@pytest.fixture
def qb() -> FakeQBAdapter:
    return FakeQBAdapter()


@pytest.fixture
def submission(mteam: FakeMTeamAdapter, qb: FakeQBAdapter) -> DownloadSubmission:
    return DownloadSubmission(
        mteam_adapter=mteam,
        qb_adapter=qb,
        default_save_path=None,
        default_tags=["mteam"],
    )


@pytest.fixture
def submission_with_default_path(
    mteam: FakeMTeamAdapter, qb: FakeQBAdapter
) -> DownloadSubmission:
    return DownloadSubmission(
        mteam_adapter=mteam,
        qb_adapter=qb,
        default_save_path="/volume1/default/downloads",
        default_tags=["mteam"],
    )


@pytest.fixture
def submission_with_custom_tags(
    mteam: FakeMTeamAdapter, qb: FakeQBAdapter
) -> DownloadSubmission:
    return DownloadSubmission(
        mteam_adapter=mteam,
        qb_adapter=qb,
        default_save_path=None,
        default_tags=["mteam", "刷流"],
    )


def make_request(**overrides: Any) -> DownloadSubmissionRequest:
    defaults: dict[str, Any] = {"torrent_id": "123", "qb_category": "movie"}
    defaults.update(overrides)
    return DownloadSubmissionRequest(**defaults)


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestSubmitSuccess:
    """Full chain succeeds with expected receipt shape."""

    def test_submit_returns_submitted_paused(self, submission: DownloadSubmission) -> None:
        receipt = submission.submit(make_request())
        assert receipt["status"] == "submitted_paused"
        assert receipt["resource_title"] == "Test Movie 2160p"
        assert receipt["external_id"] == "123"
        assert receipt["qb_hash"] == "fake-hash"
        assert receipt["qb_category"] == "movie"
        assert receipt["subtitle_count"] == 0

    def test_submit_passes_paused_flag(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request())
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["paused"] is False

    def test_submit_generates_torrent_name(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request())
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["rename"] == "123.torrent"

    def test_submit_passes_category(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request(qb_category="电视剧"))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["category"] == "电视剧"

    def test_submit_passes_download_url(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request())
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["url"] == "https://mteam.local/dl/123"


# ---------------------------------------------------------------------------
# Tests: tag injection
# ---------------------------------------------------------------------------


class TestTagInjection:
    """Default tags, user tags, and correlation tags are injected correctly."""

    def test_default_tags_present(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request())
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam"]

    def test_user_tag_appended(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request(tag="电影"))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam", "电影"]

    def test_user_tag_empty_string_omitted(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request(tag="  "))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam"]

    def test_user_tag_none_omitted(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission.submit(make_request(tag=None))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam"]

    def test_custom_default_tags(self, submission_with_custom_tags: DownloadSubmission, qb: FakeQBAdapter) -> None:
        submission_with_custom_tags.submit(make_request())
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam", "刷流"]

    def test_correlation_tag_generates_add_tags(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission.submit(make_request(tag=None), correlation_tag="wt-42")
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs.get("add_tags") == ["nasclaw-task-wt-42"]

    def test_no_correlation_tag_no_add_tags(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission.submit(make_request(tag=None))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs.get("add_tags") is None

    def test_correlation_tag_with_user_tag(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission.submit(make_request(tag="动漫"), correlation_tag="wt-7")
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["tags"] == ["mteam", "动漫"]
        assert qb.captured_kwargs.get("add_tags") == ["nasclaw-task-wt-7"]


# ---------------------------------------------------------------------------
# Tests: save path resolution
# ---------------------------------------------------------------------------


class TestSavePath:
    """save_path from request or default_save_path is forwarded to qB."""

    def test_request_save_path_forwarded(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission.submit(make_request(save_path="/downloads/movies"))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["save_path"] == "/downloads/movies"

    def test_default_save_path_used_when_request_empty(
        self, submission_with_default_path: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission_with_default_path.submit(make_request(save_path=None))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["save_path"] == "/volume1/default/downloads"

    def test_request_save_path_overrides_default(
        self, submission_with_default_path: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission_with_default_path.submit(make_request(save_path="/manual/path"))
        assert qb.captured_kwargs is not None
        assert qb.captured_kwargs["save_path"] == "/manual/path"

    def test_no_save_path_omitted_when_not_configured(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        submission.submit(make_request(save_path=None))
        assert qb.captured_kwargs is not None
        assert "save_path" not in qb.captured_kwargs


# ---------------------------------------------------------------------------
# Tests: M-Team detail resolution
# ---------------------------------------------------------------------------


class TestDetailResolution:
    """M-Team detail fetch, token generation, and URL validation."""

    def test_detail_not_found_returns_error(self, submission: DownloadSubmission, mteam: FakeMTeamAdapter) -> None:
        mteam.detail = None
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert "Failed to get torrent details" in (receipt.get("error") or "")
        assert receipt["qb_hash"] is None
        assert receipt["subtitle_count"] == 0

    def test_detail_resolution_uses_torrent_id_as_fallback_title(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        """When detail has no 'title' key, resource_title should still be set."""
        mteam.detail = {"id": "999"}
        receipt = submission.submit(make_request(torrent_id="999"))
        # submit() reads detail.get("title") -> None, uses torrent_id as fallback
        assert receipt["status"] == "submitted_paused"
        assert receipt["resource_title"] == "999"

    def test_token_not_generated_returns_error(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        mteam.download_url = None
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert "Failed to generate download URL" in (receipt.get("error") or "")

    def test_url_not_torrent_returns_error(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        mteam.is_torrent = False
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert "Download URL is not a torrent" in (receipt.get("error") or "")


# ---------------------------------------------------------------------------
# Tests: subtitle behavior
# ---------------------------------------------------------------------------


class TestSubtitleBehavior:
    """Community subtitle auto-download preservation."""

    def test_subtitles_downloaded_when_available(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter, tmp_path: Path
    ) -> None:
        mteam.detail = {
            "title": "Movie With Subs",
            "id": "456",
            "hasChineseSubtitle": True,
        }
        mteam.subtitles = [
            {"id": "sub1", "filename": "chi.srt"},
            {"id": "sub2", "filename": "eng.srt"},
        ]

        receipt = submission.submit(make_request(torrent_id="456", save_path=str(tmp_path)))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 2

        # Verify files were written
        assert (tmp_path / "chi.srt").exists()
        assert (tmp_path / "eng.srt").exists()

    def test_subtitles_not_downloaded_when_flag_false(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        mteam.detail = {
            "title": "Movie No Subs",
            "id": "789",
            "hasChineseSubtitle": False,
        }
        mteam.subtitles = [
            {"id": "sub1", "filename": "chi.srt"},
        ]

        receipt = submission.submit(make_request(torrent_id="789", save_path="/tmp/subs_test"))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 0

    def test_subtitles_not_downloaded_when_flag_missing(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        mteam.detail = {"title": "Movie", "id": "101"}
        mteam.subtitles = [{"id": "sub1", "filename": "chi.srt"}]

        receipt = submission.submit(make_request(torrent_id="101", save_path="/tmp/subs_test"))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 0

    def test_subtitle_download_failure_does_not_fail_submission(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter
    ) -> None:
        """Subtitle download failures are logged but the submission still succeeds."""
        mteam.detail = {
            "title": "Sub Fail Movie",
            "id": "555",
            "hasChineseSubtitle": True,
        }
        mteam.subtitles = [{"id": "sub1", "filename": "chi.srt"}]
        # Simulate subtitle bytes download failure
        mteam.subtitle_bytes = None

        receipt = submission.submit(make_request(torrent_id="555", save_path="/tmp/sub_fail"))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 0

    def test_subtitle_count_in_receipt(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter, tmp_path: Path
    ) -> None:
        mteam.detail = {
            "title": "Sub Count Test",
            "id": "777",
            "hasChineseSubtitle": True,
        }
        mteam.subtitles = [
            {"id": "s1", "filename": "a.srt"},
            {"id": "s2", "filename": "b.srt"},
            {"id": "s3", "filename": "c.srt"},
        ]

        receipt = submission.submit(make_request(torrent_id="777", save_path=str(tmp_path)))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 3

    def test_subtitle_save_path_uses_submission_save_path(
        self, submission: DownloadSubmission, mteam: FakeMTeamAdapter, tmp_path: Path
    ) -> None:
        sub_dir = tmp_path / "subs"
        mteam.detail = {
            "title": "Path Test",
            "id": "888",
            "hasChineseSubtitle": True,
        }
        mteam.subtitles = [{"id": "s1", "filename": "chi.srt"}]

        receipt = submission.submit(make_request(torrent_id="888", save_path=str(sub_dir)))
        assert receipt["status"] == "submitted_paused"
        assert receipt["subtitle_count"] == 1
        assert (sub_dir / "chi.srt").exists()


# ---------------------------------------------------------------------------
# Tests: qB error handling
# ---------------------------------------------------------------------------


class TestQBErrorHandling:
    """qB add failure paths."""

    def test_qb_returns_error_receipt(self, submission: DownloadSubmission, qb: FakeQBAdapter) -> None:
        qb.add_result = {
            "ok": False,
            "error_code": "CONFLICT",
            "error_message": "Torrent already exists",
            "retryable": False,
        }
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert "[CONFLICT] Torrent already exists" in (receipt.get("error") or "")

    def test_qb_retryable_error_hints_user(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        qb.add_result = {
            "ok": False,
            "error_code": "NETWORK_ERROR",
            "error_message": "Connection refused",
            "retryable": True,
        }
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert "可重试" in (receipt.get("error") or "")

    def test_qb_unknown_error_fallback(
        self, submission: DownloadSubmission, qb: FakeQBAdapter
    ) -> None:
        qb.add_result = {"ok": False}  # minimal error response
        receipt = submission.submit(make_request())
        assert receipt["status"] == "error"
        assert receipt["qb_hash"] is None
        assert receipt["subtitle_count"] == 0


# ---------------------------------------------------------------------------
# Tests: validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Input validation for empty or missing values."""

    def test_empty_torrent_id_returns_error(self, submission: DownloadSubmission) -> None:
        receipt = submission.submit(make_request(torrent_id="  "))
        assert receipt["status"] == "error"
        assert "torrent_id is required" in (receipt.get("error") or "")

    def test_empty_torrent_id_after_strip_returns_error(
        self, submission: DownloadSubmission
    ) -> None:
        receipt = submission.submit(make_request(torrent_id="\t\n  "))
        assert receipt["status"] == "error"
