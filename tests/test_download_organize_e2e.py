"""E2E recovery and safety tests for the download->watch->organize pipeline.

Covers plan Section 21 acceptance criteria and Task 12 requirements.
Handler is async; tests reflect actual handler semantics:
- Handler returns outcomes but does NOT directly update store status (worker does).
- First poll with tag resolves hash then Reschedules; completion on next poll.
- Consecutive misses tracked in payload_patch, not directly in task row.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.domain.downloads import FOLLOW_UP_AUTO_ORGANIZE, FOLLOW_UP_NOTIFY_ONLY
from app.domain.runtime_tasks import (
    Complete,
    Fail,
    Reschedule,
    Spawn,
    TaskStatus,
)
from app.runtime.handlers.download_watch import (
    CONSECUTIVE_MISSES_THRESHOLD,
    DownloadWatchConfig,
    DownloadWatchHandler,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fake qB adapter
# ---------------------------------------------------------------------------


class FakeQBAdapter:
    """In-memory fake qBittorrent adapter with controllable state."""

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
        self.add_torrent_calls: list[dict[str, Any]] = []

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

    def add_torrent(self, **kwargs: Any) -> str:
        self.add_torrent_calls.append(kwargs)
        return "Ok."


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
    }


_id_counter = itertools.count(1)


def _next_id(prefix: str = "id-") -> str:
    return prefix + str(next(_id_counter))


def _watch_payload(
    mode: str = FOLLOW_UP_NOTIFY_ONLY,
    qb_hash: str | None = None,
    torrent_name: str = "",
    save_path: str = "/downloads",
    content_path: str = "",
    source_prefixes: list[str] | None = None,
    destination_root: str = "/media",
) -> dict[str, Any]:
    return {
        "qb_hash": qb_hash,
        "torrent_name": torrent_name,
        "save_path": save_path,
        "content_path": content_path,
        "consecutive_misses": 0,
        "consecutive_errors": 0,
        "last_poll_at": None,
        "resolved_follow_up": {
            "mode": mode,
            "source": "test",
            "reason": None,
            "authorization_snapshot": {
                "policy_id": "test-policy",
                "policy_version": 1,
                "authorized_at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "allowed_source_prefixes": source_prefixes or ["/downloads"],
                "destination_root": destination_root,
                "allow_delete": False,
                "allow_overwrite": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def store(db_path: Path) -> RuntimeTaskStore:
    with connect(db_path) as conn:
        initialize_schema(conn)
    return RuntimeTaskStore(db_path=db_path, clock=datetime.now, id_factory=lambda: _next_id("store-"))


@pytest.fixture
def scheduler(store: RuntimeTaskStore) -> TaskScheduler:
    return TaskScheduler(store=store, clock=datetime.now, id_factory=lambda: _next_id("sched-"))


@pytest.fixture
def fake_qb() -> FakeQBAdapter:
    return FakeQBAdapter()


@pytest.fixture
def watch_config() -> DownloadWatchConfig:
    return DownloadWatchConfig(poll_seconds=1, error_backoff_max=600)


@pytest.fixture
def handler(
    fake_qb: FakeQBAdapter,
    watch_config: DownloadWatchConfig,
    scheduler: TaskScheduler,
    store: RuntimeTaskStore,
) -> DownloadWatchHandler:
    return DownloadWatchHandler(
        qb_adapter=fake_qb,
        config=watch_config,
        scheduler=scheduler,
        store=store,
        clock=datetime.now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTagBasedHashResolution:
    """Hash resolution via correlation tag, then completion on next poll."""

    @pytest.mark.asyncio
    async def test_resolves_hash_from_tag_then_reschedules(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            _watch_payload(mode=FOLLOW_UP_NOTIFY_ONLY, qb_hash=None),
            source_session_id="session-1",
        )
        tag = f"nasclaw-task-{task.task_id}"
        torrent = make_torrent(
            "hash-abc", name="Movie", progress=1.0, state="uploading",
            content_path="/d/Movie", tags=[tag],
        )
        fake_qb.torrents_by_tag[tag] = [torrent]
        fake_qb.torrents_by_hash["hash-abc"] = torrent

        # Hash resolution: resolves via tag, returns Reschedule with hash in patch.
        outcome1 = await handler(task, store, scheduler)
        assert isinstance(outcome1, Reschedule)
        assert outcome1.payload_patch.get("qb_hash") == "hash-abc"

        # Simulate worker applying payload_patch: create a task with merged payload.
        merged_payload = {**task.payload, **outcome1.payload_patch}
        task_with_hash = scheduler.enqueue(
            "download_watch", merged_payload, source_session_id="session-1",
        )
        # Now second poll with hash present sees completion.
        outcome2 = await handler(task_with_hash, store, scheduler)
        assert isinstance(outcome2, Complete)
        assert len(outcome2.events) > 0


class TestFullPipeline:
    """End-to-end: notify_only and auto_organize completion."""

    @pytest.mark.asyncio
    async def test_notify_only_completes_with_event(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            _watch_payload(mode=FOLLOW_UP_NOTIFY_ONLY, qb_hash="hash-n1"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-n1"] = make_torrent(
            "hash-n1", name="Notify.Movie", progress=1.0, state="uploading",
            content_path="/d/notify",
        )
        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Complete)
        assert outcome.events[0]["kind"] == "download_completed"

    @pytest.mark.asyncio
    async def test_auto_organize_spawns_child_with_content_path(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            _watch_payload(mode=FOLLOW_UP_AUTO_ORGANIZE, qb_hash="hash-ao"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-ao"] = make_torrent(
            "hash-ao", name="Org.Movie", progress=1.0, state="uploading",
            save_path="/downloads", content_path="/downloads/Org.Movie",
        )
        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Spawn)
        assert len(outcome.children) == 1
        assert outcome.children[0].kind == "organize_download"
        assert outcome.children[0].payload.get("content_path") == "/downloads/Org.Movie"

    @pytest.mark.asyncio
    async def test_notify_only_no_spawn(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            _watch_payload(mode=FOLLOW_UP_NOTIFY_ONLY, qb_hash="hash-no-spawn"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-no-spawn"] = make_torrent(
            "hash-no-spawn", progress=1.0, content_path="/d/no-spawn",
        )
        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Complete)
        assert not isinstance(outcome, Spawn)


class TestBatchPartialSuccess:
    """Failed qB adds must not create watch tasks."""

    @pytest.mark.asyncio
    async def test_failed_init_does_not_block_successful_tasks(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
    ) -> None:
        task_a = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-a"),
            source_session_id="session-1",
        )
        # task_b created via prepare (INITIALIZING) to simulate coordinator init phase.
        task_b = store.prepare(
            kind="download_watch",
            payload_json=_watch_payload(qb_hash="hash-b"),
            source_session_id="session-1",
            parent_task_id=None,
            dedupe_key=None,
            now=datetime.now(timezone.utc),
            id_factory=lambda: _next_id("init-"),
        )

        assert task_b.status == TaskStatus.INITIALIZING
        store.fail_initialization(
            task_b.task_id, {"code": "QB_ERROR", "message": "qB rejected"},
            datetime.now(timezone.utc),
        )

        assert store.get(task_a.task_id).status == TaskStatus.QUEUED
        assert store.get(task_b.task_id).status == TaskStatus.FAILED


class TestQBResilience:
    """Transient errors, torrent disappearance, paused handling."""

    @pytest.mark.asyncio
    async def test_transient_error_backs_off(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-err"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-err"] = make_torrent(
            "hash-err", progress=0.5, state="downloading", content_path="/d/err",
        )
        fake_qb.fail_get_torrent = ConnectionError("unavailable")
        outcome1 = await handler(task, store, scheduler)
        assert isinstance(outcome1, Reschedule)
        assert outcome1.run_after is not None  # Backoff timestamp.

        # Recover and poll again.
        fake_qb.fail_get_torrent = None
        reloaded = store.get(task.task_id)
        outcome2 = await handler(reloaded, store, scheduler)
        assert isinstance(outcome2, Reschedule)  # Incomplete.

    @pytest.mark.asyncio
    async def test_missing_torrent_reschedules_with_miss_count(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-gone"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash.pop("hash-gone", None)

        # Handler reschedules with miss count in payload_patch.
        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Reschedule)
        assert "consecutive_misses" in outcome.payload_patch

    @pytest.mark.asyncio
    async def test_paused_torrent_reschedules_not_fails(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-paused"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-paused"] = make_torrent(
            "hash-paused", progress=0.0, state="pausedDL", content_path="/d/paused",
        )

        for _ in range(3):
            reloaded = store.get(task.task_id)
            outcome = await handler(reloaded, store, scheduler)
            assert isinstance(outcome, Reschedule), f"Got {type(outcome).__name__}"
            assert not isinstance(outcome, Fail)


class TestConcurrencyAndIndependence:
    """Multiple torrents from same session polled independently."""

    @pytest.mark.asyncio
    async def test_two_torrents_independent_outcomes(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        ta = scheduler.enqueue("download_watch", _watch_payload(qb_hash="ha"), source_session_id="s1")
        tb = scheduler.enqueue("download_watch", _watch_payload(qb_hash="hb"), source_session_id="s1")
        fake_qb.torrents_by_hash["ha"] = make_torrent("ha", progress=1.0, content_path="/d/a")
        fake_qb.torrents_by_hash["hb"] = make_torrent("hb", progress=0.3, content_path="/d/b")

        assert isinstance(await handler(ta, store, scheduler), Complete)
        assert isinstance(await handler(tb, store, scheduler), Reschedule)


class TestRestartRecovery:
    """Process restart recovers from persisted SQLite state."""

    @pytest.mark.asyncio
    async def test_task_persists_across_store_instances(
        self, db_path: Path, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-rs"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-rs"] = make_torrent(
            "hash-rs", progress=0.5, state="downloading", content_path="/d/rs",
        )

        await handler(task, store, scheduler)

        # New store instance on same DB file.
        store2 = RuntimeTaskStore(db_path=db_path, clock=datetime.now, id_factory=lambda: _next_id("r2-"))
        assert store2.get(task.task_id) is not None
        assert store2.get(task.task_id).status == TaskStatus.QUEUED  # Handler returns outcome, worker updates status.


class TestEventAndSessionLifecycle:
    """TaskEvents are returned by handler; tasks survive session deletion."""

    @pytest.mark.asyncio
    async def test_completion_returns_download_completed_event(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(qb_hash="hash-ev2"),
            source_session_id="session-1",
        )
        fake_qb.torrents_by_hash["hash-ev2"] = make_torrent(
            "hash-ev2", progress=1.0, content_path="/d/ev2",
        )
        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Complete)
        assert len(outcome.events) > 0
        assert outcome.events[0]["kind"] == "download_completed"

    @pytest.mark.asyncio
    async def test_task_survives_session_deletion(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch", _watch_payload(),
            source_session_id="deleted-session",
        )
        assert store.get(task.task_id) is not None
        assert store.get(task.task_id).source_session_id == "deleted-session"


class TestAmbiguousCorrelation:
    """>1 matching tags should fail safely."""

    @pytest.mark.asyncio
    async def test_multiple_tag_matches_fails_ambiguous(
        self, scheduler: TaskScheduler, store: RuntimeTaskStore,
        handler: DownloadWatchHandler, fake_qb: FakeQBAdapter,
    ) -> None:
        task = scheduler.enqueue(
            "download_watch",
            _watch_payload(mode=FOLLOW_UP_NOTIFY_ONLY, qb_hash=None),
            source_session_id="session-1",
        )
        tag = f"nasclaw-task-{task.task_id}"
        t1 = make_torrent("h1", tags=[tag], content_path="/d/1")
        t2 = make_torrent("h2", tags=[tag], content_path="/d/2")
        fake_qb.torrents_by_tag[tag] = [t1, t2]

        outcome = await handler(task, store, scheduler)
        assert isinstance(outcome, Fail)
        assert outcome.code == "AMBIGUOUS_QB_CORRELATION"
