from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.domain.downloads import (
    DownloadMonitorRequest,
    DownloadMonitorUpdate,
    DownloadSubmissionRequest,
)
from app.domain.organization import OrganizationAuthorizationPolicy
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.services.download_automation import DownloadAutomation, DownloadAutomationError
from app.storage.db import ensure_schema


NOW = datetime(2026, 6, 23, 8, 0, tzinfo=timezone.utc)


class PolicyStore:
    def __init__(self, policy: OrganizationAuthorizationPolicy) -> None:
        self.policy = policy

    def load(self) -> OrganizationAuthorizationPolicy:
        return self.policy


@pytest.fixture
def automation(tmp_path: Path):
    counter = itertools.count(1)
    ids = lambda: f"id-{next(counter)}"
    db = tmp_path / "tasks.db"
    ensure_schema(db)
    scheduler = TaskScheduler(RuntimeTaskStore(db, lambda: NOW, ids), lambda: NOW, ids)
    submission = MagicMock()
    submission.resolve_save_path.side_effect = lambda request: request.save_path or "/downloads"
    submission.submit.return_value = {
        "resource_title": "Movie",
        "external_id": "123",
        "qb_hash": "ABC",
        "status": "submitted_paused",
    }
    qb = MagicMock()
    qb.get_torrent.return_value = {
        "hash": "ABC",
        "name": "Movie",
        "save_path": "/downloads",
        "content_path": "/downloads/Movie",
    }
    policy = PolicyStore(OrganizationAuthorizationPolicy(
        background_organization_allowed=True,
        allowed_source_path_prefixes=["/downloads"],
        destination_root="/media",
    ))
    service = DownloadAutomation(
        submission, qb, scheduler, policy, lambda: NOW, ids, ["/media"]
    )
    return service, scheduler, submission, qb, policy


def test_submit_none_does_not_create_monitor(automation):
    service, scheduler, submission, _, _ = automation
    result = service.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="123")], "none", "session"
    )
    assert result.items[0].status == "accepted"
    assert result.items[0].watch_task_id is None
    assert scheduler.list_tasks() == []
    submission.submit.assert_called_once()
    assert submission.submit.call_args.args[0].torrent_id == "123"


def test_submit_notify_uses_prepare_activate_and_exclusive_key(automation):
    service, scheduler, submission, _, _ = automation
    result = service.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")],
        "notify",
        "session",
        "approval-1",
    )
    task = scheduler.get(result.items[0].watch_task_id)
    assert task is not None
    assert task.status.value == "queued"
    assert task.exclusive_key == "download-monitor:abc"
    assert task.payload["monitor"] == {"mode": "until_complete", "on_completed": "notify"}
    assert "authorization_snapshot" not in task.payload
    assert submission.submit.call_args.kwargs["correlation_tag"] == task.task_id


def test_submit_retry_does_not_repeat_qb_side_effect(automation):
    service, _, submission, _, _ = automation
    request = DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")
    first = service.submit_downloads([request], "notify", "session", "approval-1")
    second = service.submit_downloads([request], "notify", "session", "approval-1")
    assert second.items[0].watch_task_id == first.items[0].watch_task_id
    assert submission.submit.call_count == 1


def test_submit_notify_accepts_success_without_immediate_hash(automation):
    service, scheduler, submission, _, _ = automation
    submission.submit.return_value = {
        "resource_title": "Movie",
        "external_id": "123",
        "qb_hash": None,
        "status": "submitted_paused",
    }

    result = service.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")],
        "notify",
        "session",
        "approval-qb4",
    )

    item = result.items[0]
    assert item.status == "accepted"
    task = scheduler.get(item.watch_task_id)
    assert task is not None
    assert task.status.value == "queued"
    assert task.payload["qb_hash"] == ""
    assert task.exclusive_key is None


def test_submit_organize_captures_snapshot(automation):
    service, scheduler, _, _, _ = automation
    result = service.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")],
        "organize",
        "session",
    )
    task = scheduler.get(result.items[0].watch_task_id)
    assert task.payload["authorization_snapshot"] == {
        "background_organization_allowed": True,
        "allowed_source_path_prefixes": ["/downloads"],
        "destination_root": "/media",
        "allow_delete": False,
        "allow_overwrite": False,
    }


