"""Tests for the TaskScheduler wrapper (app.runtime.scheduler).

Verifies that every exposed method delegates correctly to RuntimeTaskStore
with the right parameter renaming (payload -> payload_json, error -> error_json),
that clock and id_factory are injected automatically, and that worker-facing
methods are NOT exposed on the scheduler class.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from app.domain.runtime_tasks import RuntimeTask, TaskStatus
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Generate a temporary SQLite database path unique to each test."""
    return tmp_path / "test_scheduler.db"


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a deterministic clock frozen at 2026-06-01T12:00:00+00:00."""
    fixed = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return fixed

    return clock


@pytest.fixture
def sequential_id_factory() -> Callable[[], str]:
    """Return an ID factory that produces sequential strings (task-1, task-2, ...)."""
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
    """Return a RuntimeTaskStore backed by a temporary SQLite file."""
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
    """Return a TaskScheduler wrapping the store with the same clock and ID factory."""
    return TaskScheduler(store, fixed_clock, sequential_id_factory)


# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------


class TestPrepare:
    """scheduler.prepare delegates to store.prepare with correct parameter mapping."""

    def test_prepare_returns_initializing_task(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test", {"key": "val"}, "session-1", None, None)
        assert task.status == TaskStatus.INITIALIZING
        assert task.kind == "test"
        assert task.payload == {"key": "val"}
        assert task.source_session_id == "session-1"

    def test_prepare_without_optional_params(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        assert task.status == TaskStatus.INITIALIZING
        assert task.payload == {}
        assert task.source_session_id is None
        assert task.parent_task_id is None
        assert task.dedupe_key is None

    def test_prepare_with_dedupe_key(self, scheduler: TaskScheduler) -> None:
        t1 = scheduler.prepare("test", {"x": 1}, None, None, "dedupe:abc")
        t2 = scheduler.prepare("test", {"x": 2}, None, None, "dedupe:abc")
        assert t2.task_id == t1.task_id
        assert t2.payload == {"x": 1}

    def test_prepare_with_parent_task(self, scheduler: TaskScheduler) -> None:
        parent = scheduler.prepare("parent", {}, None, None, None)
        child = scheduler.prepare("child", {}, None, parent.task_id, None)
        assert child.parent_task_id == parent.task_id


class TestActivate:
    """scheduler.activate delegates to store.activate."""

    def test_activate_transitions_to_queued(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test", {"a": 1})
        activated = scheduler.activate(task.task_id, {"a": 2}, None)
        assert activated.status == TaskStatus.QUEUED
        assert activated.payload == {"a": 2}, "payload_patch should be merged"

    def test_activate_without_payload_patch(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test", {"keep": "me"})
        activated = scheduler.activate(task.task_id)
        assert activated.status == TaskStatus.QUEUED
        assert activated.payload == {"keep": "me"}

    def test_activate_with_run_after(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        activated = scheduler.activate(task.task_id, run_after="2099-01-01T00:00:00")
        assert activated.status == TaskStatus.QUEUED
        assert activated.run_after == "2099-01-01T00:00:00"

    def test_activate_missing_task_raises(self, scheduler: TaskScheduler) -> None:
        with pytest.raises(ValueError, match="not found"):
            scheduler.activate("no-such-task")


class TestEnqueue:
    """scheduler.enqueue delegates to store.enqueue."""

    def test_enqueue_creates_queued_task(self, scheduler: TaskScheduler) -> None:
        task = scheduler.enqueue("test", {"n": 42}, "session-1", None, None, None)
        assert task.status == TaskStatus.QUEUED
        assert task.kind == "test"
        assert task.payload == {"n": 42}
        assert task.source_session_id == "session-1"

    def test_enqueue_without_optional_params(self, scheduler: TaskScheduler) -> None:
        task = scheduler.enqueue("test")
        assert task.status == TaskStatus.QUEUED
        assert task.payload == {}

    def test_enqueue_with_run_after(self, scheduler: TaskScheduler) -> None:
        task = scheduler.enqueue("test", run_after="2099-12-31T23:59:00")
        assert task.run_after == "2099-12-31T23:59:00"

    def test_enqueue_with_dedupe_key(self, scheduler: TaskScheduler) -> None:
        t1 = scheduler.enqueue("test", {"a": 1}, dedupe_key="dedupe:xyz")
        t2 = scheduler.enqueue("test", {"a": 2}, dedupe_key="dedupe:xyz")
        assert t2.task_id == t1.task_id
        assert t2.payload == {"a": 1}

    def test_enqueue_with_parent_task(self, scheduler: TaskScheduler) -> None:
        parent = scheduler.enqueue("parent")
        child = scheduler.enqueue("child", parent_task_id=parent.task_id)
        assert child.parent_task_id == parent.task_id


class TestFailInitialization:
    """scheduler.fail_initialization delegates to store.fail_initialization."""

    def test_fail_initialization_returns_failed(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        failed = scheduler.fail_initialization(task.task_id, {"msg": "error"})
        assert failed.status == TaskStatus.FAILED
        assert failed.error == {"msg": "error"}

    def test_fail_initialization_without_error(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        failed = scheduler.fail_initialization(task.task_id)
        assert failed.status == TaskStatus.FAILED

    def test_fail_initialization_idempotent(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        scheduler.fail_initialization(task.task_id, {"msg": "first"})
        t2 = scheduler.fail_initialization(task.task_id, {"msg": "second"})
        assert t2.error == {"msg": "first"}, "original error must persist"

    def test_fail_initialization_missing_raises(self, scheduler: TaskScheduler) -> None:
        with pytest.raises(ValueError, match="not found"):
            scheduler.fail_initialization("no-such-task")


class TestCancel:
    """scheduler.cancel delegates to store.cancel."""

    def test_cancel_from_queued(self, scheduler: TaskScheduler) -> None:
        task = scheduler.enqueue("test")
        cancelled = scheduler.cancel(task.task_id)
        assert cancelled.status == TaskStatus.CANCELLED

    def test_cancel_from_initializing(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        cancelled = scheduler.cancel(task.task_id)
        assert cancelled.status == TaskStatus.CANCELLED

    def test_cancel_idempotent(self, scheduler: TaskScheduler) -> None:
        task = scheduler.enqueue("test")
        scheduler.cancel(task.task_id)
        t2 = scheduler.cancel(task.task_id)
        assert t2.status == TaskStatus.CANCELLED

    def test_cancel_missing_raises(self, scheduler: TaskScheduler) -> None:
        with pytest.raises(ValueError, match="not found"):
            scheduler.cancel("no-such-task")


class TestGet:
    """scheduler.get delegates to store.get."""

    def test_get_returns_task(self, scheduler: TaskScheduler) -> None:
        created = scheduler.enqueue("test", {"key": "val"})
        retrieved = scheduler.get(created.task_id)
        assert retrieved is not None
        assert retrieved.task_id == created.task_id
        assert retrieved.payload == {"key": "val"}

    def test_get_returns_none_for_missing(self, scheduler: TaskScheduler) -> None:
        assert scheduler.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Payload dict serialization
# ---------------------------------------------------------------------------


class TestPayloadSerialization:
    """Payload dicts passed to the scheduler are JSON-serialized by the store."""

    CHINESE_TITLE = "沙丘2：全面启动"
    NAS_PATH = "/volume1/影视/电影/沙丘2 (2024)"

    def test_prepare_payload_round_trip(self, scheduler: TaskScheduler) -> None:
        payload = {"title": self.CHINESE_TITLE, "path": self.NAS_PATH, "tags": ["电影"]}
        task = scheduler.prepare("test", payload)
        assert task.payload == payload

    def test_enqueue_payload_round_trip(self, scheduler: TaskScheduler) -> None:
        payload = {"url": "https://example.com/torrent", "name": self.CHINESE_TITLE}
        task = scheduler.enqueue("test", payload)
        assert task.payload == payload

    def test_activate_payload_patch_round_trip(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test", {"initial": True})
        activated = scheduler.activate(task.task_id, {"patch": "applied"})
        assert activated.payload == {"initial": True, "patch": "applied"}

    def test_exclusive_key_and_monitor_update_wrappers(
        self, scheduler: TaskScheduler
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            {"qb_hash": "abc", "monitor": {"mode": "until_complete", "on_completed": "notify"}},
            exclusive_key="download-monitor:abc",
        )
        assert task.exclusive_key == "download-monitor:abc"
        updated = scheduler.update_download_monitor(task.task_id, mode="once")
        assert updated.payload["monitor"]["mode"] == "once"

    def test_fail_initialization_error_round_trip(self, scheduler: TaskScheduler) -> None:
        task = scheduler.prepare("test")
        error = {"code": "TIMEOUT", "message": f"下载超时 {self.CHINESE_TITLE}"}
        failed = scheduler.fail_initialization(task.task_id, error)
        assert failed.error == error


# ---------------------------------------------------------------------------
# Clock and ID factory injection
# ---------------------------------------------------------------------------


class TestClockInjection:
    """The scheduler injects its clock automatically, not exposing 'now'."""

    def test_create_timestamps_match_clock(self, scheduler: TaskScheduler, fixed_clock: Callable[[], datetime]) -> None:
        now = fixed_clock()
        task = scheduler.enqueue("test", {"x": 1})
        assert task.created_at == now.isoformat()
        assert task.updated_at == now.isoformat()

    def test_activate_timestamps_match_clock(self, scheduler: TaskScheduler, fixed_clock: Callable[[], datetime]) -> None:
        now = fixed_clock()
        task = scheduler.prepare("test")
        activated = scheduler.activate(task.task_id)
        assert activated.updated_at == now.isoformat()


class TestIdFactoryInjection:
    """The scheduler injects its id_factory automatically, not exposing it."""

    def test_prepare_uses_injected_factory(self, scheduler: TaskScheduler, sequential_id_factory: Callable[[], str]) -> None:
        t1 = scheduler.prepare("test")
        assert t1.task_id == "task-1"
        t2 = scheduler.prepare("test")
        assert t2.task_id == "task-2"

    def test_enqueue_uses_injected_factory(self, scheduler: TaskScheduler, sequential_id_factory: Callable[[], str]) -> None:
        t1 = scheduler.enqueue("test")
        assert t1.task_id == "task-1"
        t2 = scheduler.enqueue("test")
        assert t2.task_id == "task-2"


# ---------------------------------------------------------------------------
# Worker methods are NOT exposed
# ---------------------------------------------------------------------------


class TestWorkerMethodsHidden:
    """TaskScheduler intentionally hides worker-facing store methods."""

    WORKER_METHODS = (
        "claim_due",
        "reschedule",
        "finish",
        "record_run",
        "update_run",
        "create_event",
        "get_events_for_session",
        "mark_events_injected",
        "acknowledge_event",
        "list_events",
    )

    def test_worker_methods_not_accessible(self, scheduler: TaskScheduler) -> None:
        for name in self.WORKER_METHODS:
            assert not hasattr(scheduler, name), f"TaskScheduler must not expose '{name}'"

    def test_scheduler_has_expected_methods(self, scheduler: TaskScheduler) -> None:
        expected = ("prepare", "activate", "enqueue", "fail_initialization", "cancel", "get")
        for name in expected:
            assert hasattr(scheduler, name), f"TaskScheduler must expose '{name}'"
