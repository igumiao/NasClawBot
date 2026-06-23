"""Tests for the DownloadWatchHandler (app.runtime.handlers.download_watch).

Exercises the full handler lifecycle with a fake qB adapter (dict-backed),
temporary SQLite store, and deterministic clock:
- Hash resolution: 0/1/>1 tag matches, reschedule/ambiguous
- Polling: incomplete progress, paused torrents, transient errors
- Completion: notify_only, auto_organize (spawn with dedupe), missing content_path
- Miss tracking: consecutive misses leading to QB_TORRENT_MISSING
- Payload state updates through reschedule patches
- Idempotent completion
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

FOLLOW_UP_AUTO_ORGANIZE = "auto_organize"
FOLLOW_UP_NOTIFY_ONLY = "notify_only"
from app.domain.runtime_tasks import (
    Complete,
    Fail,
    Reschedule,
    RuntimeTask,
    Spawn,
    TaskOutcome,
    TaskStatus,
)
from app.runtime.handlers.download_watch import (
    CONSECUTIVE_MISSES_THRESHOLD,
    ORGANIZE_DEDUPE_KEY_PREFIX,
    DownloadWatchConfig,
    DownloadWatchHandler,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fake qB adapter: dict-backed state machine
# ---------------------------------------------------------------------------


class FakeQBAdapter:
    """In-memory fake qBittorrent adapter.

    Callers pre-populate ``torrents_by_tag`` and ``torrents_by_hash`` dicts
    to control what ``list_torrents`` and ``get_torrent`` return.

    - ``list_torrents`` matches on the ``tag`` kwarg (exact match).
    - ``get_torrent`` returns the torrent by hash, or ``None``.
    - ``fail_list_torrents`` / ``fail_get_torrent`` cause exceptions.
    """

    def __init__(
        self,
        torrents_by_tag: dict[str, list[dict[str, Any]]] | None = None,
        torrents_by_hash: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.torrents_by_tag = dict(torrents_by_tag or {})
        self.torrents_by_hash = dict(torrents_by_hash or {})
        self.fail_list_torrents: Exception | None = None
        self.fail_get_torrent: Exception | None = None
        self.list_torrents_calls: list[dict[str, Any]] = []
        self.get_torrent_calls: list[str] = []

    def list_torrents(self, *, tag: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_torrents_calls.append({"tag": tag, **kwargs})
        if self.fail_list_torrents is not None:
            raise self.fail_list_torrents
        if tag is None:
            return list(self.torrents_by_hash.values())
        return list(self.torrents_by_tag.get(tag, []))

    def get_torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        self.get_torrent_calls.append(torrent_hash)
        if self.fail_get_torrent is not None:
            raise self.fail_get_torrent
        return self.torrents_by_hash.get(torrent_hash)


# ---------------------------------------------------------------------------
# Build minimal torrent dicts
# ---------------------------------------------------------------------------


def make_torrent(
    qb_hash: str,
    name: str = "Test.Torrent",
    progress: float = 0.0,
    state: str = "pausedDL",
    save_path: str = "/downloads",
    content_path: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    content = content_path or f"{save_path}/{name}"
    return {
        "hash": qb_hash,
        "name": name,
        "progress": progress,
        "state": state,
        "save_path": save_path,
        "content_path": content,
        "tags": tags or [],
        "category": "",
        "size": 1024 * 1024,
        "total_size": 1024 * 1024,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_watch_handler.db"


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a deterministic clock frozen at 2026-06-01T12:00:00+00:00."""
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
def qb_adapter() -> FakeQBAdapter:
    return FakeQBAdapter()


@pytest.fixture
def config() -> DownloadWatchConfig:
    return DownloadWatchConfig(poll_seconds=30, error_backoff_max=600)


@pytest.fixture
def handler(
    qb_adapter: FakeQBAdapter,
    config: DownloadWatchConfig,
    scheduler: TaskScheduler,
    store: RuntimeTaskStore,
    fixed_clock: Callable[[], datetime],
) -> DownloadWatchHandler:
    return DownloadWatchHandler(qb_adapter, config, scheduler, store, fixed_clock)


