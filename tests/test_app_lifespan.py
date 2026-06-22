"""Tests for the lifespan integration in ``app/main.py``.

Verifies:

1. ``task_runtime`` is created and attached to ``app.state``.
2. The runtime worker starts on lifespan startup and stops on shutdown.
3. ``reconcile_stale_initializing`` runs during startup.
4. Startup ordering: MCP pool initialised before the task runtime;
   shutdown ordering: task runtime stopped before the MCP pool is shut down.

Uses ``pytest.mark.asyncio`` and a real ``TaskRuntime`` with a temporary
database.  The MCP pool functions are mocked to avoid starting real server
processes.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

from app.domain.runtime_tasks import RuntimeTask, TaskStatus
from app.runtime.worker import TaskWorkerConfig
from app.storage.db import connect, ensure_schema, initialize_schema
from app.task_runtime import TaskRuntime, create_task_runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime(tmp_path: Path) -> TaskRuntime:
    """Create a real TaskRuntime backed by a temporary SQLite database.

    The worker is configured with a long tick interval so it does not
    interfere with test assertions.  The schema is initialised so the
    store is ready for use.
    """
    db_path = tmp_path / "runtime_tasks.db"
    ensure_schema(db_path)
    return create_task_runtime(
        db_path=db_path,
        config=TaskWorkerConfig(tick_seconds=300),  # never ticks in tests
    )


def _patch_deps(runtime: TaskRuntime | None = None) -> ExitStack:
    """Return an ``ExitStack`` that patches the three external dependencies
    of ``app.main._app_lifespan``.

    Usage::

        with _patch_deps(my_runtime):
            ...
    """
    stack = ExitStack()
    stack.enter_context(patch("app.main.init_mcp_pool", AsyncMock()))
    stack.enter_context(patch("app.main.shutdown_mcp_pool", AsyncMock()))
    stack.enter_context(
        patch("app.main.create_task_runtime", return_value=runtime or AsyncMock()),
    )
    return stack


# ===================================================================
# 1. task_runtime is created and attached to app.state
# ===================================================================


@pytest.mark.asyncio
async def test_task_runtime_attached_to_app_state(
    runtime: TaskRuntime,
) -> None:
    """During the lifespan ``yield``, ``app.state.task_runtime`` holds
    the instance returned by ``create_task_runtime``.
    """
    with _patch_deps(runtime):
        from app.main import _app_lifespan

        app = FastAPI()
        async with _app_lifespan(app):
            assert app.state.task_runtime is runtime


# ===================================================================
# 2. task_runtime starts and stops with the app
# ===================================================================


@pytest.mark.asyncio
async def test_task_runtime_starts_and_stops_with_app(
    runtime: TaskRuntime,
) -> None:
    """The runtime's worker loop is running during the lifespan yield and
    is stopped after the lifespan exits.
    """
    with _patch_deps(runtime):
        from app.main import _app_lifespan

        app = FastAPI()

        # During yield: worker should be active.
        # Note: ``start()`` is scheduled via ``create_task()`` inside the
        # lifespan, so we need to yield once for it to run.
        async with _app_lifespan(app):
            await asyncio.sleep(0)  # let the start() task execute
            assert runtime._worker_task is not None
            assert not runtime._worker_task.done()

        # After shutdown: worker must have been torn down.
        await asyncio.sleep(0.01)
        assert runtime._worker is None


# ===================================================================
# 3. reconcile_stale_initializing runs at startup
# ===================================================================


@pytest.mark.asyncio
async def test_reconcile_stale_initializing_called_at_startup(
    runtime: TaskRuntime,
) -> None:
    """``reconcile_stale_initializing()`` is invoked during the lifespan
    startup phase.  We verify by injecting a stale INITIALIZING task
    before the lifespan runs and checking it was failed afterwards.
    """
    # Manually insert a stale INITIALIZING task into the runtime's store.
    conn = connect(runtime.store._db_path)
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO runtime_tasks "
        "(task_id, kind, status, payload_json, created_at, updated_at) "
        "VALUES (?, ?, 'initializing', ?, ?, ?)",
        (
            "stale-initing-test",
            "test",
            json.dumps({}),
            "2020-01-01T00:00:00",
            "2020-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()

    with _patch_deps(runtime):
        from app.main import _app_lifespan

        app = FastAPI()
        async with _app_lifespan(app):
            # The stale task should have been failed by reconciliation.
            stale = runtime.store.get("stale-initing-test")
            assert stale is not None
            assert stale.status == TaskStatus.FAILED
            assert "stale_initialization" in (stale.error or {}).get("code", "")


# ===================================================================
# 4. Startup and shutdown ordering
# ===================================================================


@pytest.mark.asyncio
async def test_lifespan_startup_and_shutdown_order(
    tmp_path: Path,
) -> None:
    """Verify the call sequence:

    * Startup:  init_mcp_pool -> create_task_runtime -> reconcile -> start
    * Shutdown: stop -> shutdown_mcp_pool
    """
    call_sequence: list[str] = []

    async def track_init_mcp() -> None:
        call_sequence.append("init_mcp")

    async def track_shutdown_mcp() -> None:
        call_sequence.append("shutdown_mcp")

    # We need a real TaskRuntime so that reconcile_stale_initializing()
    # is a genuine synchronous call (not an event-loop coroutine).
    db_path = tmp_path / "runtime_tasks.db"
    ensure_schema(db_path)
    real_runtime = create_task_runtime(
        db_path=db_path,
        config=TaskWorkerConfig(tick_seconds=300),
    )

    # Wrap the methods we care about so they record into call_sequence.
    orig_reconcile = real_runtime.reconcile_stale_initializing
    orig_start = real_runtime.start
    orig_stop = real_runtime.stop

    def tracking_reconcile(*args: object, **kwargs: object) -> list[RuntimeTask]:
        call_sequence.append("reconcile")
        return orig_reconcile(*args, **kwargs)

    def tracking_start() -> object:
        """Record call synchronously and return the coroutine from ``orig_start``.

        The lifespan calls this inside ``asyncio.create_task(...)``, so the
        call is synchronous even though the coroutine body runs later.
        """
        call_sequence.append("start")
        return orig_start()  # returns a coroutine

    async def tracking_stop() -> None:
        call_sequence.append("stop")
        return await orig_stop()

    real_runtime.reconcile_stale_initializing = tracking_reconcile  # type: ignore[method-assign]
    real_runtime.start = tracking_start  # type: ignore[method-assign]
    real_runtime.stop = tracking_stop  # type: ignore[method-assign]

    with (
        patch("app.main.init_mcp_pool", track_init_mcp),
        patch("app.main.shutdown_mcp_pool", track_shutdown_mcp),
        patch("app.main.create_task_runtime", return_value=real_runtime),
    ):
        from app.main import _app_lifespan

        app = FastAPI()
        async with _app_lifespan(app):
            pass  # yield point -- all startup calls have been made

    # Check startup order (synchronous calls that happen before the yield).
    # ``start`` is scheduled via create_task so it might appear later;
    # we check the synchronous prefix.
    sync_prefix = [
        s for s in call_sequence
        if s in ("init_mcp", "reconcile")
    ]
    assert sync_prefix == ["init_mcp", "reconcile"], (
        f"Expected startup prefix [init_mcp, reconcile], got {sync_prefix}"
    )

    # ``start`` must have been called (the call itself is synchronous
    # even though its coroutine runs asynchronously).
    assert "start" in call_sequence, "start was never called"

    # Check shutdown suffix.
    shutdown_suffix = [
        s for s in call_sequence
        if s in ("stop", "shutdown_mcp")
    ]
    assert shutdown_suffix == ["stop", "shutdown_mcp"], (
        f"Expected shutdown suffix [stop, shutdown_mcp], got {shutdown_suffix}"
    )
