"""Integration tests for the full download supervision lifecycle.

Exercises the complete path from scheduler.enqueue through handler execution
to terminal state, including restart recovery from WAITING and terminal-state
idempotency.

Uses:
- FakeQBAdapter (dict-backed) for qB state
- Temporary SQLite database for RuntimeTaskStore
- Deterministic clock and manual time advancement
- Real DownloadWatchHandler registered with a real TaskWorker
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from app.domain.runtime_tasks import (
    Complete,
    Fail,
    Reschedule,
    RuntimeTask,
    Spawn,
    TaskEventSeverity,
    TaskOutcome,
    TaskStatus,
)
from app.runtime.handlers.download_watch import (
    CONSECUTIVE_MISSES_THRESHOLD,
    DownloadWatchConfig,
    DownloadWatchHandler,
)
from app.runtime.registry import HandlerRegistry
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.runtime.worker import TaskWorker, TaskWorkerConfig
from app.storage.db import connect, initialize_schema


LEGACY_FOLLOW_UP_NOTIFY_ONLY = "notify_only"


# ---------------------------------------------------------------------------
# Fake qB adapter
# ---------------------------------------------------------------------------


class FakeQBAdapter:
    """In-memory fake qBittorrent adapter for integration tests."""

    def __init__(
        self,
        torrents_by_tag: dict[str, list[dict[str, Any]]] | None = None,
        torrents_by_hash: dict[str, dict[str, Any] | None] | None = None,
    ) -> None:
        self.torrents_by_tag = dict(torrents_by_tag or {})
        self.torrents_by_hash = dict(torrents_by_hash or {})
        self.fail_list_torrents: Exception | None = None
        self.fail_get_torrent: Exception | None = None

    def list_torrents(self, *, tag: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        if self.fail_list_torrents is not None:
            raise self.fail_list_torrents
        if tag is None:
            return [v for v in self.torrents_by_hash.values() if v is not None]
        return list(self.torrents_by_tag.get(tag, []))

    def get_torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        if self.fail_get_torrent is not None:
            raise self.fail_get_torrent
        return self.torrents_by_hash.get(torrent_hash)


def make_torrent(
    qb_hash: str,
    name: str = "Test.Torrent",
    progress: float = 0.0,
    state: str = "pausedDL",
    save_path: str = "/downloads",
    content_path: str = "",
) -> dict[str, Any]:
    content = content_path or f"{save_path}/{name}"
    return {
        "hash": qb_hash,
        "name": name,
        "progress": progress,
        "state": state,
        "save_path": save_path,
        "content_path": content,
        "tags": [],
        "category": "",
        "size": 1024 * 1024,
        "total_size": 1024 * 1024,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_supervision.db"


@pytest.fixture
def manual_clock() -> tuple[Callable[[], datetime], Callable[[int], None]]:
    _now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return _now

    def advance(seconds: int) -> None:
        nonlocal _now
        _now += timedelta(seconds=seconds)

    return clock, advance


@pytest.fixture
def sequential_id_factory() -> Callable[[], str]:
    counter = itertools.count(1)

    def factory() -> str:
        return f"task-{next(counter)}"

    return factory


@pytest.fixture
def store(
    tmp_db_path: Path,
    manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
    sequential_id_factory: Callable[[], str],
) -> RuntimeTaskStore:
    clock, _ = manual_clock
    conn = connect(tmp_db_path)
    initialize_schema(conn)
    conn.close()
    return RuntimeTaskStore(tmp_db_path, clock, sequential_id_factory)


@pytest.fixture
def registry() -> HandlerRegistry:
    return HandlerRegistry()


@pytest.fixture
def qb_adapter() -> FakeQBAdapter:
    return FakeQBAdapter()


@pytest.fixture
def handler(
    qb_adapter: FakeQBAdapter,
    store: RuntimeTaskStore,
    manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
) -> DownloadWatchHandler:
    clock, _ = manual_clock
    config = DownloadWatchConfig(poll_seconds=30, error_backoff_max=600)
    scheduler = TaskScheduler(store, clock, lambda: "sid-1")
    return DownloadWatchHandler(qb_adapter, config, scheduler, store, clock)


# ===================================================================
# 1. Full path: scheduler.enqueue -> handler execution -> terminal
# ===================================================================


class TestFullPathNotifyOnly:
    """From scheduler.enqueue through worker execution to SUCCEEDED."""

    @pytest.mark.asyncio
    async def test_full_notify_only_path_to_succeeded(
        self,
        tmp_db_path: Path,
        manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Enqueue a download_watch task, let the worker run, verify terminal.

        Flow:
        1. Seed qB with a torrent tagged with nasclaw-task-{id}.
        2. Enqueue a download_watch task with no qb_hash (simulates freshly
           submitted watch task).
        3. Register the real DownloadWatchHandler.
        4. Run the worker for ticks, advancing the clock past run_after.
        5. Verify the task reaches SUCCEEDED with correct result + events.
        """
        clock, advance = manual_clock
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        store = RuntimeTaskStore(tmp_db_path, clock, sequential_id_factory)
        registry = HandlerRegistry()
        qb = FakeQBAdapter()

        task_id = "watch-integration-1"
        qb_hash = "hash-integ-1"
        correlation_tag = f"nasclaw-task-{task_id}"

        # Seed qB: one torrent matching the correlation tag, at 100%
        qb.torrents_by_tag[correlation_tag] = [
            make_torrent(
                qb_hash, "Integration.Movie", progress=1.0, state="completed",
                content_path="/downloads/Integration.Movie.mkv",
            ),
        ]
        qb.torrents_by_hash[qb_hash] = make_torrent(
            qb_hash, "Integration.Movie", progress=1.0, state="completed",
            content_path="/downloads/Integration.Movie.mkv",
        )

        # Register the handler
        config = DownloadWatchConfig(poll_seconds=30, error_backoff_max=600)
        scheduler = TaskScheduler(store, clock, sequential_id_factory)
        watch_handler = DownloadWatchHandler(qb, config, scheduler, store, clock)
        registry.register("download_watch", watch_handler)

        # Enqueue a download_watch task with notify_only follow-up
        task = store.enqueue(
            kind="download_watch",
            payload_json={
                "torrent_id": "mteam-123",
                "resolved_follow_up": {
                    "mode": LEGACY_FOLLOW_UP_NOTIFY_ONLY,
                },
            },
            source_session_id="session-int-1",
            parent_task_id=None,
            dedupe_key=None,
            run_after=None,  # immediately eligible
            now=clock(),
            id_factory=lambda: task_id,
        )
        assert task.status == TaskStatus.QUEUED

        # Worker config: single-tick to avoid infinite loop
        worker_config = TaskWorkerConfig(
            tick_seconds=0,
            lease_seconds=60,
            max_concurrency=10,
            clock=clock,
            worker_id="test-worker-integ",
        )
        worker = TaskWorker(store, registry, worker_config)

        # Tick 1: no qb_hash yet -> resolves hash -> Reschedule (WAITING).
        # The handler runs async via ensure_future, so yield to event loop.
        await worker._tick()
        await asyncio.sleep(0.02)

        t1 = store.get(task_id)
        assert t1 is not None
        assert t1.payload.get("qb_hash") == qb_hash, (
            f"Hash should be resolved, got {t1.payload.get('qb_hash')}"
        )
        assert t1.status == TaskStatus.WAITING, f"Expected WAITING, got {t1.status}"

        # Advance clock past run_after so the task is eligible again
        advance(31)

        # Tick 2: progress=1.0 -> Complete
        await worker._tick()
        await asyncio.sleep(0.02)

        t2 = store.get(task_id)
        assert t2 is not None
        assert t2.status == TaskStatus.SUCCEEDED, f"Expected SUCCEEDED, got {t2.status}"
        assert t2.result is not None
        assert t2.result.get("qb_hash") == qb_hash
        assert t2.result.get("torrent_name") == "Integration.Movie"
        assert t2.result.get("content_path") == "/downloads/Integration.Movie.mkv"

        # Verify a download_completed event was created
        events = store.get_events_for_session("session-int-1")
        assert len(events) >= 1
        completed_events = [e for e in events if e.kind == "download_completed"]
        assert len(completed_events) >= 1, "Expected at least one download_completed event"


