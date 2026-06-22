"""Tests for the DownloadCoordinator orchestration layer.

Tests the full submission sequence (prepare -> qB -> activate), after_download
resolution, qB failure path, batch partial success, stale initialization
reconciliation, and error cases.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from app.domain.downloads import (
    DownloadSubmissionRequest,
    FOLLOW_UP_AUTO_ORGANIZE,
    FOLLOW_UP_NONE,
    FOLLOW_UP_NOTIFY_ONLY,
)
from app.domain.organization import (
    OrganizationAutomationPolicy,
    default_organization_automation_policy,
)
from app.domain.runtime_tasks import RuntimeTask, TaskStatus, utc_now_iso
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.services.download_coordinator import (
    DownloadCoordinator,
    WATCH_TASK_KIND,
)
from app.services.download_submission import DownloadSubmission
from app.services.organization_policy_store import (
    OrganizationAutomationPolicyStore,
)
from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fake clock & ID factory
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """Return a deterministic clock frozen at 2026-06-15T10:00:00+00:00."""
    fixed = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

    def clock() -> datetime:
        return fixed

    return clock


@pytest.fixture
def sequential_id_factory() -> Callable[[], str]:
    """Return an ID factory that produces sequential strings (t-1, t-2, ...)."""
    counter = itertools.count(1)

    def factory() -> str:
        return f"t-{next(counter)}"

    return factory


# ---------------------------------------------------------------------------
# Temp SQLite store + scheduler
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_coordinator.db"


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


# ---------------------------------------------------------------------------
# Fake policy store
# ---------------------------------------------------------------------------


class FakePolicyStore:
    """In-memory policy store with configurable default."""

    def __init__(self, policy: OrganizationAutomationPolicy | None = None) -> None:
        self._policy = policy or default_organization_automation_policy()

    def load(self) -> OrganizationAutomationPolicy:
        return self._policy

    def set_policy(self, policy: OrganizationAutomationPolicy) -> None:
        self._policy = policy


@pytest.fixture
def policy_store() -> FakePolicyStore:
    return FakePolicyStore()


# ---------------------------------------------------------------------------
# Fake DownloadSubmission (submission service mock)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_submission() -> MagicMock:
    """Return a MagicMock that acts as a successful DownloadSubmission by default.

    The mock's ``submit`` method returns a dict with status ``"submitted_paused"``
    and a fake qb_hash.
    """
    m = MagicMock(spec=DownloadSubmission)
    m.submit.return_value = {
        "resource_title": "Test Movie",
        "external_id": "123",
        "qb_category": "movie",
        "qb_hash": "fake-hash",
        "status": "submitted_paused",
        "subtitle_count": 0,
    }
    m._default_tags = ["mteam"]
    return m


# ---------------------------------------------------------------------------
# Coordinator factory helper
# ---------------------------------------------------------------------------


def build_coordinator(
    submission: DownloadSubmission | MagicMock,
    scheduler: TaskScheduler,
    policy_store: OrganizationAutomationPolicyStore | FakePolicyStore,
    fixed_clock: Callable[[], datetime],
    sequential_id_factory: Callable[[], str],
    runtime_store: RuntimeTaskStore | None = None,
) -> DownloadCoordinator:
    return DownloadCoordinator(
        submission=submission,
        scheduler=scheduler,
        policy_store=policy_store,
        clock=fixed_clock,
        id_factory=sequential_id_factory,
        store=runtime_store,
    )


def make_request(**overrides: Any) -> DownloadSubmissionRequest:
    defaults: dict[str, Any] = {"torrent_id": "123", "qb_category": "movie"}
    defaults.update(overrides)
    return DownloadSubmissionRequest(**defaults)


# ---------------------------------------------------------------------------
# Tests: full submission sequence
# ---------------------------------------------------------------------------


class TestFullSubmissionSequence:
    """Happy path: prepare -> qB -> activate."""

    def test_submit_returns_accepted_with_watch_task(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        assert result.status == "accepted"
        assert result.watch_task_id != ""
        assert result.torrent_id == "123"
        assert result.submission_receipt is not None
        assert result.submission_receipt["status"] == "submitted_paused"
        assert result.submission_receipt["qb_hash"] == "fake-hash"

    def test_submit_creates_watch_task(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        # Verify the watch task was created and then activated
        task = scheduler.get(result.watch_task_id)
        assert task is not None
        assert task.kind == WATCH_TASK_KIND
        assert task.status == TaskStatus.QUEUED
        assert task.payload["torrent_id"] == "123"
        assert task.payload["qb_category"] == "movie"

    def test_submit_passes_correlation_tag(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        # The correlation tag should match the watch task ID
        mock_submission.submit.assert_called_once()
        _kwargs = mock_submission.submit.call_args[1]
        assert _kwargs.get("correlation_tag") == result.watch_task_id

    def test_submit_embeds_receipt_in_watch_payload(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        task = scheduler.get(result.watch_task_id)
        assert task is not None
        assert task.payload["qb_hash"] == "fake-hash"
        assert task.payload["receipt"]["status"] == "submitted_paused"

    def test_submit_with_source_session_id(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(), source_session_id="session-abc")

        task = scheduler.get(result.watch_task_id)
        assert task is not None
        assert task.source_session_id == "session-abc"


# ---------------------------------------------------------------------------
# Tests: after_download resolution
# ---------------------------------------------------------------------------


class TestAfterDownloadResolution:
    """Three-way precedence: request -> settings -> fallback."""

    def test_none_falls_to_settings_default(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """request.after_download=None, policy has default_after_download='notify_only'."""
        policy = OrganizationAutomationPolicy(
            enabled=True,
            default_after_download=FOLLOW_UP_NOTIFY_ONLY,
        )
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=None))

        assert result.resolved_follow_up.mode == FOLLOW_UP_NOTIFY_ONLY
        assert result.resolved_follow_up.source == "settings"

    def test_explicit_notify_only(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """request.after_download='notify_only' wins over settings."""
        policy = OrganizationAutomationPolicy(
            enabled=True,
            default_after_download=FOLLOW_UP_AUTO_ORGANIZE,
        )
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=FOLLOW_UP_NOTIFY_ONLY))

        assert result.resolved_follow_up.mode == FOLLOW_UP_NOTIFY_ONLY
        assert result.resolved_follow_up.source == "request"

    def test_explicit_auto_organize_with_policy_enabled(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """auto_organize with policy enabled creates authorization snapshot."""
        policy = OrganizationAutomationPolicy(
            enabled=True,
            default_after_download=FOLLOW_UP_NOTIFY_ONLY,
            allowed_source_path_prefixes=["/volume1/影视"],
            destination_root="/volume1/organized",
        )
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=FOLLOW_UP_AUTO_ORGANIZE))

        assert result.status == "accepted"
        assert result.resolved_follow_up.mode == FOLLOW_UP_AUTO_ORGANIZE
        assert result.resolved_follow_up.source == "request"
        assert result.resolved_follow_up.authorization_snapshot is not None
        assert result.resolved_follow_up.authorization_snapshot["enabled"] is True
        assert result.resolved_follow_up.authorization_snapshot["destination_root"] == "/volume1/organized"

    def test_explicit_auto_organize_with_policy_disabled_returns_error(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """auto_organize requires policy.enabled; returns failed otherwise."""
        policy = OrganizationAutomationPolicy(enabled=False)
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=FOLLOW_UP_AUTO_ORGANIZE))

        assert result.status == "failed"
        assert result.error is not None
        assert "disabled" in result.error.lower()
        # No watch task should be created for a pre-submission validation failure
        assert result.watch_task_id == ""

    def test_settings_default_notify_only_is_not_none(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When policy default_after_download is 'notify_only', None request resolves to it."""
        policy = OrganizationAutomationPolicy(
            enabled=False,
            default_after_download=FOLLOW_UP_NOTIFY_ONLY,
        )
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=None))

        assert result.resolved_follow_up.mode == FOLLOW_UP_NOTIFY_ONLY
        assert result.resolved_follow_up.source == "settings"

    def test_authorization_snapshot_in_watch_payload(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Snapshot is stored in the activated watch task payload."""
        policy = OrganizationAutomationPolicy(
            enabled=True,
            default_after_download=FOLLOW_UP_AUTO_ORGANIZE,
            allowed_source_path_prefixes=["/media"],
            destination_root="/media/organized",
        )
        store = FakePolicyStore(policy)
        coord = build_coordinator(
            mock_submission, scheduler, store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request(after_download=FOLLOW_UP_AUTO_ORGANIZE))

        task = scheduler.get(result.watch_task_id)
        assert task is not None
        resolved = task.payload.get("resolved_follow_up", {})
        assert resolved.get("authorization_snapshot") is not None
        assert resolved["authorization_snapshot"]["enabled"] is True
        assert resolved["authorization_snapshot"]["destination_root"] == "/media/organized"


# ---------------------------------------------------------------------------
# Tests: qB failure path
# ---------------------------------------------------------------------------


class TestQBFailurePath:
    """qB submission failure triggers fail_initialization."""

    def test_qb_failure_returns_failed_status(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When the submission service returns an error, coordinator returns failed."""
        mock_submission.submit.return_value = {
            "resource_title": None,
            "external_id": "123",
            "qb_category": "movie",
            "qb_hash": None,
            "status": "error",
            "error": "[CONFLICT] Torrent already exists",
            "error_code": "CONFLICT",
            "subtitle_count": 0,
        }

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        assert result.status == "duplicate"
        assert result.watch_task_id == ""
        assert "[CONFLICT]" in (result.error or "")

    def test_qb_failure_with_unknown_error_code(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Non-CONFLICT errors map to 'failed' status."""
        mock_submission.submit.return_value = {
            "status": "error",
            "error": "[NETWORK_ERROR] Connection refused",
            "error_code": "NETWORK_ERROR",
        }

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        assert result.status == "failed"
        assert result.watch_task_id == ""

    def test_qb_failure_triggers_fail_initialization(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """The INITIALIZING watch task is failed after qB error."""
        mock_submission.submit.return_value = {
            "status": "error",
            "error": "[NETWORK_ERROR] Timeout",
            "error_code": "NETWORK_ERROR",
        }

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        # A watch task was prepared but then failed
        # watch_task_id is empty in the result, but the task record exists
        # Since fail_initialization was called, the task should now be FAILED
        tasks = store.list_tasks(kind=WATCH_TASK_KIND, status=TaskStatus.FAILED.value)
        assert len(tasks) == 1
        assert tasks[0].error is not None
        assert tasks[0].error["code"] == "NETWORK_ERROR"

    def test_qb_failure_preserves_error_in_failed_task(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Error details are stored in the failed watch task."""
        mock_submission.submit.return_value = {
            "status": "error",
            "error": "[REJECTED] Category not allowed",
            "error_code": "REJECTED",
        }

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        result = coord.submit(make_request())

        assert result.status == "failed"

        tasks = store.list_tasks(kind=WATCH_TASK_KIND, status=TaskStatus.FAILED.value)
        assert len(tasks) == 1
        assert tasks[0].error["code"] == "REJECTED"
        assert "Category not allowed" in tasks[0].error["message"]


# ---------------------------------------------------------------------------
# Tests: batch submission (partial success)
# ---------------------------------------------------------------------------


class TestBatchSubmission:
    """submit_many handles mixed success/failure correctly."""

    def test_all_succeed(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        batch_result = coord.submit_many([
            make_request(torrent_id="101", qb_category="movie"),
            make_request(torrent_id="102", qb_category="movie"),
        ])

        assert len(batch_result.items) == 2
        assert all(item.status == "accepted" for item in batch_result.items)
        assert batch_result.summary == {"accepted": 2}

    def test_partial_success_preserves_watches_for_successes(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Only successful submissions get activated watch tasks."""
        call_count = 0

        def _side_effect(request: DownloadSubmissionRequest, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # second call fails
                return {
                    "status": "error",
                    "error": "[CONFLICT] Duplicate",
                    "error_code": "CONFLICT",
                }
            return {
                "resource_title": f"Movie {request.torrent_id}",
                "external_id": request.torrent_id,
                "qb_category": request.qb_category or "",
                "qb_hash": f"hash-{request.torrent_id}",
                "status": "submitted_paused",
                "subtitle_count": 0,
            }

        mock_submission.submit.side_effect = _side_effect

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        batch_result = coord.submit_many([
            make_request(torrent_id="101", qb_category="movie"),
            make_request(torrent_id="102", qb_category="movie"),
        ])

        assert batch_result.items[0].status == "accepted"
        assert batch_result.items[0].watch_task_id != ""
        assert batch_result.items[1].status == "duplicate"
        assert batch_result.items[1].watch_task_id == ""
        assert batch_result.summary == {"accepted": 1, "duplicate": 1}

        # Only the success should have an activated (QUEUED) watch task
        queued_tasks = store.list_tasks(
            kind=WATCH_TASK_KIND, status=TaskStatus.QUEUED.value
        )
        assert len(queued_tasks) == 1
        assert queued_tasks[0].payload["torrent_id"] == "101"

        # The failure should have a FAILED watch task
        failed_tasks = store.list_tasks(
            kind=WATCH_TASK_KIND, status=TaskStatus.FAILED.value
        )
        assert len(failed_tasks) == 1
        assert failed_tasks[0].payload["torrent_id"] == "102"

    def test_all_fail(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        mock_submission.submit.return_value = {
            "status": "error",
            "error": "[NETWORK_ERROR] Down",
            "error_code": "NETWORK_ERROR",
        }

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        batch_result = coord.submit_many([
            make_request(torrent_id="201"),
            make_request(torrent_id="202"),
        ])

        assert all(item.status == "failed" for item in batch_result.items)
        assert batch_result.summary == {"failed": 2}

    def test_summary_counts_multiple_statuses(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        call_count = 0

        def _side_effect(request: DownloadSubmissionRequest, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "status": "submitted_paused",
                    "qb_hash": "h1",
                    "resource_title": "A",
                    "external_id": "301",
                    "qb_category": "movie",
                    "subtitle_count": 0,
                }
            elif call_count == 2:
                return {
                    "status": "error",
                    "error": "[CONFLICT] dup",
                    "error_code": "CONFLICT",
                }
            else:
                return {
                    "status": "error",
                    "error": "[NETWORK_ERROR] down",
                    "error_code": "NETWORK_ERROR",
                }

        mock_submission.submit.side_effect = _side_effect

        coord = build_coordinator(
            mock_submission, scheduler, policy_store, fixed_clock, sequential_id_factory
        )
        batch_result = coord.submit_many([
            make_request(torrent_id="301"),
            make_request(torrent_id="302"),
            make_request(torrent_id="303"),
        ])

        assert batch_result.summary == {"accepted": 1, "duplicate": 1, "failed": 1}
        assert batch_result.items[0].status == "accepted"
        assert batch_result.items[1].status == "duplicate"
        assert batch_result.items[2].status == "failed"


# ---------------------------------------------------------------------------
# Tests: stale initialization reconciliation
# ---------------------------------------------------------------------------


class TestStaleReconciliation:
    """Startup reconciliation of INITIALIZING tasks left by crashes."""

    def test_reconcile_stale_initializing(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """INITIALIZING download_watch tasks are failed at startup."""
        # Directly create tasks in INITIALIZING status via the store
        task1 = store.prepare(
            kind=WATCH_TASK_KIND,
            payload_json={"torrent_id": "orphan-1"},
            source_session_id=None,
            parent_task_id=None,
            dedupe_key=None,
            now=fixed_clock(),
            id_factory=lambda: "orphan-1",
        )
        task2 = store.prepare(
            kind=WATCH_TASK_KIND,
            payload_json={"torrent_id": "orphan-2"},
            source_session_id=None,
            parent_task_id=None,
            dedupe_key=None,
            now=fixed_clock(),
            id_factory=lambda: "orphan-2",
        )

        assert task1.status == TaskStatus.INITIALIZING
        assert task2.status == TaskStatus.INITIALIZING

        coord = build_coordinator(
            mock_submission,
            scheduler,
            policy_store,
            fixed_clock,
            sequential_id_factory,
            runtime_store=store,
        )
        reconciled = coord.reconcile_stale_initializing()

        assert len(reconciled) == 2
        for r in reconciled:
            assert r.status == TaskStatus.FAILED
            assert r.error is not None
            assert r.error["code"] == "STARTUP_RECONCILE"

        # Verify they are persisted as FAILED
        for task_id in ("orphan-1", "orphan-2"):
            t = store.get(task_id)
            assert t is not None
            assert t.status == TaskStatus.FAILED

    def test_reconcile_does_not_touch_queued_tasks(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Tasks already in QUEUED status are left alone."""
        queued = store.enqueue(
            kind=WATCH_TASK_KIND,
            payload_json={"torrent_id": "healthy"},
            source_session_id=None,
            parent_task_id=None,
            dedupe_key=None,
            run_after=None,
            now=fixed_clock(),
            id_factory=lambda: "healthy-1",
        )
        assert queued.status == TaskStatus.QUEUED

        coord = build_coordinator(
            mock_submission,
            scheduler,
            policy_store,
            fixed_clock,
            sequential_id_factory,
            runtime_store=store,
        )
        reconciled = coord.reconcile_stale_initializing()

        assert len(reconciled) == 0
        t = store.get("healthy-1")
        assert t is not None
        assert t.status == TaskStatus.QUEUED

    def test_reconcile_only_targets_download_watch_kind(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """INITIALIZING tasks of other kinds are not reconciled."""
        other = store.prepare(
            kind="organize_download",
            payload_json={"torrent_id": "other"},
            source_session_id=None,
            parent_task_id=None,
            dedupe_key=None,
            now=fixed_clock(),
            id_factory=lambda: "other-1",
        )

        coord = build_coordinator(
            mock_submission,
            scheduler,
            policy_store,
            fixed_clock,
            sequential_id_factory,
            runtime_store=store,
        )
        reconciled = coord.reconcile_stale_initializing()

        assert len(reconciled) == 0
        t = store.get("other-1")
        assert t is not None
        assert t.status == TaskStatus.INITIALIZING

    def test_reconcile_no_store_returns_empty(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """Without a store provided, reconcile logs warning and returns empty list."""
        coord = build_coordinator(
            mock_submission,
            scheduler,
            policy_store,
            fixed_clock,
            sequential_id_factory,
            runtime_store=None,
        )
        reconciled = coord.reconcile_stale_initializing()
        assert reconciled == []

    def test_reconcile_no_stale_tasks(
        self,
        mock_submission: MagicMock,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        policy_store: FakePolicyStore,
        fixed_clock: Callable[[], datetime],
        sequential_id_factory: Callable[[], str],
    ) -> None:
        """When no stale INITIALIZING tasks exist, returns empty list."""
        coord = build_coordinator(
            mock_submission,
            scheduler,
            policy_store,
            fixed_clock,
            sequential_id_factory,
            runtime_store=store,
        )
        reconciled = coord.reconcile_stale_initializing()
        assert reconciled == []