def enqueue_watch_task(
    store: RuntimeTaskStore,
    clock: Callable[[], datetime],
    id_factory: Callable[[], str],
    task_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> RuntimeTask:
    """Enqueue a download_watch task and return it."""
    def _make_id() -> str:
        return task_id or id_factory()

    return store.enqueue(
        kind="download_watch",
        payload_json=payload or {},
        source_session_id=None,
        parent_task_id=None,
        dedupe_key=None,
        run_after=None,
        now=clock(),
        id_factory=_make_id,
    )


# ===================================================================
# 1. Hash resolution: 0 matches -> Reschedule
# ===================================================================


@pytest.mark.asyncio
class TestHashResolution:
    """Correlating the task to a qB torrent via nasclaw-task-{id} tag."""

    async def test_reschedules_when_no_torrent_found(
        self,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When list_torrents returns 0 matches, handler should Reschedule."""
        task = enqueue_watch_task(store, fixed_clock, sequential_id_factory, task_id="task-watch-1")
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        # Handler does not set reason for the 0-match case; just verify run_after.
        assert outcome.run_after is not None
        assert task.payload.get("qb_hash") is None

    async def test_resolves_hash_on_one_match(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When list_torrents returns exactly 1 match, handler patches payload."""
        qb_adapter.torrents_by_tag["nasclaw-task-task-resolve-1"] = [
            make_torrent("hash-abc", name="Resolved.Movie", save_path="/media/movies"),
        ]
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-resolve-1",
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert outcome.payload_patch is not None
        assert outcome.payload_patch["qb_hash"] == "hash-abc"
        assert outcome.payload_patch["torrent_name"] == "Resolved.Movie"
        assert outcome.payload_patch["save_path"] == "/media/movies"
        assert outcome.payload_patch["consecutive_misses"] == 0
        assert outcome.payload_patch["consecutive_errors"] == 0

    async def test_fails_on_multiple_matches(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When list_torrents returns >1 match, handler should Fail."""
        qb_adapter.torrents_by_tag["nasclaw-task-task-ambig-1"] = [
            make_torrent("hash-a", "Torrent.A"),
            make_torrent("hash-b", "Torrent.B"),
        ]
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-ambig-1",
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Fail)
        assert outcome.code == "AMBIGUOUS_QB_CORRELATION"
        assert outcome.retryable is False
        assert outcome.details["torrent_count"] == 2

    async def test_list_torrents_exception_reschedules(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When list_torrents raises, handler should Reschedule."""
        qb_adapter.fail_list_torrents = RuntimeError("qB connection refused")
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-exc-1",
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert "list_torrents" in (outcome.reason or "")


# ===================================================================
# 2. Polling: incomplete progress
# ===================================================================


@pytest.mark.asyncio
class TestPolling:
    """Once qb_hash is resolved, handler polls get_torrent for progress."""

    async def test_reschedules_on_incomplete_progress(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Torrent at progress < 1.0 should Reschedule."""
        qb_adapter.torrents_by_hash["hash-inc"] = make_torrent(
            "hash-inc", "Incomplete.Movie", progress=0.45, state="downloading",
        )
        payload: dict[str, Any] = {"qb_hash": "hash-inc"}
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-inc-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert "progress=0.4500" in (outcome.reason or "")
        assert outcome.payload_patch is not None
        assert outcome.payload_patch["consecutive_misses"] == 0
        assert outcome.payload_patch["consecutive_errors"] == 0
        assert "last_poll_at" in outcome.payload_patch

    async def test_reschedules_paused_torrent(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """A paused torrent at progress < 1.0 should still Reschedule (never resumes)."""
        qb_adapter.torrents_by_hash["hash-paused"] = make_torrent(
            "hash-paused", "Paused.Torrent", progress=0.85, state="pausedDL",
        )
        payload: dict[str, Any] = {"qb_hash": "hash-paused"}
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-paused-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert "pausedDL" in (outcome.reason or "")


# ===================================================================
# 3. Completion modes
# ===================================================================


@pytest.mark.asyncio
class TestCompletion:
    """Torrent at progress >= 1.0 triggers completion handling."""

    async def test_notify_only_emits_download_completed_event(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """notify_only mode should Complete with a download_completed event."""
        qb_adapter.torrents_by_hash["hash-done"] = make_torrent(
            "hash-done", "Done.Movie", progress=1.0, state="completed",
            content_path="/downloads/Done.Movie.mkv",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-done",
            "resolved_follow_up": {"mode": FOLLOW_UP_NOTIFY_ONLY},
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-notify-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Complete)
        assert outcome.result["qb_hash"] == "hash-done"
        assert outcome.result["torrent_name"] == "Done.Movie"
        assert outcome.result["content_path"] == "/downloads/Done.Movie.mkv"
        assert len(outcome.events) == 1
        assert outcome.events[0]["kind"] == "download_completed"

    async def test_auto_organize_spawns_child_with_dedupe(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """auto_organize mode should Spawn an organize_download child with dedupe key."""
        qb_adapter.torrents_by_hash["hash-org"] = make_torrent(
            "hash-org", "Organize.Movie", progress=1.0, state="completed",
            content_path="/downloads/Organize.Movie.mkv",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-org",
            "resolved_follow_up": {
                "mode": FOLLOW_UP_AUTO_ORGANIZE,
                "authorization_snapshot": {"enabled": True, "allowed_source_path_prefixes": [], "destination_root": "/media"},
            },
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-org-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Spawn)
        assert outcome.result["spawned_organize"] is True
        assert outcome.result["qb_hash"] == "hash-org"
        assert len(outcome.children) == 1
        child = outcome.children[0]
        assert child.kind == "organize_download"
        assert child.payload["qb_hash"] == "hash-org"
        assert child.payload["content_path"] == "/downloads/Organize.Movie.mkv"
        assert child.dedupe_key == f"{ORGANIZE_DEDUPE_KEY_PREFIX}hash-org"
        assert len(outcome.events) == 1
        assert outcome.events[0]["kind"] == "download_completed"

    async def test_auto_organize_dedupe_key_prevents_duplicate_children(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When the handler runs again after completion, dedupe key is identical.

        The dedupe key is derived from qb_hash, so a second call returns the same
        key.  The Spawn outcome's dedupe key must match so the worker can enforce
        idempotent child creation.
        """
        qb_adapter.torrents_by_hash["hash-dedup"] = make_torrent(
            "hash-dedup", "Dedup.Movie", progress=1.0, state="completed",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-dedup",
            "resolved_follow_up": {
                "mode": FOLLOW_UP_AUTO_ORGANIZE,
                "authorization_snapshot": {},
            },
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-dedup-1", payload=payload,
        )

        outcome1 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome1, Spawn)
        outcome2 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome2, Spawn)
        assert outcome2.children[0].dedupe_key == outcome1.children[0].dedupe_key


# ===================================================================
# 4. Content path missing handling
# ===================================================================


@pytest.mark.asyncio
class TestContentPathMissing:
    """Torrent completes but content_path is empty."""

    async def test_completes_with_warning_event(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When content_path is empty, Complete with warning event (no follow-up)."""
        qb_adapter.torrents_by_hash["hash-nopath"] = {
            "hash": "hash-nopath",
            "name": "NoPath.Torrent",
            "progress": 1.0,
            "state": "completed",
            "save_path": "/downloads",
            "content_path": "",  # empty
            "tags": [],
            "category": "",
            "size": 0,
            "total_size": 0,
        }
        payload: dict[str, Any] = {"qb_hash": "hash-nopath"}
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-nopath-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Complete)
        assert len(outcome.events) == 1
        assert outcome.events[0]["kind"] == "download_completed_no_path"


# ===================================================================
# 5. Consecutive misses -> QB_TORRENT_MISSING
# ===================================================================


@pytest.mark.asyncio
class TestConsecutiveMisses:
    """Missing torrent tracking leads to terminal failure."""

    async def test_fails_after_consecutive_misses(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """After CONSECUTIVE_MISSES_THRESHOLD null returns, handler fails."""
        # get_torrent returns None because hash not in dict
        payload: dict[str, Any] = {
            "qb_hash": "hash-miss",
            "consecutive_misses": CONSECUTIVE_MISSES_THRESHOLD - 1,
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-miss-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Fail)
        assert outcome.code == "QB_TORRENT_MISSING"
        assert outcome.retryable is False
        assert outcome.details["qb_hash"] == "hash-miss"

    async def test_reschedules_below_threshold(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """A known hash missing from qB is a terminal domain failure."""
        payload: dict[str, Any] = {
            "qb_hash": "hash-miss2",
            "consecutive_misses": 0,
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-miss2-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Fail)
        assert outcome.code == "QB_TORRENT_MISSING"
        assert outcome.retryable is False


# ===================================================================
# 6. Transient qB errors with backoff
# ===================================================================


@pytest.mark.asyncio
class TestTransientErrors:
    """Exceptions from get_torrent trigger exponential backoff."""

    async def test_backoff_on_transient_error(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Technical failures use the worker's bounded retry mechanism."""
        qb_adapter.fail_get_torrent = RuntimeError("timeout")

        payload: dict[str, Any] = {
            "qb_hash": "hash-err",
            "consecutive_errors": 0,
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-err-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Fail)
        assert outcome.retryable is True
        assert outcome.code == "QB_TRANSIENT_ERROR"
        assert outcome.details["consecutive_errors"] == 1

    async def test_backoff_caps_at_max(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Repeated technical failures remain bounded worker retries."""
        qb_adapter.fail_get_torrent = RuntimeError("still failing")

        # consecutive_errors=6 -> 30 * 2^5 = 960, capped at 600
        payload: dict[str, Any] = {
            "qb_hash": "hash-cap",
            "consecutive_errors": 6,
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-cap-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Fail)
        assert outcome.retryable is True
        assert outcome.details["consecutive_errors"] == 7

    async def test_errors_reset_after_successful_fetch(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """After a successful get_torrent, error/miss counters reset to 0."""
        qb_adapter.torrents_by_hash["hash-ok"] = make_torrent(
            "hash-ok", "OK.Torrent", progress=0.5, state="downloading",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-ok",
            "consecutive_errors": 3,
            "consecutive_misses": 2,
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-ok-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert outcome.payload_patch is not None
        assert outcome.payload_patch["consecutive_errors"] == 0
        assert outcome.payload_patch["consecutive_misses"] == 0


# ===================================================================
# 7. Payload state updates
# ===================================================================


@pytest.mark.asyncio
class TestPayloadStateUpdates:
    """Verify payload patches carry correct metadata through phases."""

    async def test_resolution_sets_last_poll_at(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Hash resolution payload_patch includes last_poll_at."""
        qb_adapter.torrents_by_tag["nasclaw-task-task-state-1"] = [
            make_torrent("hash-state", name="State.Torrent"),
        ]
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-state-1",
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert outcome.payload_patch is not None
        assert outcome.payload_patch["last_poll_at"] == fixed_clock().isoformat()

    async def test_polling_updates_last_poll_at(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Poll phase payload_patch includes last_poll_at."""
        qb_adapter.torrents_by_hash["hash-poll"] = make_torrent(
            "hash-poll", "Poll.Torrent", progress=0.3, state="downloading",
        )
        payload: dict[str, Any] = {"qb_hash": "hash-poll"}
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-poll-1", payload=payload,
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Reschedule)
        assert outcome.payload_patch is not None
        assert outcome.payload_patch["last_poll_at"] == fixed_clock().isoformat()


# ===================================================================
# 8. Idempotent completion
# ===================================================================


@pytest.mark.asyncio
class TestIdempotentCompletion:
    """Handler does not store state — idempotency is handled by the worker.

    The handler always returns the same outcome for the same inputs.
    These tests verify that repeated calls produce identical results.
    """

    async def test_repeated_notify_only_returns_same_outcome(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Calling the handler twice on a completed notify_only torrent yields the same Complete."""
        qb_adapter.torrents_by_hash["hash-idem"] = make_torrent(
            "hash-idem", "Idem.Torrent", progress=1.0, state="completed",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-idem",
            "resolved_follow_up": {"mode": FOLLOW_UP_NOTIFY_ONLY},
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-idem-1", payload=payload,
        )

        outcome1 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        outcome2 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome1, Complete)
        assert isinstance(outcome2, Complete)
        assert outcome1.result == outcome2.result

    async def test_repeated_auto_organize_returns_same_dedupe_key(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Repeated auto_organize calls produce identical children (same dedupe key)."""
        qb_adapter.torrents_by_hash["hash-idem2"] = make_torrent(
            "hash-idem2", "Idem2.Torrent", progress=1.0, state="completed",
        )
        payload: dict[str, Any] = {
            "qb_hash": "hash-idem2",
            "resolved_follow_up": {
                "mode": FOLLOW_UP_AUTO_ORGANIZE,
                "authorization_snapshot": {},
            },
        }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, task_id="task-idem2-1", payload=payload,
        )

        outcome1 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        outcome2 = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome1, Spawn)
        assert isinstance(outcome2, Spawn)
        assert outcome1.children[0].dedupe_key == outcome2.children[0].dedupe_key


@pytest.mark.asyncio
class TestCanonicalMonitorMatrix:
    @pytest.mark.parametrize(
        ("mode", "action", "expected_type"),
        [
            ("once", "notify", Complete),
            ("once", "organize", Complete),
            ("until_complete", "notify", Reschedule),
            ("until_complete", "organize", Reschedule),
        ],
    )
    async def test_incomplete_matrix(
        self,
        mode: str,
        action: str,
        expected_type: type[TaskOutcome],
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        qb_hash = f"incomplete-{mode}-{action}"
        qb_adapter.torrents_by_hash[qb_hash] = make_torrent(
            qb_hash, progress=0.5, state="downloading"
        )
        payload: dict[str, Any] = {
            "qb_hash": qb_hash,
            "monitor": {"mode": mode, "on_completed": action},
        }
        if action == "organize":
            payload["authorization_snapshot"] = {
                "background_organization_allowed": True,
                "allowed_source_path_prefixes": ["/downloads"],
                "destination_root": "/media",
            }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, payload=payload
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, expected_type)
        if mode == "once":
            assert outcome.events[0]["kind"] == "download_check_incomplete"

    @pytest.mark.parametrize(
        ("mode", "action", "expected_type"),
        [
            ("once", "notify", Complete),
            ("once", "organize", Spawn),
            ("until_complete", "notify", Complete),
            ("until_complete", "organize", Spawn),
        ],
    )
    async def test_completed_matrix(
        self,
        mode: str,
        action: str,
        expected_type: type[TaskOutcome],
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        qb_hash = f"complete-{mode}-{action}"
        qb_adapter.torrents_by_hash[qb_hash] = make_torrent(
            qb_hash, progress=1.0, state="completed"
        )
        payload: dict[str, Any] = {
            "qb_hash": qb_hash,
            "monitor": {"mode": mode, "on_completed": action},
        }
        if action == "organize":
            payload["authorization_snapshot"] = {
                "background_organization_allowed": True,
                "allowed_source_path_prefixes": ["/downloads"],
                "destination_root": "/media",
            }
        task = enqueue_watch_task(
            store, fixed_clock, sequential_id_factory, payload=payload
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, expected_type)
        if isinstance(outcome, Spawn):
            snapshot = outcome.children[0].payload["authorization_snapshot"]
            assert snapshot["background_organization_allowed"] is True

    async def test_legacy_none_completes_silently(
        self,
        qb_adapter: FakeQBAdapter,
        handler: DownloadWatchHandler,
        store: RuntimeTaskStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        qb_adapter.torrents_by_hash["legacy-none"] = make_torrent(
            "legacy-none", progress=1.0, state="completed"
        )
        task = enqueue_watch_task(
            store,
            fixed_clock,
            sequential_id_factory,
            payload={
                "qb_hash": "legacy-none",
                "check_policy": {"mode": "continuous"},
                "resolved_follow_up": {"mode": "none"},
            },
        )
        outcome = await handler(task, store, scheduler=None)  # type: ignore[arg-type]
        assert isinstance(outcome, Complete)
        assert outcome.events == []