# ===================================================================
# 2. Restart recovery from WAITING state
# ===================================================================


class TestRestartRecovery:
    """Simulate a process restart while a download_watch task is in WAITING.

    After restart:
    - The task remains in WAITING with its resolved qb_hash.
    - A fresh worker claims it when run_after is due.
    - The handler polls the (now-complete) torrent and transitions to SUCCEEDED.
    """

    @pytest.mark.asyncio
    async def test_recover_from_waitting_after_restart(
        self,
        tmp_db_path: Path,
        manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        clock, advance = manual_clock
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        store = RuntimeTaskStore(tmp_db_path, clock, sequential_id_factory)
        qb = FakeQBAdapter()
        scheduler = TaskScheduler(store, clock, sequential_id_factory)

        qb_hash = "hash-recover-1"

        # Phase 1: "pre-restart" — task exists in WAITING with resolved qb_hash.
        # Must go through RUNNING first since reschedule only accepts RUNNING->WAITING.
        pre_task = store.enqueue(
            kind="download_watch",
            payload_json={
                "qb_hash": qb_hash,
                "torrent_name": "Recovery.Movie",
                "save_path": "/downloads",
                "consecutive_misses": 0,
                "consecutive_errors": 0,
                "last_poll_at": clock().isoformat(),
                "resolved_follow_up": {
                    "mode": LEGACY_FOLLOW_UP_NOTIFY_ONLY,
                },
            },
            source_session_id="session-recover-1",
            parent_task_id=None,
            dedupe_key=None,
            run_after=None,  # immediately eligible so claim_due can pick it up
            now=clock(),
            id_factory=lambda: "task-recover-1",
        )

        # Claim it (QUEUED -> RUNNING) then reschedule (RUNNING -> WAITING)
        claimed = store.claim_due(["download_watch"], 1, "pre-worker", 60, clock())
        assert len(claimed) == 1

        store.reschedule(
            task_id=pre_task.task_id,
            run_after=(clock() + timedelta(seconds=10)).isoformat(),
            payload_patch=None,
            now=clock(),
        )
        pre_status = store.get("task-recover-1")
        assert pre_status is not None
        assert pre_status.status == TaskStatus.WAITING

        # Phase 2: "post-restart" — seed qB with the completed torrent
        qb.torrents_by_hash[qb_hash] = make_torrent(
            qb_hash, "Recovery.Movie", progress=1.0, state="completed",
            content_path="/downloads/Recovery.Movie.mkv",
        )

        # Phase 3: Start a fresh worker (simulates restart)
        registry = HandlerRegistry()
        config = DownloadWatchConfig(poll_seconds=30, error_backoff_max=600)
        watch_handler = DownloadWatchHandler(qb, config, scheduler, store, clock)
        registry.register("download_watch", watch_handler)

        worker_config = TaskWorkerConfig(
            tick_seconds=0,
            lease_seconds=60,
            max_concurrency=10,
            clock=clock,
            worker_id="test-worker-recover",
        )
        worker = TaskWorker(store, registry, worker_config)

        # Tick 1: task is WAITING but run_after is still in the future
        await worker._tick()
        await asyncio.sleep(0.01)

        t1 = store.get("task-recover-1")
        assert t1 is not None
        assert t1.status == TaskStatus.WAITING

        # Advance clock past run_after
        advance(11)

        # Tick 2: worker should claim the task, handler runs async
        await worker._tick()
        await asyncio.sleep(0.02)

        t2 = store.get("task-recover-1")
        assert t2 is not None
        assert t2.status == TaskStatus.SUCCEEDED, (
            f"Expected SUCCEEDED after recovery, got {t2.status}"
        )
        assert t2.result is not None
        assert t2.result["qb_hash"] == qb_hash

        events = store.get_events_for_session("session-recover-1")
        completed_events = [e for e in events if e.kind == "download_completed"]
        assert len(completed_events) >= 1, "Recovery should produce download_completed event"


# ===================================================================
# 3. Terminal state idempotency
# ===================================================================


class TestTerminalIdempotency:
    """Once a task reaches a terminal state (SUCCEEDED/FAILED), the worker
    should not re-claim or re-execute it.

    This is enforced by the store's claim_due which only claims QUEUED/WAITING
    tasks.
    """

    @pytest.mark.asyncio
    async def test_succeeded_task_not_reclaimed(
        self,
        tmp_db_path: Path,
        manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """A SUCCEEDED task is not claimed by the worker on subsequent ticks.

        The store's claim_due only returns QUEUED/WAITING tasks, so a terminal
        task is never passed to a handler.
        """
        clock, advance = manual_clock
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        store = RuntimeTaskStore(tmp_db_path, clock, sequential_id_factory)

        # Create a task that is already SUCCEEDED.
        # Must go through claim_due -> finish since finish only accepts RUNNING.
        task = store.enqueue(
            kind="download_watch",
            payload_json={"qb_hash": "hash-done", "resolved_follow_up": {"mode": LEGACY_FOLLOW_UP_NOTIFY_ONLY}},
            source_session_id="session-term-1",
            parent_task_id=None,
            dedupe_key=None,
            run_after=None,
            now=clock(),
            id_factory=lambda: "task-term-1",
        )

        # Claim it (QUEUED -> RUNNING)
        claimed = store.claim_due(["download_watch"], 1, "setup-worker", 60, clock())
        assert len(claimed) == 1

        # Transition to SUCCEEDED (RUNNING -> SUCCEEDED)
        store.finish(
            task_id=task.task_id,
            status=TaskStatus.SUCCEEDED,
            result_json={"qb_hash": "hash-done"},
            error_json=None,
            now=clock(),
        )

        t = store.get("task-term-1")
        assert t is not None
        assert t.status == TaskStatus.SUCCEEDED

        # Register a handler that should never be called
        handler_called = False

        async def should_not_be_called(
            _task: RuntimeTask,
            _store: RuntimeTaskStore,
            _scheduler: TaskScheduler,
        ) -> TaskOutcome:
            nonlocal handler_called
            handler_called = True
            return Complete()

        registry = HandlerRegistry()
        registry.register("download_watch", should_not_be_called)

        worker_config = TaskWorkerConfig(
            tick_seconds=0,
            lease_seconds=60,
            max_concurrency=10,
            clock=clock,
            worker_id="test-worker-term",
        )
        worker = TaskWorker(store, registry, worker_config)

        # Tick multiple times
        for _ in range(3):
            await worker._tick()
            await asyncio.sleep(0.01)

        assert not handler_called, "Handler should not be called for a terminal task"

    @pytest.mark.asyncio
    async def test_failed_task_not_reclaimed(
        self,
        tmp_db_path: Path,
        manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """A FAILED task is not claimed by the worker on subsequent ticks."""
        clock, advance = manual_clock
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        store = RuntimeTaskStore(tmp_db_path, clock, sequential_id_factory)

        task = store.enqueue(
            kind="download_watch",
            payload_json={},
            source_session_id=None,
            parent_task_id=None,
            dedupe_key=None,
            run_after=None,
            now=clock(),
            id_factory=lambda: "task-term-fail",
        )

        # Claim it (QUEUED -> RUNNING)
        claimed = store.claim_due(["download_watch"], 1, "setup-worker", 60, clock())
        assert len(claimed) == 1

        # Transition to FAILED (RUNNING -> FAILED)
        store.finish(
            task_id="task-term-fail",
            status=TaskStatus.FAILED,
            result_json=None,
            error_json={"code": "QB_TORRENT_MISSING", "message": "Gone"},
            now=clock(),
        )

        t = store.get("task-term-fail")
        assert t is not None
        assert t.status == TaskStatus.FAILED

        handler_called = False

        async def should_not_be_called(
            _task: RuntimeTask,
            _store: RuntimeTaskStore,
            _scheduler: TaskScheduler,
        ) -> TaskOutcome:
            nonlocal handler_called
            handler_called = True
            return Complete()

        registry = HandlerRegistry()
        registry.register("download_watch", should_not_be_called)

        worker_config = TaskWorkerConfig(
            tick_seconds=0,
            lease_seconds=60,
            max_concurrency=10,
            clock=clock,
            worker_id="test-worker-term",
        )
        worker = TaskWorker(store, registry, worker_config)

        for _ in range(3):
            await worker._tick()
            await asyncio.sleep(0.01)

        assert not handler_called, "Handler should not be called for a terminal task"
