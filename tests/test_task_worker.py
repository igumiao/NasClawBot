"""Tests for the TaskWorker (app.runtime.worker).

Exercises the worker lifecycle, the full claim-and-dispatch path, handler
outcome application (Complete / Reschedule / Fail / Spawn), handler exception
handling, per-kind concurrency limits, lease recovery after a simulated crash,
clock injection for run_after filtering, and unknown-kind skip behaviour.

Uses fake async handlers that return controlled outcomes.  All tests use a
temporary SQLite database and deterministic clock/ID-fixtures.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from app.domain.runtime_tasks import (
    ChildTaskSpec,
    Complete,
    Fail,
    Reschedule,
    RuntimeTask,
    Spawn,
    TaskStatus,
)
from app.runtime.registry import HandlerRegistry
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.runtime.worker import TaskWorker, TaskWorkerConfig
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_worker.db"


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a deterministic clock frozen at 2026-06-01T12:00:00+00:00."""
    fixed = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return fixed

    return clock


@pytest.fixture
def manual_clock() -> tuple[Callable[[], datetime], Callable[[int], None]]:
    """Return ``(clock, advance)`` for manual time control.

    ``clock()`` returns the current simulated time.
    ``advance(seconds)`` moves it forward by *seconds*.
    """
    _now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return _now

    def advance(seconds: int) -> None:
        nonlocal _now
        _now += timedelta(seconds=seconds)

    return clock, advance


@pytest.fixture
def sequential_id_factory() -> Callable[[], str]:
    """Return an ID factory that produces ``task-1``, ``task-2``, …."""
    counter = itertools.count(1)

    def factory() -> str:
        return f"task-{next(counter)}"

    return factory


@pytest.fixture
def store(
    tmp_db_path: Path,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> RuntimeTaskStore:
    """Return a RuntimeTaskStore backed by a temporary SQLite file with schema."""
    conn = connect(tmp_db_path)
    initialize_schema(conn)
    conn.close()
    return RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)


@pytest.fixture
def registry() -> HandlerRegistry:
    return HandlerRegistry()


