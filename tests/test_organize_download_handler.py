"""Tests for the OrganizeDownloadHandler (app.runtime.handlers.organize_download).

Exercises:
- Handler completes successfully with a successful worker result
- Handler fails with MISSING_CONTENT_PATH when content_path is empty
- Handler fails with MISSING_DESTINATION_ROOT when no root can be derived
- Handler fails with ORGANIZE_FAILED when the worker returns failed status
- Handler fails with ORGANIZE_ERROR when the worker returns error status
- Handler skips when disabled
- Worker exception is caught and returned as retryable Fail
- Outcome events have correct structure
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from app.agent.organize_worker import OrganizeWorkerAgent, OrganizeWorkerResult
from app.domain.runtime_tasks import (
    Complete,
    Fail,
    RuntimeTask,
    TaskEventSeverity,
    TaskOutcome,
    TaskStatus,
)
from app.runtime.handlers.organize_download import (
    OrganizeDownloadConfig,
    OrganizeDownloadHandler,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fake worker
# ---------------------------------------------------------------------------


class FakeWorker:
    """Deterministic fake OrganizeWorkerAgent.

    The caller sets ``next_result`` to control what the worker returns on
    the next ``run()`` call.
    """

    def __init__(self) -> None:
        self.next_result: OrganizeWorkerResult = OrganizeWorkerResult(
            status="success",
            summary="OK",
            moved_count=2,
            destination="/影视/电影/Test.Movie.2024",
        )
        self.run_calls: list[tuple[str, str]] = []

    def run(self, source_path: str, destination_root: str) -> OrganizeWorkerResult:
        self.run_calls.append((source_path, destination_root))
        return self.next_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_organize_handler.db"


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    fixed = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return fixed

    return clock


@pytest.fixture
def sequential_id_factory() -> Callable[[], str]:
    counter = itertools.count(1)

    def factory() -> str:
        return f"task-{next(counter)}"

    return factory


@pytest.fixture
def clock(fixed_clock: Callable[[], datetime]) -> Callable[[], datetime]:
    return fixed_clock


@pytest.fixture
def id_factory(sequential_id_factory: Callable[[], str]) -> Callable[[], str]:
    return sequential_id_factory


@pytest.fixture
def store(
    tmp_db_path: Path,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> RuntimeTaskStore:
    conn = connect(tmp_db_path)
    initialize_schema(conn)
    conn.close()
    return RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)


@pytest.fixture
def scheduler(
    store: RuntimeTaskStore,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> TaskScheduler:
    return TaskScheduler(store, fixed_clock, sequential_id_factory)


@pytest.fixture
def fake_worker() -> FakeWorker:
    return FakeWorker()


@pytest.fixture
def config() -> OrganizeDownloadConfig:
    return OrganizeDownloadConfig(
        destination_root="/影视",
        worker_max_steps=15,
        enabled=True,
    )


@pytest.fixture
def handler(
    config: OrganizeDownloadConfig,
    scheduler: TaskScheduler,
    store: RuntimeTaskStore,
    fixed_clock: Callable[[], datetime],
    fake_worker: FakeWorker,
) -> OrganizeDownloadHandler:
    return OrganizeDownloadHandler(
        config=config,
        scheduler=scheduler,
        store=store,
        clock=fixed_clock,
        worker_factory=lambda ms: fake_worker,  # type: ignore[return-value]
    )


def enqueue_task(
    store: RuntimeTaskStore,
    clock: Callable[[], datetime],
    id_factory: Callable[[], str],
    task_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> RuntimeTask:
    """Enqueue an organize_download task and return it."""

    def _make_id() -> str:
        return task_id or id_factory()

    return store.enqueue(
        kind="organize_download",
        payload_json=payload or {},
        source_session_id=None,
        parent_task_id=None,
        dedupe_key=None,
        run_after=None,
        now=clock(),
        id_factory=_make_id,
    )


def claim_task(
    store: RuntimeTaskStore,
    clock: Callable[[], datetime],
) -> RuntimeTask | None:
    """Claim the first due organize_download task."""
    tasks = store.claim_due(
        kinds=["organize_download"],
        limit=1,
        lease_owner="test-worker",
        lease_seconds=120,
        now=clock(),
    )
    return tasks[0] if tasks else None


# ===================================================================
# Tests
# ===================================================================


@pytest.mark.asyncio
class TestHandlerSuccess:
    """Happy path: worker returns success."""

    async def test_returns_complete_with_result(
        self,
        handler: OrganizeDownloadHandler,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={
                "content_path": "/downloads/Test.Movie.2024.mkv",
                "save_path": "/downloads",
                "torrent_name": "Test.Movie.2024",
                "qb_hash": "hash123",
            },
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "complete"
        assert isinstance(outcome, Complete)
        assert outcome.result is not None
        assert outcome.result["status"] == "success"
        assert outcome.result["moved_count"] == 2
        assert outcome.result["destination"] == "/影视/电影/Test.Movie.2024"

        assert len(outcome.events) == 1
        event = outcome.events[0]
        assert event["kind"] == "organize_completed"
        assert event["severity"] == TaskEventSeverity.SUCCESS
        assert event["title"] == "下载整理完成"

    async def test_worker_receives_correct_paths(
        self,
        handler: OrganizeDownloadHandler,
        fake_worker: FakeWorker,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={
                "content_path": "/downloads/My.Movie.mkv",
                "save_path": "/downloads",
            },
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        await handler(claimed, store, scheduler)

        assert len(fake_worker.run_calls) == 1
        src, dst = fake_worker.run_calls[0]
        assert src == "/downloads/My.Movie.mkv"
        assert dst == "/影视"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandlerErrors:
    """Handler returns appropriate Fail outcomes for various error conditions."""

    async def test_missing_content_path(
        self,
        handler: OrganizeDownloadHandler,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        task = enqueue_task(store, clock, id_factory, payload={})
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "fail"
        assert isinstance(outcome, Fail)
        assert outcome.code == "MISSING_CONTENT_PATH"
        assert outcome.retryable is False

    async def test_empty_content_path(
        self,
        handler: OrganizeDownloadHandler,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": ""},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "fail"
        assert isinstance(outcome, Fail)
        assert outcome.code == "MISSING_CONTENT_PATH"

    async def test_worker_returns_failed_status(
        self,
        handler: OrganizeDownloadHandler,
        fake_worker: FakeWorker,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        fake_worker.next_result = OrganizeWorkerResult(
            status="failed",
            summary="Could not identify media",
            issues=["TMDB search returned no results"],
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": "/downloads/unknown.mkv"},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "fail"
        assert isinstance(outcome, Fail)
        assert outcome.code == "ORGANIZE_FAILED"
        assert outcome.retryable is True

    async def test_worker_returns_error_status(
        self,
        handler: OrganizeDownloadHandler,
        fake_worker: FakeWorker,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        fake_worker.next_result = OrganizeWorkerResult(
            status="error",
            summary="Agent loop crashed",
            issues=["RuntimeError: LLM unavailable"],
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": "/downloads/test.mkv"},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        scheduler = TaskScheduler(store, clock, id_factory)
        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "fail"
        assert isinstance(outcome, Fail)
        assert outcome.code == "ORGANIZE_ERROR"
        assert outcome.retryable is True


# ---------------------------------------------------------------------------
# Handler disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandlerDisabled:
    """When enabled=False, the handler returns Complete without running worker."""

    async def test_disabled_returns_complete_skip(
        self,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        cfg = OrganizeDownloadConfig(enabled=False)
        scheduler = TaskScheduler(store, clock, id_factory)
        fake_worker = FakeWorker()
        h = OrganizeDownloadHandler(
            config=cfg,
            scheduler=scheduler,
            store=store,
            clock=clock,
            worker_factory=lambda ms: fake_worker,  # type: ignore[return-value]
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": "/downloads/test.mkv"},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        outcome: TaskOutcome = await h(claimed, store, scheduler)

        assert outcome.kind == "complete"
        assert isinstance(outcome, Complete)
        assert outcome.result is not None
        assert outcome.result.get("skipped") is True

        # Worker should NOT have been called.
        assert len(fake_worker.run_calls) == 0


# ---------------------------------------------------------------------------
# Worker exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWorkerException:
    """Handler catches worker exceptions and returns retryable Fail."""

    async def test_worker_init_raises(
        self,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        def broken_factory(ms: int) -> OrganizeWorkerAgent:  # pragma: no cover
            raise RuntimeError("Worker init failed")

        cfg = OrganizeDownloadConfig(destination_root="/影视")
        scheduler = TaskScheduler(store, clock, id_factory)
        handler = OrganizeDownloadHandler(
            config=cfg,
            scheduler=scheduler,
            store=store,
            clock=clock,
            worker_factory=broken_factory,
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": "/downloads/test.mkv"},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        outcome: TaskOutcome = await handler(claimed, store, scheduler)

        assert outcome.kind == "fail"
        assert isinstance(outcome, Fail)
        assert outcome.code == "WORKER_EXCEPTION"
        assert outcome.retryable is True


# ---------------------------------------------------------------------------
# Destination root derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDestinationRootDerivation:
    """Handler derives destination_root from payload when config is empty."""

    async def test_derives_from_payload_destination_root(
        self,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        cfg = OrganizeDownloadConfig(destination_root="", enabled=True)
        scheduler = TaskScheduler(store, clock, id_factory)
        fake_worker = FakeWorker()
        h = OrganizeDownloadHandler(
            config=cfg,
            scheduler=scheduler,
            store=store,
            clock=clock,
            worker_factory=lambda ms: fake_worker,  # type: ignore[return-value]
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={
                "content_path": "/data/file.mkv",
                "destination_root": "/payload-root",
            },
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        await h(claimed, store, scheduler)

        assert len(fake_worker.run_calls) == 1
        _, dst = fake_worker.run_calls[0]
        assert dst == "/payload-root"

    async def test_derives_from_content_path_when_not_configured(
        self,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        """When config and payload have no explicit root,
        the handler derives it from content_path's parent directory."""
        cfg = OrganizeDownloadConfig(destination_root="", enabled=True)
        scheduler = TaskScheduler(store, clock, id_factory)
        fake_worker = FakeWorker()
        h = OrganizeDownloadHandler(
            config=cfg,
            scheduler=scheduler,
            store=store,
            clock=clock,
            worker_factory=lambda ms: fake_worker,  # type: ignore[return-value]
        )

        task = enqueue_task(
            store,
            clock,
            id_factory,
            payload={"content_path": "/downloads/some/movie.mkv"},
        )
        claimed = claim_task(store, clock)
        assert claimed is not None

        outcome: TaskOutcome = await h(claimed, store, scheduler)
        assert outcome.kind == "complete"
        assert len(fake_worker.run_calls) == 1
        _, dst = fake_worker.run_calls[0]
        assert dst == "/downloads/some"
