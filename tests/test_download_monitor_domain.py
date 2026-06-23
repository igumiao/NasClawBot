from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.downloads import (
    DownloadMonitorSpec,
    DownloadMonitorUpdate,
    build_download_monitor_payload,
    parse_download_monitor,
)


@pytest.mark.parametrize(
    ("mode", "on_completed"),
    [
        ("once", "notify"),
        ("once", "organize"),
        ("until_complete", "notify"),
        ("until_complete", "organize"),
    ],
)
def test_canonical_monitor_matrix(mode: str, on_completed: str) -> None:
    snapshot = {"background_organization_allowed": True} if on_completed == "organize" else None
    payload = build_download_monitor_payload(
        torrent_hash="abc",
        torrent_name="Example",
        save_path="/downloads",
        monitor=DownloadMonitorSpec(mode=mode, on_completed=on_completed),
        authorization_snapshot=snapshot,
    )

    parsed = parse_download_monitor(payload)

    assert parsed.mode == mode
    assert parsed.on_completed == on_completed
    assert parsed.is_legacy is False
    assert "check_policy" not in payload
    assert "resolved_follow_up" not in payload
    assert "scheduled_for" not in payload


@pytest.mark.parametrize(
    ("legacy_mode", "legacy_action", "mode", "on_completed"),
    [
        ("continuous", "notify_only", "until_complete", "notify"),
        ("continuous", "auto_organize", "until_complete", "organize"),
        ("once", "notify_only", "once", "notify"),
        ("once", "auto_organize", "once", "organize"),
        ("once", "none", "once", "none"),
    ],
)
def test_legacy_monitor_payloads_remain_readable(
    legacy_mode: str,
    legacy_action: str,
    mode: str,
    on_completed: str,
) -> None:
    parsed = parse_download_monitor(
        {
            "check_policy": {"mode": legacy_mode},
            "resolved_follow_up": {"mode": legacy_action},
        }
    )

    assert parsed.mode == mode
    assert parsed.on_completed == on_completed
    assert parsed.is_legacy is True


def test_monitor_update_requires_a_real_mutation() -> None:
    with pytest.raises(ValidationError):
        DownloadMonitorUpdate(task_id="task-1")
    with pytest.raises(ValidationError):
        DownloadMonitorUpdate(task_id="task-1", start_at=None)


def test_notify_payload_rejects_authorization_snapshot() -> None:
    with pytest.raises(ValueError, match="must not carry"):
        build_download_monitor_payload(
            torrent_hash="abc",
            torrent_name="Example",
            save_path="/downloads",
            monitor=DownloadMonitorSpec(mode="once", on_completed="notify"),
            authorization_snapshot={"background_organization_allowed": True},
        )
