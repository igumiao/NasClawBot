"""Tests for the RuntimeTaskStore (app.runtime.store).

Exercises state transitions, terminal idempotency, illegal transitions,
concurrent claim via BEGIN IMMEDIATE, expired lease recovery, dedupe_key,
JSON round-trips, and clock/id_factory injection.
"""

from __future__ import annotations

import json
import itertools
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from app.domain.runtime_tasks import RuntimeTask, TaskStatus, WorkerRun
from app.runtime.store import RuntimeTaskStore
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Generate a temporary SQLite database path unique to each test."""
    return tmp_path / "test_store.db"


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a deterministic clock that always returns 2026-06-01T12:00:00+00:00."""
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
    """Return a RuntimeTaskStore backed by a temporary SQLite file with schema applied."""
    # Ensure schema exists before constructing the store
    conn = connect(tmp_db_path)
    initialize_schema(conn)
    conn.close()
    return RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Verify every legal state transition through the store methods."""

    def test_prepare_creates_initializing(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {"key": "val"}, None, None, None, fixed_clock(), sequential_id_factory)
        assert task.status == TaskStatus.INITIALIZING
        assert task.kind == "test"
        assert task.payload == {"key": "val"}

    def test_activate_transitions_to_queued(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        activated = store.activate(task.task_id, None, None, fixed_clock())
        assert activated.status == TaskStatus.QUEUED

    def test_enqueue_creates_queued(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.enqueue("test", {"n": 1}, None, None, None, None, fixed_clock(), sequential_id_factory)
        assert task.status == TaskStatus.QUEUED

    def test_initializing_to_queued(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        activated = store.activate(task.task_id, None, None, fixed_clock())
        assert activated.status == TaskStatus.QUEUED

    def test_initializing_to_failed(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        failed = store.fail_initialization(task.task_id, {"msg": "oops"}, fixed_clock())
        assert failed.status == TaskStatus.FAILED

    def test_initializing_to_cancelled(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        cancelled = store.cancel(task.task_id, fixed_clock())
        assert cancelled.status == TaskStatus.CANCELLED

    def test_queued_to_running(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        assert len(claimed) == 1
        assert claimed[0].status == TaskStatus.RUNNING
        assert claimed[0].lease_owner == "worker1"

    def test_queued_to_cancelled(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        cancelled = store.cancel(task.task_id, fixed_clock())
        assert cancelled.status == TaskStatus.CANCELLED

    def test_running_to_succeeded(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        finished = store.finish(claimed[0].task_id, TaskStatus.SUCCEEDED, {"ok": True}, None, fixed_clock())
        assert finished.status == TaskStatus.SUCCEEDED
        assert finished.result == {"ok": True}
        assert finished.completed_at is not None

    def test_running_to_failed(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        finished = store.finish(claimed[0].task_id, TaskStatus.FAILED, None, {"error": "boom"}, fixed_clock())
        assert finished.status == TaskStatus.FAILED
        assert finished.error == {"error": "boom"}

    def test_running_to_waiting(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        rescheduled = store.reschedule(claimed[0].task_id, "2099-01-01T00:00:00", None, fixed_clock())
        assert rescheduled.status == TaskStatus.WAITING
        assert rescheduled.lease_owner is None
        assert rescheduled.lease_expires_at is None

    def test_waiting_to_running(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        store.reschedule(claimed[0].task_id, fixed_clock().isoformat(), None, fixed_clock())
        reclaimed = store.claim_due(["test"], 1, "worker2", 60, fixed_clock())
        assert len(reclaimed) == 1
        assert reclaimed[0].status == TaskStatus.RUNNING
        assert reclaimed[0].lease_owner == "worker2"

    def test_running_to_cancelled(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        cancelled = store.cancel(claimed[0].task_id, fixed_clock())
        assert cancelled.status == TaskStatus.CANCELLED

    def test_waiting_to_cancelled(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        rescheduled = store.reschedule(claimed[0].task_id, "2099-01-01T00:00:00", None, fixed_clock())
        cancelled = store.cancel(rescheduled.task_id, fixed_clock())
        assert cancelled.status == TaskStatus.CANCELLED

    def test_fail_initialization_from_initializing(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        failed = store.fail_initialization(task.task_id, {"msg": "failed"}, fixed_clock())
        assert failed.status == TaskStatus.FAILED
        assert failed.error == {"msg": "failed"}


# ---------------------------------------------------------------------------
# Terminal idempotency
# ---------------------------------------------------------------------------


class TestTerminalIdempotency:
    """Calling finish/cancel on an already-terminal task returns the existing row."""

    def test_finish_succeeded_is_idempotent(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        t1 = store.finish(claimed[0].task_id, TaskStatus.SUCCEEDED, {"ok": True}, None, fixed_clock())
        t2 = store.finish(claimed[0].task_id, TaskStatus.SUCCEEDED, None, None, fixed_clock())
        assert t2.status == TaskStatus.SUCCEEDED
        assert t2.result == {"ok": True}, "second finish must not overwrite result"

    def test_finish_failed_is_idempotent(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        t1 = store.finish(claimed[0].task_id, TaskStatus.FAILED, None, {"err": "x"}, fixed_clock())
        t2 = store.finish(claimed[0].task_id, TaskStatus.FAILED, None, None, fixed_clock())
        assert t2.status == TaskStatus.FAILED
        assert t2.error == {"err": "x"}, "second finish must not overwrite error"

    def test_cancel_is_idempotent(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        t1 = store.cancel(claimed[0].task_id, fixed_clock())
        t2 = store.cancel(claimed[0].task_id, fixed_clock())
        assert t2.status == TaskStatus.CANCELLED

    def test_fail_initialization_is_idempotent_on_terminal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        store.fail_initialization(task.task_id, {"err": "x"}, fixed_clock())
        t2 = store.fail_initialization(task.task_id, {"err": "y"}, fixed_clock())
        assert t2.status == TaskStatus.FAILED
        assert t2.error == {"err": "x"}, "second fail_initialization must not overwrite error"


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


class TestIllegalTransitions:
    """Illegal state transitions raise ValueError."""

    def test_initializing_to_terminal_via_finish_illegal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """INITIALIZING can only transition to QUEUED, FAILED, or CANCELLED.

        Finish with SUCCEEDED from INITIALIZING is illegal
        (INITIALIZING->SUCCEEDED is not in LEGAL_TRANSITIONS).
        INITIALIZING->FAILED via finish IS legal because the allowed set
        includes FAILED, though fail_initialization is the preferred path.
        """
        task = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        with pytest.raises(ValueError, match="Invalid transition"):
            store.finish(task.task_id, TaskStatus.SUCCEEDED, None, None, fixed_clock())

    def test_queued_to_succeeded_illegal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        with pytest.raises(ValueError, match="Invalid transition"):
            store.finish(task.task_id, TaskStatus.SUCCEEDED, None, None, fixed_clock())

    def test_queued_to_failed_illegal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        with pytest.raises(ValueError, match="Invalid transition"):
            store.finish(task.task_id, TaskStatus.FAILED, None, None, fixed_clock())

    def test_queued_to_waiting_illegal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        task = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        with pytest.raises(ValueError, match="Invalid transition"):
            store.reschedule(task.task_id, "2099-01-01T00:00:00", None, fixed_clock())

    def test_terminal_to_anything_illegal(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """After finish (SUCCEEDED), non-idempotent methods reject further mutations.

        finish/cancel/fail_initialization are idempotent on terminal tasks and
        return the existing row without raising.  reschedule and activate do
        NOT have terminal guards so they must raise.
        """
        task = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        store.finish(claimed[0].task_id, TaskStatus.SUCCEEDED, None, None, fixed_clock())
        with pytest.raises(ValueError, match="terminal"):
            store.reschedule(claimed[0].task_id, "2099-01-01T00:00:00", None, fixed_clock())
        with pytest.raises(ValueError, match="terminal"):
            store.activate(claimed[0].task_id, None, None, fixed_clock())

    def test_transition_from_missing_task_raises(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            store.activate("no-such-task", None, None, fixed_clock())
        with pytest.raises(ValueError, match="not found"):
            store.finish("no-such-task", TaskStatus.SUCCEEDED, None, None, fixed_clock())
        with pytest.raises(ValueError, match="not found"):
            store.cancel("no-such-task", fixed_clock())
        with pytest.raises(ValueError, match="not found"):
            store.reschedule("no-such-task", "2099-01-01T00:00:00", None, fixed_clock())
        with pytest.raises(ValueError, match="not found"):
            store.fail_initialization("no-such-task", None, fixed_clock())


# ---------------------------------------------------------------------------
# claim_due with BEGIN IMMEDIATE (concurrent)
# ---------------------------------------------------------------------------


class TestClaimDueConcurrent:
    """Two store instances on the same DB file: only one should claim each task."""

    def test_concurrent_claim_no_double_claim(
        self,
        tmp_db_path: Path,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Two stores race to claim 2 tasks with limit=2; total claimed is 2."""
        # Pre-enqueue tasks via an ephemeral store
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        setup_store = RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)
        ids: list[str] = []
        for _ in range(2):
            t = setup_store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
            ids.append(t.task_id)
        del setup_store  # release file handles

        store_a = RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)
        store_b = RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)

        results: list[tuple[int, Any]] = []

        def _claim(s: RuntimeTaskStore, idx: int) -> None:
            try:
                tasks = s.claim_due(["test"], 2, f"worker{idx}", 60, fixed_clock())
                results.append((idx, tasks))
            except Exception as e:
                results.append((idx, e))

        threads = [
            threading.Thread(target=_claim, args=(store_a, 1)),
            threading.Thread(target=_claim, args=(store_b, 2)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Sum claimed tasks across both stores — must match total enqueued tasks
        total_claimed = sum(
            len(r[1]) for r in results if isinstance(r[1], list)
        )
        assert total_claimed == 2, f"Expected 2 total claimed, got {total_claimed}"

        # Verify no double-claim: each task appears exactly once in all results
        all_task_ids: list[str] = []
        for _, tasks in results:
            if isinstance(tasks, list):
                all_task_ids.extend(t.task_id for t in tasks)
        assert len(all_task_ids) == len(set(all_task_ids)), "Duplicate task claim detected"

    def test_claim_due_with_expired_lease(
        self,
        tmp_db_path: Path,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """A task whose lease has expired can be reclaimed after resetting to QUEUED."""
        conn = connect(tmp_db_path)
        initialize_schema(conn)
        conn.close()

        store_inst = RuntimeTaskStore(tmp_db_path, fixed_clock, sequential_id_factory)
        t = store_inst.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)

        # Claim it (RUNNING with lease)
        claimed = store_inst.claim_due(["test"], 1, "worker1", 60, fixed_clock())
        assert len(claimed) == 1
        assert claimed[0].lease_owner == "worker1"

        # Simulate lease expiration: set lease_expires_at to the past and
        # reset status to QUEUED (as a recovery mechanism would do).
        conn = connect(tmp_db_path)
        conn.execute(
            "UPDATE runtime_tasks SET "
            "status = 'queued', "
            "lease_owner = NULL, "
            "lease_expires_at = ?, "
            "updated_at = ? "
            "WHERE task_id = ?",
            ("2020-01-01T00:00:00", fixed_clock().isoformat(), t.task_id),
        )
        conn.commit()
        conn.close()

        # Another worker can now claim the recovered task
        reclaimed = store_inst.claim_due(["test"], 1, "worker2", 60, fixed_clock())
        assert len(reclaimed) == 1
        assert reclaimed[0].status == TaskStatus.RUNNING
        assert reclaimed[0].lease_owner == "worker2"
        # Lease should be fresh
        assert reclaimed[0].lease_expires_at is not None

    def test_claim_due_empty_kinds_returns_empty(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
    ) -> None:
        assert store.claim_due([], 10, "w", 60, fixed_clock()) == []

    def test_claim_due_limit_zero_returns_empty(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
    ) -> None:
        assert store.claim_due(["test"], 0, "w", 60, fixed_clock()) == []

    def test_claim_due_respects_run_after(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Tasks with future run_after are not claimed."""
        future = "2099-12-31T23:59:00"
        store.enqueue("test", {}, None, None, None, future, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 10, "w", 60, fixed_clock())
        assert claimed == []


# ---------------------------------------------------------------------------
# Duplicate-key protection (dedupe_key)
# ---------------------------------------------------------------------------


class TestDedupeKey:
    """Duplicate dedupe_key returns existing task on prepare/enqueue."""

    def test_dedupe_key_prepare_returns_existing(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t1 = store.prepare("test", {"a": 1}, None, None, "dedupe:abc", fixed_clock(), sequential_id_factory)
        t2 = store.prepare("test", {"a": 2}, None, None, "dedupe:abc", fixed_clock(), sequential_id_factory)
        assert t2.task_id == t1.task_id
        assert t2.payload == {"a": 1}, "second prepare must return original payload"

    def test_dedupe_key_enqueue_returns_existing(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t1 = store.enqueue("test", {"x": 1}, None, None, "dedupe:xyz", None, fixed_clock(), sequential_id_factory)
        t2 = store.enqueue("test", {"x": 2}, None, None, "dedupe:xyz", None, fixed_clock(), sequential_id_factory)
        assert t2.task_id == t1.task_id
        assert t2.payload == {"x": 1}

    def test_dedupe_key_different_keys_create_separate_tasks(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t1 = store.enqueue("test", {}, None, None, "key-a", None, fixed_clock(), sequential_id_factory)
        t2 = store.enqueue("test", {}, None, None, "key-b", None, fixed_clock(), sequential_id_factory)
        assert t1.task_id != t2.task_id


class TestActiveExclusiveKey:
    def test_enqueue_conflicts_while_first_monitor_is_active(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        store.enqueue(
            "download_watch", {"monitor": {"mode": "until_complete", "on_completed": "notify"}},
            None, None, None, None, fixed_clock(), sequential_id_factory,
            exclusive_key="download-monitor:abc",
        )
        with pytest.raises(ValueError, match="already owns"):
            store.enqueue(
                "download_watch", {"monitor": {"mode": "once", "on_completed": "notify"}},
                None, None, None, None, fixed_clock(), sequential_id_factory,
                exclusive_key="download-monitor:abc",
            )

    def test_terminal_task_releases_exclusive_key(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        first = store.enqueue(
            "download_watch", {"monitor": {"mode": "once", "on_completed": "notify"}},
            None, None, None, None, fixed_clock(), sequential_id_factory,
            exclusive_key="download-monitor:abc",
        )
        claimed = store.claim_due(
            ["download_watch"], 1, "worker", 60, fixed_clock()
        )[0]
        store.finish(
            claimed.task_id, TaskStatus.SUCCEEDED, {}, None, fixed_clock()
        )
        second = store.enqueue(
            "download_watch", {"monitor": {"mode": "once", "on_completed": "notify"}},
            None, None, None, None, fixed_clock(), sequential_id_factory,
            exclusive_key="download-monitor:abc",
        )
        assert second.task_id != first.task_id

    def test_activate_binds_exclusive_key_atomically(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        existing = store.enqueue(
            "download_watch", {"monitor": {"mode": "once", "on_completed": "notify"}},
            None, None, None, None, fixed_clock(), sequential_id_factory,
            exclusive_key="download-monitor:abc",
        )
        prepared = store.prepare(
            "download_watch", {"monitor": {"mode": "until_complete", "on_completed": "notify"}},
            None, None, None, fixed_clock(), sequential_id_factory,
        )
        with pytest.raises(ValueError, match=existing.task_id):
            store.activate(
                prepared.task_id,
                {"qb_hash": "abc"},
                None,
                fixed_clock(),
                exclusive_key="download-monitor:abc",
            )
        unchanged = store.get(prepared.task_id)
        assert unchanged is not None
        assert unchanged.status == TaskStatus.INITIALIZING
        assert unchanged.payload.get("qb_hash") is None
        assert unchanged.exclusive_key is None


class TestAtomicDownloadMonitorUpdate:
    def _create(self, store, clock, ids, *, action="notify"):
        payload = {
            "qb_hash": "abc",
            "monitor": {"mode": "until_complete", "on_completed": action},
        }
        if action == "organize":
            payload["authorization_snapshot"] = {
                "background_organization_allowed": True,
                "allowed_source_path_prefixes": ["/downloads"],
                "destination_root": "/media",
            }
        return store.enqueue(
            "download_watch", payload, None, None, None,
            "2026-06-24T00:00:00+00:00", clock(), ids,
            exclusive_key="download-monitor:abc",
        )

    def test_updates_time_mode_and_action_in_one_write(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        task = self._create(store, fixed_clock, sequential_id_factory)
        snapshot = {
            "background_organization_allowed": True,
            "allowed_source_path_prefixes": ["/downloads"],
            "destination_root": "/media",
        }
        updated = store.update_download_monitor(
            task.task_id,
            run_after="2026-06-25T00:00:00+00:00",
            mode="once",
            on_completed="organize",
            authorization_snapshot=snapshot,
            now=fixed_clock(),
        )
        assert updated.run_after == "2026-06-25T00:00:00+00:00"
        assert updated.payload["monitor"] == {
            "mode": "once", "on_completed": "organize"
        }
        assert updated.payload["authorization_snapshot"] == snapshot

    def test_organize_to_notify_removes_snapshot(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        task = self._create(
            store, fixed_clock, sequential_id_factory, action="organize"
        )
        updated = store.update_download_monitor(
            task.task_id, on_completed="notify", now=fixed_clock()
        )
        assert updated.payload["monitor"]["on_completed"] == "notify"
        assert "authorization_snapshot" not in updated.payload

    def test_legacy_payload_is_rewritten_canonically(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        task = store.enqueue(
            "download_watch",
            {
                "qb_hash": "legacy",
                "check_policy": {"mode": "once", "on_incomplete": "notify"},
                "resolved_follow_up": {"mode": "notify_only"},
                "scheduled_for": "old",
            },
            None, None, None, None, fixed_clock(), sequential_id_factory,
        )
        updated = store.update_download_monitor(
            task.task_id, mode="until_complete", now=fixed_clock()
        )
        assert updated.payload["monitor"] == {
            "mode": "until_complete", "on_completed": "notify"
        }
        assert "check_policy" not in updated.payload
        assert "resolved_follow_up" not in updated.payload
        assert "scheduled_for" not in updated.payload

    def test_running_and_terminal_updates_are_rejected(
        self, store, fixed_clock, sequential_id_factory
    ) -> None:
        task = self._create(store, fixed_clock, sequential_id_factory)
        store.update_download_monitor(
            task.task_id, run_after=fixed_clock().isoformat(), now=fixed_clock()
        )
        running = store.claim_due(
            ["download_watch"], 1, "worker", 60, fixed_clock()
        )[0]
        with pytest.raises(ValueError, match="RUNNING"):
            store.update_download_monitor(
                running.task_id, mode="once", now=fixed_clock()
            )
        store.finish(
            running.task_id, TaskStatus.SUCCEEDED, {}, None, fixed_clock()
        )
        with pytest.raises(ValueError, match="terminal"):
            store.update_download_monitor(
                task.task_id, mode="once", now=fixed_clock()
            )

    def test_null_dedupe_keys_are_distinct(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t1 = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        t2 = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        assert t1.task_id != t2.task_id


# ---------------------------------------------------------------------------
# Query methods
# ---------------------------------------------------------------------------


class TestQueryMethods:
    """get, list_tasks, get_task_with_runs."""

    def test_get_returns_none_for_missing(
        self,
        store: RuntimeTaskStore,
    ) -> None:
        assert store.get("nonexistent") is None

    def test_get_returns_task(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t = store.enqueue("test", {"n": 42}, None, None, None, None, fixed_clock(), sequential_id_factory)
        retrieved = store.get(t.task_id)
        assert retrieved is not None
        assert retrieved.task_id == t.task_id
        assert retrieved.payload == {"n": 42}

    def test_list_tasks_with_no_filters(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("a", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        store.enqueue("b", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        all_tasks = store.list_tasks()
        assert len(all_tasks) == 2

    def test_list_tasks_filter_by_status(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        t = store.prepare("test", {}, None, None, None, fixed_clock(), sequential_id_factory)
        # INITIALIZING tasks
        initializing = store.list_tasks(status="initializing")
        assert len(initializing) == 1
        assert initializing[0].task_id == t.task_id
        # QUEUED tasks
        queued = store.list_tasks(status="queued")
        assert len(queued) == 1

    def test_list_tasks_filter_by_kind(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("kind_a", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        store.enqueue("kind_b", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        a_tasks = store.list_tasks(kind="kind_a")
        assert len(a_tasks) == 1
        assert a_tasks[0].kind == "kind_a"

    def test_list_tasks_filter_by_session(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        store.enqueue("test", {}, "session-1", None, None, None, fixed_clock(), sequential_id_factory)
        store.enqueue("test", {}, "session-2", None, None, None, fixed_clock(), sequential_id_factory)
        s1 = store.list_tasks(source_session_id="session-1")
        assert len(s1) == 1
        assert s1[0].source_session_id == "session-1"

    def test_list_tasks_respects_limit(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        for _ in range(5):
            store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        limited = store.list_tasks(limit=3)
        assert len(limited) == 3

    def test_get_task_with_runs(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t = store.enqueue("test", {"n": 1}, None, None, None, None, fixed_clock(), sequential_id_factory)
        # Create a WorkerRun manually
        run = WorkerRun.model_validate({
            "run_id": "run-1",
            "task_id": t.task_id,
            "attempt": 1,
            "status": "running",
            "started_at": fixed_clock().isoformat(),
        })
        store.record_run(run)

        task, runs = store.get_task_with_runs(t.task_id)
        assert task.task_id == t.task_id
        assert len(runs) == 1
        assert runs[0].run_id == "run-1"

    def test_get_task_with_runs_missing_raises(
        self,
        store: RuntimeTaskStore,
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            store.get_task_with_runs("no-such-task")


# ---------------------------------------------------------------------------
# JSON round-trip with Unicode / Chinese
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    """Payload, result, and error JSON fields preserve Chinese and Unicode."""

    CHINESE_TITLE = "沙丘2：全面启动"
    NAS_PATH = "/volume1/影视/电影/沙丘2 (2024)"

    def test_payload_with_chinese(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        payload = {"title": self.CHINESE_TITLE, "path": self.NAS_PATH, "tags": ["电影", "科幻"]}
        t = store.enqueue("test", payload, None, None, None, None, fixed_clock(), sequential_id_factory)
        retrieved = store.get(t.task_id)
        assert retrieved is not None
        assert retrieved.payload["title"] == self.CHINESE_TITLE
        assert retrieved.payload["path"] == self.NAS_PATH
        assert retrieved.payload["tags"] == ["电影", "科幻"]

    def test_result_with_chinese(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        result = {"filename": self.CHINESE_TITLE, "downloaded": True}
        finished = store.finish(claimed[0].task_id, TaskStatus.SUCCEEDED, result, None, fixed_clock())
        assert finished.result == result

    def test_error_with_chinese(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        t = store.enqueue("test", {}, None, None, None, None, fixed_clock(), sequential_id_factory)
        claimed = store.claim_due(["test"], 1, "w", 60, fixed_clock())
        error = {"message": f"下载失败: {self.CHINESE_TITLE}", "code": 500}
        finished = store.finish(claimed[0].task_id, TaskStatus.FAILED, None, error, fixed_clock())
        assert finished.error == error


# ---------------------------------------------------------------------------
# Clock injection
# ---------------------------------------------------------------------------


class TestClockInjection:
    """The store's clock is not used internally; each method accepts an explicit now.

    These tests verify that timestamps in created tasks match the injected 'now'.
    """

    def test_timestamps_use_injected_now(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        now = fixed_clock()
        t = store.enqueue("test", {}, None, None, None, None, now, sequential_id_factory)
        assert t.created_at == now.isoformat()
        assert t.updated_at == now.isoformat()


# ---------------------------------------------------------------------------
# ID factory injection
# ---------------------------------------------------------------------------


class TestIdFactoryInjection:
    """The task_id in created tasks uses the injected id_factory."""

    def test_task_id_uses_injected_factory(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        custom_counter = iter(["custom-1", "custom-2"])

        def custom_factory() -> str:
            return next(custom_counter)

        t1 = store.prepare("test", {}, None, None, None, fixed_clock(), custom_factory)
        assert t1.task_id == "custom-1"

        t2 = store.enqueue("test", {}, None, None, None, None, fixed_clock(), custom_factory)
        assert t2.task_id == "custom-2"

    def test_id_factory_passed_directly_to_prepare(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
    ) -> None:
        def my_id() -> str:
            return "my-preview-id"

        t = store.prepare("test", {}, None, None, None, fixed_clock(), my_id)
        assert t.task_id == "my-preview-id"

    def test_id_factory_passed_directly_to_enqueue(
        self,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
    ) -> None:
        def my_id() -> str:
            return "my-enqueue-id"

        t = store.enqueue("test", {}, None, None, None, None, fixed_clock(), my_id)
        assert t.task_id == "my-enqueue-id"
