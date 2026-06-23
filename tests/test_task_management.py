"""Tests for TaskManagementService and store-level atomic mutations."""

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.downloads import (
    DownloadCheckPolicy,
    ScheduleDownloadCheckRequest,
    ScheduledDownloadCheckReceipt,
    is_future_time,
    normalize_to_utc,
)
from app.runtime.store import RuntimeTaskStore
from app.runtime.scheduler import TaskScheduler


# ---------------------------------------------------------------------------
# UTC normalization
# ---------------------------------------------------------------------------


class TestNormalizeToUtc:
    def test_converts_offset_to_utc(self):
        result = normalize_to_utc("2026-06-25T20:00:00+08:00")
        assert result == "2026-06-25T12:00:00+00:00"

    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError, match="timezone offset"):
            normalize_to_utc("2026-06-25T20:00:00")

    def test_rejects_unparseable(self):
        with pytest.raises(ValueError):
            normalize_to_utc("not-a-datetime")

    def test_preserves_utc(self):
        result = normalize_to_utc("2026-06-25T12:00:00+00:00")
        assert result == "2026-06-25T12:00:00+00:00"


class TestIsFutureTime:
    def test_future_is_true(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert is_future_time(future) is True

    def test_past_is_false(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert is_future_time(past) is False

    def test_accepts_custom_now(self):
        now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
        assert is_future_time("2026-06-25T13:00:00+00:00", now=now) is True
        assert is_future_time("2026-06-25T11:00:00+00:00", now=now) is False


# ---------------------------------------------------------------------------
# DownloadCheckPolicy
# ---------------------------------------------------------------------------


class TestDownloadCheckPolicy:
    def test_defaults_are_continuous_reschedule(self):
        policy = DownloadCheckPolicy()
        assert policy.mode == "continuous"
        assert policy.on_incomplete == "reschedule"

    def test_roundtrip(self):
        policy = DownloadCheckPolicy(mode="once", on_incomplete="notify")
        data = policy.model_dump()
        assert data == {"mode": "once", "on_incomplete": "notify"}

    def test_validate_from_dict(self):
        policy = DownloadCheckPolicy.model_validate(
            {"mode": "once", "on_incomplete": "notify"}
        )
        assert policy.mode == "once"
        assert policy.on_incomplete == "notify"


# ---------------------------------------------------------------------------
# ScheduleDownloadCheckRequest
# ---------------------------------------------------------------------------


class TestScheduleDownloadCheckRequest:
    def test_minimal_request(self):
        req = ScheduleDownloadCheckRequest(
            torrent_hash="abc123",
            run_at="2026-06-25T20:00:00+08:00",
        )
        assert req.torrent_hash == "abc123"
        assert req.follow_up is None

    def test_with_follow_up(self):
        req = ScheduleDownloadCheckRequest(
            torrent_hash="abc123",
            run_at="2026-06-25T20:00:00+08:00",
            follow_up="auto_organize",
        )
        assert req.follow_up == "auto_organize"


# ---------------------------------------------------------------------------
# ScheduledDownloadCheckReceipt
# ---------------------------------------------------------------------------


class TestScheduledDownloadCheckReceipt:
    def test_receipt_fields(self):
        receipt = ScheduledDownloadCheckReceipt(
            task_id="task-1",
            torrent_hash="abc123",
            torrent_name="Test.Movie.1080p",
            run_at="2026-06-25T12:00:00+00:00",
            check_mode="once",
            resolved_follow_up="notify_only",
            if_incomplete="notify",
        )
        assert receipt.task_id == "task-1"
        assert receipt.check_mode == "once"
        assert receipt.if_incomplete == "notify"


# ---------------------------------------------------------------------------
# Atomic store mutations
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _id_factory() -> str:
    import uuid
    return uuid.uuid4().hex


def _make_store(db_path: str) -> RuntimeTaskStore:
    from app.storage.db import ensure_schema

    ensure_schema(db_path)
    return RuntimeTaskStore(
        db_path=db_path,
        clock=_utc_now,
        id_factory=_id_factory,
    )


class TestCancelPending:
    def test_cancels_queued_task(self, tmp_path):
        db = tmp_path / "tasks.db"
        store = _make_store(str(db))
        scheduler = TaskScheduler(store, _utc_now, _id_factory)

        task = scheduler.enqueue(
            kind="download_watch",
            payload={"qb_hash": "test123"},
        )
        assert task.status.value == "queued"

        cancelled = scheduler.cancel_pending(task.task_id)
        assert cancelled.status.value == "cancelled"

    def test_rejects_running_task(self, tmp_path):
        db = tmp_path / "tasks.db"
        store = _make_store(str(db))
        scheduler = TaskScheduler(store, _utc_now, _id_factory)

        task = scheduler.enqueue(
            kind="download_watch",
            payload={"qb_hash": "test123"},
        )
        # Simulate claim by directly updating status.
        store._db_path  # force access

        # Manually transition to RUNNING (bypass scheduler for test).
        import sqlite3
        from app.storage.db import connect

        conn = connect(str(db))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE runtime_tasks SET status='running' WHERE task_id=?",
                (task.task_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(ValueError, match="RUNNING"):
            scheduler.cancel_pending(task.task_id)

    def test_rejects_terminal_task(self, tmp_path):
        db = tmp_path / "tasks.db"
        store = _make_store(str(db))
        scheduler = TaskScheduler(store, _utc_now, _id_factory)

        task = scheduler.enqueue(
            kind="download_watch",
            payload={"qb_hash": "test123"},
        )
        scheduler.cancel(task.task_id)

        with pytest.raises(ValueError, match="terminal"):
            scheduler.cancel_pending(task.task_id)


class TestReschedulePendingOnce:
    def test_reschedules_queued_once_task(self, tmp_path):
        db = tmp_path / "tasks.db"
        store = _make_store(str(db))
        scheduler = TaskScheduler(store, _utc_now, _id_factory)

        new_time = (_utc_now() + timedelta(hours=2)).isoformat()
        task = scheduler.enqueue(
            kind="download_watch",
            payload={
                "qb_hash": "test123",
                "check_policy": {"mode": "once", "on_incomplete": "notify"},
                "scheduled_for": (_utc_now() + timedelta(hours=1)).isoformat(),
            },
            run_after=(_utc_now() + timedelta(hours=1)).isoformat(),
        )

        rescheduled = scheduler.reschedule_pending_once(
            task.task_id, run_after=new_time,
        )
        assert rescheduled.run_after == new_time

    def test_rejects_continuous_task(self, tmp_path):
        db = tmp_path / "tasks.db"
        store = _make_store(str(db))
        scheduler = TaskScheduler(store, _utc_now, _id_factory)

        new_time = (_utc_now() + timedelta(hours=2)).isoformat()
        task = scheduler.enqueue(
            kind="download_watch",
            payload={"qb_hash": "test123"},  # no check_policy → continuous
        )

        with pytest.raises(ValueError, match="only once-mode"):
            scheduler.reschedule_pending_once(task.task_id, run_after=new_time)