def test_organize_rejects_destination_outside_mcp_scope(automation):
    service, _, _, _, policy = automation
    policy.policy = policy.policy.model_copy(update={"destination_root": "/elsewhere"})
    with pytest.raises(DownloadAutomationError) as exc:
        service.submit_downloads(
            [DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")],
            "organize",
            "session",
        )
    assert exc.value.code == "DESTINATION_OUTSIDE_MCP_SCOPE"


def test_organize_rejects_source_path_traversal(automation):
    service, _, _, _, _ = automation
    with pytest.raises(DownloadAutomationError) as exc:
        service.submit_downloads(
            [DownloadSubmissionRequest(
                torrent_id="123",
                save_path="/downloads/../outside",
            )],
            "organize",
            "session",
        )
    assert exc.value.code == "SOURCE_PATH_NOT_AUTHORIZED"


def test_organize_rejects_destination_path_traversal(automation):
    service, _, _, _, policy = automation
    policy.policy = policy.policy.model_copy(
        update={"destination_root": "/media/../outside"}
    )
    with pytest.raises(DownloadAutomationError) as exc:
        service.submit_downloads(
            [DownloadSubmissionRequest(torrent_id="123", save_path="/downloads")],
            "organize",
            "session",
        )
    assert exc.value.code == "DESTINATION_OUTSIDE_MCP_SCOPE"


def test_create_monitor_translates_qb_windows_source_path_before_authorization(
    automation,
):
    _, scheduler, submission, qb, policy = automation
    qb.get_torrent.return_value = {
        "hash": "ABC",
        "name": "Movie",
        "save_path": r"D:\影视\未整理",
        "content_path": r"D:\影视\未整理\Movie",
    }
    policy.policy = policy.policy.model_copy(update={
        "allowed_source_path_prefixes": ["/mnt/d/影视/未整理"],
    })
    service = DownloadAutomation(
        submission,
        qb,
        scheduler,
        policy,
        lambda: NOW,
        lambda: "mapped-monitor",
        ["/media"],
        path_mapping={"D:\\": "/mnt/d/"},
    )

    receipt = service.create_monitor(
        DownloadMonitorRequest(
            torrent_hash="ABC",
            mode="until_complete",
            on_completed="organize",
        ),
        "session",
        "approval-mapped",
    )

    task = scheduler.get(receipt.task_id)
    assert task is not None
    assert task.payload["save_path"] == "/mnt/d/影视/未整理/Movie"


def test_submit_organize_translates_effective_qb_save_path_before_authorization(
    automation,
):
    _, scheduler, submission, qb, policy = automation
    submission.resolve_save_path.return_value = r"D:\影视\未整理"
    submission.resolve_save_path.side_effect = None
    policy.policy = policy.policy.model_copy(update={
        "allowed_source_path_prefixes": ["/mnt/d/影视/未整理"],
    })
    service = DownloadAutomation(
        submission,
        qb,
        scheduler,
        policy,
        lambda: NOW,
        lambda: "mapped-download",
        ["/media"],
        path_mapping={"D:\\": "/mnt/d/"},
    )

    result = service.submit_downloads(
        [DownloadSubmissionRequest(torrent_id="123")],
        "organize",
        "session",
    )

    task = scheduler.get(result.items[0].watch_task_id)
    assert task is not None
    assert task.payload["save_path"] == "/mnt/d/影视/未整理"


def test_create_and_atomic_update_monitor(automation):
    service, scheduler, _, _, _ = automation
    created = service.create_monitor(
        DownloadMonitorRequest(
            torrent_hash="ABC", mode="once", on_completed="notify"
        ),
        "session",
        "approval-create",
    )
    assert created.start_at is None
    future = (NOW + timedelta(hours=2)).isoformat()
    updated = service.update_monitor(DownloadMonitorUpdate(
        task_id=created.task_id,
        start_at=future,
        mode="until_complete",
        on_completed="organize",
    ))
    assert updated.start_at == future
    assert updated.mode == "until_complete"
    assert updated.on_completed == "organize"
    task = scheduler.get(created.task_id)
    assert task.payload["authorization_snapshot"]["destination_root"] == "/media"


def test_one_active_monitor_per_torrent(automation):
    service, _, _, _, _ = automation
    request = DownloadMonitorRequest(
        torrent_hash="ABC", mode="once", on_completed="notify"
    )
    first = service.create_monitor(request, "session", "approval-1")
    same = service.create_monitor(request, "session", "approval-1")
    assert same.task_id == first.task_id
    with pytest.raises(DownloadAutomationError) as exc:
        service.create_monitor(request, "session", "approval-2")
    assert exc.value.code == "MONITOR_CONFLICT"