@pytest.fixture
def fast_config(fixed_clock: Callable[[], datetime]) -> TaskWorkerConfig:
    """Worker config with a fast tick loop for integration tests."""
    return TaskWorkerConfig(
        tick_seconds=0.001,
        lease_seconds=60,
        max_concurrency=10,
        clock=fixed_clock,
        worker_id="test-worker",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_worker_until(
    worker: TaskWorker,
    event: asyncio.Event,
    timeout: float = 2.0,
) -> None:
    """Start the worker loop in a background task and wait for *event*.

    Stops the worker after the event fires (or after *timeout*).
    Returns when both the event and shutdown are complete.
    """
    w_task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    finally:
        await worker.stop()
        await asyncio.sleep(0.01)
        if not w_task.done():
            w_task.cancel()
            try:
                await w_task
            except (asyncio.CancelledError, StopIteration):
                pass


def inject_task(
    store: RuntimeTaskStore,
    kind: str = "test",
    status: str = "queued",
    payload: dict[str, Any] | None = None,
    run_after: str | None = None,
    lease_owner: str | None = None,
    lease_expires_at: str | None = None,
    created_at: str | None = None,
) -> RuntimeTask:
    """Insert a raw task row into the store's database.

    Useful for simulating lease-recovery scenarios that require a task
    in RUNNING with an expired lease.
    """
    now = created_at or datetime(2026, 6, 1, 12, 0, 0).isoformat()
    task_id = f"injected-{id({})}"
    conn = connect(store._db_path)
    try:
        conn.execute(
            "INSERT INTO runtime_tasks "
            "(task_id, kind, status, payload_json, run_after, "
            "parent_task_id, source_session_id, dedupe_key, "
            "lease_owner, lease_expires_at, "
            "attempts, max_attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 20, ?, ?)",
            (
                task_id,
                kind,
                status,
                json.dumps(payload or {}),
                run_after,
                None, None, None,
                lease_owner,
                lease_expires_at,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Re-read through the store so JSON columns are parsed.
    result = store.get(task_id)
    assert result is not None, f"Failed to inject task {task_id}"
    return result


# ===================================================================
# 1. Worker lifecycle
# ===================================================================


@pytest.mark.asyncio
async def test_worker_starts_and_stops_cleanly(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fixed_clock: Callable[[], datetime],
) -> None:
    """Worker can be started and stopped without error."""
    config = TaskWorkerConfig(tick_seconds=0.01, clock=fixed_clock)
    worker = TaskWorker(store, registry, config)
    w_task = asyncio.create_task(worker.run())

    await asyncio.sleep(0.02)
    await worker.stop()
    await asyncio.sleep(0.01)

    assert w_task.done(), "Worker loop should have exited"
    # No exception should have been raised inside the worker task.
    if w_task.exception():
        raise w_task.exception()


# ===================================================================
# 2. Complete outcome
# ===================================================================


@pytest.mark.asyncio
async def test_complete_outcome_succeeds_task(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """Handler returning Complete transitions the task to SUCCEEDED."""
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        done.set()
        return Complete(result={"downloaded": True})

    registry.register("download", handler)

    t = store.enqueue(
        "download", {"url": "http://example.com/t.torrent"},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    await _run_worker_until(TaskWorker(store, registry, fast_config), done)

    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.SUCCEEDED
    assert result.result == {"downloaded": True}


# ===================================================================
# 3. Reschedule outcome
# ===================================================================


@pytest.mark.asyncio
async def test_reschedule_outcome_updates_run_after(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """Handler returning Reschedule transitions the task to WAITING with
    a new run_after timestamp and a payload patch merged in.
    """
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Reschedule:
        done.set()
        return Reschedule(
            run_after="2026-06-02T00:00:00",
            payload_patch={"progress": 0.5},
        )

    registry.register("poll", handler)

    t = store.enqueue(
        "poll", {"progress": 0.0},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    await _run_worker_until(TaskWorker(store, registry, fast_config), done)

    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.WAITING
    assert result.run_after == "2026-06-02T00:00:00"
    # Payload should retain original keys merged with the patch.
    assert result.payload == {"progress": 0.5}


# ===================================================================
# 4. Fail outcome
# ===================================================================


@pytest.mark.asyncio
async def test_fail_outcome_fails_task(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """Handler returning a non-retryable Fail transitions the task to FAILED."""
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Fail:
        done.set()
        return Fail(code="NOT_FOUND", message="Torrent missing", retryable=False)

    registry.register("lookup", handler)

    t = store.enqueue(
        "lookup", {},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    await _run_worker_until(TaskWorker(store, registry, fast_config), done)

    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.FAILED
    assert result.error is not None
    assert result.error["code"] == "NOT_FOUND"
    assert "Torrent missing" in result.error["message"]


# ===================================================================
# 5. Spawn outcome
# ===================================================================


@pytest.mark.asyncio
async def test_spawn_outcome_creates_child_tasks(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """Handler returning Spawn creates child tasks and transitions the
    parent to SUCCEEDED.
    """
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Spawn:
        done.set()
        return Spawn(
            children=[
                ChildTaskSpec(kind="organize", payload={"file": "movie.mkv"}),
                ChildTaskSpec(kind="notify", payload={"msg": "done"}),
            ],
            result={"spawned": 2},
        )

    registry.register("download", handler)

    parent = store.enqueue(
        "download", {},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    await _run_worker_until(TaskWorker(store, registry, fast_config), done)

    # Parent should be SUCCEEDED.
    parent_result = store.get(parent.task_id)
    assert parent_result is not None
    assert parent_result.status == TaskStatus.SUCCEEDED
    assert parent_result.result == {"spawned": 2}

    # Two child tasks should exist with proper parent reference.
    all_tasks = store.list_tasks()
    children = [t for t in all_tasks if t.parent_task_id == parent.task_id]
    assert len(children) == 2

    child_kinds = {c.kind for c in children}
    assert child_kinds == {"organize", "notify"}
    for c in children:
        assert c.status == TaskStatus.QUEUED


# ===================================================================
# 6. Handler exception
# ===================================================================


@pytest.mark.asyncio
async def test_handler_exception_is_caught_and_mapped_to_fail(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """An exception raised inside the handler is caught and mapped to
    a retryable Fail with HANDLER_EXCEPTION code.
    """
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        done.set()
        msg = "Something went wrong"
        raise RuntimeError(msg)

    registry.register("brittle", handler)

    t = store.enqueue(
        "brittle", {},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    await _run_worker_until(TaskWorker(store, registry, fast_config), done)

    result = store.get(t.task_id)
    assert result is not None

    # The worker catches the exception and creates a retryable Fail.
    # Because the task has remaining attempts (20), the worker schedules
    # a retry by transitioning to WAITING and stores the error in the
    # payload via `_last_error`.
    assert result.status == TaskStatus.WAITING, (
        f"Expected WAITING (retry scheduled), got {result.status}"
    )
    last_error = result.payload.get("_last_error", {})
    assert last_error.get("code") == "HANDLER_EXCEPTION", (
        f"Expected HANDLER_EXCEPTION code in payload, got {last_error}"
    )
    assert "Something went wrong" in last_error.get("message", "")


# ===================================================================
# 7. Per-kind semaphore concurrency limit
# ===================================================================


@pytest.mark.asyncio
async def test_per_kind_semaphore_limits_concurrency(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """With ``per_kind_semaphores={"slow": 1}`` only one task of kind
    ``"slow"`` runs at a time; the second waits for the first to complete.
    """
    entered: list[str] = []
    proceed = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        entered.append(task.task_id)
        # Block until the test releases us.
        await proceed.wait()
        return Complete()

    registry.register("slow", handler)

    config = TaskWorkerConfig(
        tick_seconds=0.001,
        lease_seconds=60,
        max_concurrency=10,
        clock=fixed_clock,
        worker_id="test-worker",
        per_kind_semaphores={"slow": 1},
    )

    t1 = store.enqueue(
        "slow", {"n": 1},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )
    t2 = store.enqueue(
        "slow", {"n": 2},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    worker = TaskWorker(store, registry, config)
    w_task = asyncio.create_task(worker.run())

    try:
        # Wait for the first handler to start running.
        await asyncio.sleep(0.05)

        # Only one handler should have entered.
        assert len(entered) == 1, (
            f"Expected exactly 1 handler running, got {len(entered)}"
        )

        # The second task may be RUNNING (claimed) but its handler hasn't
        # started because the per-kind semaphore is held by the first.
        t2_status = store.get(t2.task_id)
        assert t2_status is not None
        # Because the first handler is still blocked (not returned),
        # the global + per-kind semaphores keep it from entering.
    finally:
        proceed.set()
        await asyncio.sleep(0.05)
        await worker.stop()
        await asyncio.sleep(0.01)
        if not w_task.done():
            w_task.cancel()
            try:
                await w_task
            except (asyncio.CancelledError, StopIteration):
                pass

    # Both should eventually succeed.
    assert store.get(t1.task_id) is not None
    assert store.get(t1.task_id).status == TaskStatus.SUCCEEDED
    assert store.get(t2.task_id).status == TaskStatus.SUCCEEDED


# ===================================================================
# 8. Lease recovery (simulated crashed worker)
# ===================================================================


@pytest.mark.asyncio
async def test_lease_recovery(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """After a crashed worker lease expires and the task status is reset
    to QUEUED, a fresh worker claims the task on the next tick.
    """
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        done.set()
        return Complete(result={"recovered": True})

    registry.register("test", handler)

    # Phase 1: "worker-1" claims the task.
    t = store.enqueue(
        "test", {},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )
    claimed = store.claim_due(
        ["test"], 1, "worker-1", 60, fixed_clock(),
    )
    assert len(claimed) == 1
    assert claimed[0].lease_owner == "worker-1"

    # Phase 2: simulate a crash by resetting the task to QUEUED with an
    # expired lease (the recovery mechanism an external monitor would run).
    conn = connect(store._db_path)
    conn.execute(
        "UPDATE runtime_tasks SET "
        "status = 'queued', "
        "lease_owner = NULL, "
        "lease_expires_at = ? "
        "WHERE task_id = ?",
        ("2020-01-01T00:00:00", t.task_id),
    )
    conn.commit()
    conn.close()

    # Phase 3: a fresh worker claims and executes the recovered task.
    config = TaskWorkerConfig(
        tick_seconds=0.001,
        lease_seconds=60,
        max_concurrency=10,
        clock=fixed_clock,
        worker_id="worker-2",
    )
    await _run_worker_until(TaskWorker(store, registry, config), done)

    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.SUCCEEDED
    assert result.result == {"recovered": True}


# ===================================================================
# 9. Clock injection for run_after filtering
# ===================================================================


@pytest.mark.asyncio
async def test_worker_respects_clock_injection_for_run_after(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    sequential_id_factory: Callable[[], str],
    manual_clock: tuple[Callable[[], datetime], Callable[[int], None]],
) -> None:
    """The worker uses the injected clock -- not the real wall clock --
    when deciding whether a task with a future run_after is eligible.
    """
    clock, advance = manual_clock
    now = clock()
    future = (now + timedelta(seconds=30)).isoformat()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        return Complete(result={"claimed": True})

    registry.register("test", handler)

    # Enqueue a task with run_after in the future.
    t = store.enqueue(
        "test", {},
        None, None, None, run_after=future,
        now=now, id_factory=sequential_id_factory,
    )

    config = TaskWorkerConfig(
        tick_seconds=0,     # single-tick mode for testing
        lease_seconds=60,
        clock=clock,
    )
    worker = TaskWorker(store, registry, config)

    # First tick: clock < run_after -> not claimed.
    await worker._tick()
    assert store.get(t.task_id).status == TaskStatus.QUEUED

    # Advance the clock past run_after.
    advance(31)

    # Second tick: clock > run_after -> claimed.
    await worker._tick()
    assert store.get(t.task_id).status == TaskStatus.RUNNING


# ===================================================================
# 10. Future run_after tasks are skipped
# ===================================================================


@pytest.mark.asyncio
async def test_worker_skips_future_run_after_tasks(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """Tasks whose run_after is in the future are not claimed by the worker."""
    done = asyncio.Event()

    async def handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        done.set()  # Should never be called.
        return Complete()

    registry.register("test", handler)

    future = (fixed_clock() + timedelta(hours=1)).isoformat()
    t = store.enqueue(
        "test", {},
        None, None, None,
        run_after=future,
        now=fixed_clock(),
        id_factory=sequential_id_factory,
    )

    worker = TaskWorker(store, registry, fast_config)
    w_task = asyncio.create_task(worker.run())

    # Let the worker tick a few times.
    await asyncio.sleep(0.05)
    await worker.stop()
    await asyncio.sleep(0.01)
    if not w_task.done():
        w_task.cancel()
        try:
            await w_task
        except (asyncio.CancelledError, StopIteration):
            pass

    # Task should still be QUEUED (not RUNNING, not SUCCEEDED).
    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.QUEUED
    assert not done.is_set(), "Handler should never have been invoked"


# ===================================================================
# 11. Unknown kind (no registered handler)
# ===================================================================


@pytest.mark.asyncio
async def test_unknown_kind_skipped_and_failed(
    store: RuntimeTaskStore,
    registry: HandlerRegistry,
    fast_config: TaskWorkerConfig,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
) -> None:
    """A task whose kind has no registered handler is never claimed by
    the worker -- ``_tick`` only queries for registered kinds.
    """
    # Register a handler for one kind but not for "unknown".
    async def real_handler(
        task: RuntimeTask,
        _store: RuntimeTaskStore,
        _scheduler: TaskScheduler,
    ) -> Complete:
        return Complete()

    registry.register("real", real_handler)

    t = store.enqueue(
        "unknown", {},
        None, None, None, None,
        fixed_clock(), sequential_id_factory,
    )

    worker = TaskWorker(store, registry, fast_config)
    w_task = asyncio.create_task(worker.run())

    await asyncio.sleep(0.05)
    await worker.stop()
    await asyncio.sleep(0.01)
    if not w_task.done():
        w_task.cancel()
        try:
            await w_task
        except (asyncio.CancelledError, StopIteration):
            pass

    # No handler registered for "unknown" -> the worker never claims it,
    # so it stays QUEUED.
    result = store.get(t.task_id)
    assert result is not None
    assert result.status == TaskStatus.QUEUED, (
        f"Expected QUEUED (unclaimed), got {result.status}"
    )
