"""Authorization and execution tests for OrganizeDownloadHandler."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.agent.organize_worker import OrganizeWorkerResult
from app.domain.organization import OrganizationAuthorizationPolicy
from app.domain.runtime_tasks import Complete, Fail, RuntimeTask, TaskStatus
from app.runtime.handlers.organize_download import (
    OrganizeDownloadConfig,
    OrganizeDownloadHandler,
)


NOW = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.result = OrganizeWorkerResult(
            status="success",
            summary="organized",
            moved_count=1,
            destination="/media/Test",
        )

    def run(self, source_path: str, destination_root: str, qb_hash: str = "") -> OrganizeWorkerResult:
        self.calls.append((source_path, destination_root, qb_hash))
        return self.result


class FakePolicyStore:
    def __init__(self, policy: OrganizationAuthorizationPolicy | Exception) -> None:
        self.policy = policy

    def load(self) -> OrganizationAuthorizationPolicy:
        if isinstance(self.policy, Exception):
            raise self.policy
        return self.policy


def policy(
    *,
    allowed: bool = True,
    prefixes: list[str] | None = None,
    destination: str = "/media",
) -> OrganizationAuthorizationPolicy:
    return OrganizationAuthorizationPolicy(
        background_organization_allowed=allowed,
        allowed_source_path_prefixes=prefixes or ["/downloads"],
        destination_root=destination,
    )


def task(
    *,
    content_path: str = "/downloads/Test.mkv",
    snapshot: dict[str, Any] | None = None,
) -> RuntimeTask:
    payload: dict[str, Any] = {
        "qb_hash": "abc",
        "torrent_name": "Test",
        "content_path": content_path,
        "save_path": "/downloads",
    }
    if snapshot is not None:
        payload["authorization_snapshot"] = snapshot
    return RuntimeTask(
        task_id="organize-1",
        kind="organize_download",
        status=TaskStatus.RUNNING,
        payload=payload,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )


def snapshot(
    *,
    prefixes: list[str] | None = None,
    destination: str = "/media",
) -> dict[str, Any]:
    return {
        "background_organization_allowed": True,
        "allowed_source_path_prefixes": prefixes or ["/downloads"],
        "destination_root": destination,
        "allow_delete": False,
        "allow_overwrite": False,
    }


def handler(
    worker: FakeWorker,
    current_policy: OrganizationAuthorizationPolicy | Exception | None,
) -> OrganizeDownloadHandler:
    store = None if current_policy is None else FakePolicyStore(current_policy)
    return OrganizeDownloadHandler(
        config=OrganizeDownloadConfig(enabled=True),
        scheduler=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        clock=lambda: NOW,
        worker_factory=lambda _: worker,  # type: ignore[return-value]
        organization_policy_store=store,
    )


@pytest.mark.asyncio
async def test_authorized_snapshot_runs_worker() -> None:
    worker = FakeWorker()
    outcome = await handler(worker, policy())(
        task(snapshot=snapshot()), None, None  # type: ignore[arg-type]
    )
    assert isinstance(outcome, Complete)
    assert worker.calls == [("/downloads/Test.mkv", "/media", "abc")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "snap", "content_path", "code"),
    [
        (policy(), None, "/downloads/Test.mkv", "ORGANIZE_AUTHORIZATION_MISSING"),
        (None, snapshot(), "/downloads/Test.mkv", "ORGANIZE_POLICY_UNAVAILABLE"),
        (RuntimeError("read failed"), snapshot(), "/downloads/Test.mkv", "ORGANIZE_POLICY_UNAVAILABLE"),
        (policy(allowed=False), snapshot(), "/downloads/Test.mkv", "ORGANIZE_POLICY_DISABLED"),
        (policy(prefixes=["/downloads/tv"]), snapshot(), "/downloads/Test.mkv", "ORGANIZE_SOURCE_SCOPE_REVOKED"),
        (policy(prefixes=["/"]), snapshot(prefixes=["/downloads/tv"]), "/downloads/Test.mkv", "ORGANIZE_SOURCE_SCOPE_REVOKED"),
        (policy(destination="/media-new"), snapshot(), "/downloads/Test.mkv", "ORGANIZE_DESTINATION_MISMATCH"),
    ],
)
async def test_revalidation_fails_closed_before_worker(
    current: OrganizationAuthorizationPolicy | Exception | None,
    snap: dict[str, Any] | None,
    content_path: str,
    code: str,
) -> None:
    worker = FakeWorker()
    outcome = await handler(worker, current)(
        task(content_path=content_path, snapshot=snap), None, None  # type: ignore[arg-type]
    )
    assert isinstance(outcome, Fail)
    assert outcome.code == code
    assert outcome.retryable is False
    assert worker.calls == []


@pytest.mark.asyncio
async def test_current_narrowing_allows_source_inside_both_scopes() -> None:
    worker = FakeWorker()
    outcome = await handler(
        worker, policy(prefixes=["/downloads/movies"])
    )(
        task(
            content_path="/downloads/movies/Test.mkv",
            snapshot=snapshot(prefixes=["/downloads"]),
        ),
        None,
        None,
    )  # type: ignore[arg-type]
    assert isinstance(outcome, Complete)
    assert len(worker.calls) == 1


@pytest.mark.asyncio
async def test_legacy_snapshot_keys_are_normalized() -> None:
    worker = FakeWorker()
    legacy = {
        "enabled": True,
        "allowed_source_prefixes": ["/downloads"],
        "destination_root": "/media",
    }
    outcome = await handler(worker, policy())(
        task(snapshot=legacy), None, None  # type: ignore[arg-type]
    )
    assert isinstance(outcome, Complete)
    assert len(worker.calls) == 1


@pytest.mark.asyncio
async def test_worker_failure_is_preserved_after_authorization() -> None:
    worker = FakeWorker()
    worker.result = OrganizeWorkerResult(
        status="failed", summary="could not identify media"
    )
    outcome = await handler(worker, policy())(
        task(snapshot=snapshot()), None, None  # type: ignore[arg-type]
    )
    assert isinstance(outcome, Fail)
    assert outcome.code == "ORGANIZE_FAILED"
    assert outcome.retryable is True
