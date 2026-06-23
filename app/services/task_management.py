"""Task management service — safe Agent-facing layer over TaskScheduler.

``TaskManagementService`` maps Conversation-Agent semantic operations
(create scheduled check, list, cancel, reschedule) to the existing
``TaskScheduler`` without exposing raw payload internals, authorization
snapshots, or store-level primitives to callers.

Design rules:
- Never access ``RuntimeTaskStore`` directly — all mutations go through the
  injected ``TaskScheduler``.
- ``TaskView`` is the only model returned to Agent-facing code.  It must
  never leak raw payload, token URLs, or authorization snapshots.
- Dedupe keys use the pattern ``scheduled-download-check:{session_id}:{idempotency_key}``
  so approval retries are idempotent without embedding mutable ``run_at``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.downloads import (
    FOLLOW_UP_AUTO_ORGANIZE,
    FOLLOW_UP_NOTIFY_ONLY,
    DownloadCheckPolicy,
    ScheduleDownloadCheckRequest,
    ScheduledDownloadCheckReceipt,
    is_future_time,
    normalize_to_utc,
)
from app.domain.organization import OrganizationAutomationPolicy
from app.domain.runtime_tasks import RuntimeTask, TaskStatus
from app.runtime.scheduler import TaskScheduler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dedupe key prefix
# ---------------------------------------------------------------------------

SCHEDULED_CHECK_DEDUPE_PREFIX = "scheduled-download-check"


def _scheduled_check_dedupe_key(session_id: str, idempotency_key: str) -> str:
    """Build a stable dedupe key for a scheduled download check.

    The key intentionally omits ``run_at`` so that rescheduling does not
    break dedupe identity — the same approval retry returns the existing
    task even if the caller changed the time between calls.
    """
    return f"{SCHEDULED_CHECK_DEDUPE_PREFIX}:{session_id}:{idempotency_key}"


# ---------------------------------------------------------------------------
# Public view models (safe for Agent / HTTP exposure)
# ---------------------------------------------------------------------------


class TaskView(BaseModel):
    """Safe projection of a ``RuntimeTask`` for Agent and HTTP consumers.

    Never exposes raw ``payload_json``, ``result_json``, ``error_json``,
    token URLs, or authorization snapshots.
    """

    task_id: str
    kind: str
    status: str
    run_after: str | None = None
    description: str = ""
    source_session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_runtime_task(cls, task: RuntimeTask) -> "TaskView":
        """Build a safe view from a raw ``RuntimeTask``.

        Derives a human-readable *description* from the task kind and
        payload without exposing internal details.
        """
        payload = task.payload or {}
        description = cls._build_description(task.kind, payload)
        return cls(
            task_id=task.task_id,
            kind=task.kind,
            status=task.status.value,
            run_after=task.run_after,
            description=description,
            source_session_id=task.source_session_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    @staticmethod
    def _build_description(kind: str, payload: dict[str, Any]) -> str:
        if kind == "download_watch":
            name = payload.get("torrent_name", "") or payload.get("qb_hash", "") or "?"
            check_policy = payload.get("check_policy") or {}
            mode = check_policy.get("mode", "continuous") if isinstance(check_policy, dict) else "continuous"
            if mode == "once":
                return f"定时检查: {name}"
            return f"下载监控: {name}"
        if kind == "organize_download":
            name = payload.get("torrent_name", "") or payload.get("qb_hash", "") or "?"
            return f"整理: {name}"
        return f"{kind}"


class TaskListQuery(BaseModel):
    """Filter parameters for listing tasks."""

    status: str | None = None
    kind: str | None = None
    source_session_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------


class TaskManagementError(ValueError):
    """Domain error with a machine-readable code for Agent/tool feedback."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TaskManagementService:
    """Safe, semantic task-management API for the Conversation Agent.

    Every mutation goes through the injected ``TaskScheduler``.  The service
    owns domain rules (follow-up resolution, policy validation, dedupe) that
    should never be duplicated in individual Tool implementations.
    """

    def __init__(
        self,
        scheduler: TaskScheduler,
        qb_adapter: QBittorrentAdapter,
        organization_policy_store: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialise the service.

        Args:
            scheduler: The existing ``TaskScheduler`` for all task lifecycle
                operations.
            qb_adapter: qBittorrent adapter for torrent validation at creation
                time.
            organization_policy_store: Optional store for reading the current
                organisation automation policy.  Required when
                ``auto_organize`` follow-up is used.
            clock: Callable returning current UTC ``datetime``.
        """
        self._scheduler = scheduler
        self._qb = qb_adapter
        self._org_policy_store = organization_policy_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Create scheduled download check
    # ------------------------------------------------------------------

    def create_download_check(
        self,
        request: ScheduleDownloadCheckRequest,
        source_session_id: str | None,
        idempotency_key: str,
    ) -> ScheduledDownloadCheckReceipt:
        """Create a one-shot future download-watch task.

        Steps (hidden from callers):
        1. Validate the qB hash against the live qBittorrent instance.
        2. Normalise ``run_at`` to canonical UTC and reject past times.
        3. Resolve follow-up mode (request > Settings default > notify_only).
        4. For ``auto_organize``, validate the organization policy and
           capture an immutable authorization snapshot.
        5. Build a typed payload compatible with ``DownloadWatchHandler``.
        6. Enqueue via ``TaskScheduler.enqueue()`` with a stable dedupe key.
        7. Return a safe receipt.

        Raises:
            TaskManagementError: On validation failure (torrent missing,
                invalid time, policy disabled, etc.).
        """
        now = self._clock()

        # 1. Validate torrent exists in qB.
        torrent_hash = request.torrent_hash.strip()
        if not torrent_hash:
            raise TaskManagementError(
                "MISSING_TORRENT_HASH",
                "torrent_hash is required and must not be empty",
            )

        try:
            torrent = self._qb.get_torrent(torrent_hash)
        except Exception as exc:
            raise TaskManagementError(
                "QB_UNAVAILABLE",
                f"Cannot reach qBittorrent to validate torrent: {exc}",
            ) from exc

        if torrent is None:
            raise TaskManagementError(
                "TORRENT_NOT_FOUND",
                f"Torrent with hash {torrent_hash!r} was not found in qBittorrent",
            )

        torrent_name = torrent.get("name", "") or torrent_hash
        save_path = torrent.get("save_path", "") or ""

        # 2. Normalise run_at to canonical UTC.
        try:
            run_at_utc = normalize_to_utc(request.run_at)
        except ValueError as exc:
            raise TaskManagementError(
                "INVALID_RUN_AT",
                str(exc),
            ) from exc

        if not is_future_time(run_at_utc, now=now):
            raise TaskManagementError(
                "RUN_AT_NOT_FUTURE",
                f"run_at must be in the future: {request.run_at!r}",
            )

        # 3. Resolve follow-up: request > Settings default > notify_only.
        resolved_follow_up = self._resolve_follow_up(request.follow_up)

        # 4. For auto_organize, validate policy and capture snapshot.
        authorization_snapshot: dict[str, Any] | None = None
        if resolved_follow_up == FOLLOW_UP_AUTO_ORGANIZE:
            authorization_snapshot = self._capture_authorization_snapshot()

        # 5. Build typed payload.
        resolved_follow_up_dict: dict[str, Any] = {
            "mode": resolved_follow_up,
            "source": "request" if request.follow_up else "settings",
            "reason": (
                "Explicit conversation-created scheduled check."
                if request.follow_up
                else "Conversation-created scheduled check using Settings default."
            ),
        }
        if authorization_snapshot is not None:
            resolved_follow_up_dict["authorization_snapshot"] = authorization_snapshot

        check_policy = DownloadCheckPolicy(
            mode="once",
            on_incomplete="notify",
        )

        payload: dict[str, Any] = {
            "qb_hash": torrent_hash,
            "torrent_name": torrent_name,
            "save_path": save_path,
            "check_policy": check_policy.model_dump(),
            "resolved_follow_up": resolved_follow_up_dict,
            "scheduled_for": run_at_utc,
            "created_via": "conversation_agent",
        }

        # 6. Enqueue via dedupe-protected scheduler call.
        session_id = source_session_id or ""
        dedupe_key = _scheduled_check_dedupe_key(session_id, idempotency_key)

        task = self._scheduler.enqueue(
            kind="download_watch",
            payload=payload,
            source_session_id=source_session_id,
            dedupe_key=dedupe_key,
            run_after=run_at_utc,
        )

        logger.info(
            "Created scheduled download check task=%s hash=%s run_at=%s follow_up=%s",
            task.task_id,
            torrent_hash,
            run_at_utc,
            resolved_follow_up,
        )

        # 7. Return safe receipt.
        return ScheduledDownloadCheckReceipt(
            task_id=task.task_id,
            torrent_hash=torrent_hash,
            torrent_name=torrent_name,
            run_at=run_at_utc,
            check_mode="once",
            resolved_follow_up=resolved_follow_up,  # type: ignore[arg-type]
            if_incomplete="notify",
        )

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_tasks(self, query: TaskListQuery | None = None) -> list[TaskView]:
        """Return safe ``TaskView`` projections for matching tasks.

        Delegates to ``TaskScheduler.list_tasks()``, then maps every
        ``RuntimeTask`` through ``TaskView.from_runtime_task()`` to strip
        internal fields.
        """
        q = query or TaskListQuery()
        raw_tasks = self._scheduler.list_tasks(
            status=q.status,
            kind=q.kind,
            source_session_id=q.source_session_id,
            limit=q.limit,
        )
        return [TaskView.from_runtime_task(t) for t in raw_tasks]

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel_task(self, task_id: str) -> TaskView:
        """Atomically cancel a task that is still ``QUEUED`` or ``WAITING``.

        Only pending (not-yet-claimed) tasks can be cancelled through this
        method.  ``RUNNING`` and terminal tasks are rejected with a clear
        error.

        Raises:
            TaskManagementError: When the task does not exist, is already
                terminal, or is currently ``RUNNING``.
        """
        task = self._scheduler.cancel_pending(task_id)
        return TaskView.from_runtime_task(task)

    # ------------------------------------------------------------------
    # Reschedule
    # ------------------------------------------------------------------

    def reschedule_task(self, task_id: str, run_at: str) -> TaskView:
        """Atomically update the ``run_after`` of a pending once-mode task.

        Only ``QUEUED`` / ``WAITING`` tasks with ``check_policy.mode=once``
        are eligible.  Continuous watch tasks and terminal tasks are rejected.

        Raises:
            TaskManagementError: When the task is ineligible or *run_at* is
                invalid.
        """
        # Normalise the new time.
        try:
            run_at_utc = normalize_to_utc(run_at)
        except ValueError as exc:
            raise TaskManagementError("INVALID_RUN_AT", str(exc)) from exc

        if not is_future_time(run_at_utc, now=self._clock()):
            raise TaskManagementError(
                "RUN_AT_NOT_FUTURE",
                f"New run_at must be in the future: {run_at!r}",
            )

        task = self._scheduler.reschedule_pending_once(
            task_id=task_id,
            run_after=run_at_utc,
        )
        return TaskView.from_runtime_task(task)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_follow_up(
        self,
        explicit: Literal["notify_only", "auto_organize"] | None,
    ) -> str:
        """Resolve follow-up mode: explicit > Settings default > notify_only."""
        if explicit is not None:
            return explicit

        # Try Settings default.
        if self._org_policy_store is not None:
            try:
                policy: OrganizationAutomationPolicy = self._org_policy_store.load()
                if policy.enabled and policy.default_after_download in (
                    FOLLOW_UP_AUTO_ORGANIZE,
                    FOLLOW_UP_NOTIFY_ONLY,
                ):
                    return policy.default_after_download
            except Exception:
                logger.warning(
                    "Failed to read organization policy; falling back to notify_only"
                )

        return FOLLOW_UP_NOTIFY_ONLY

    def _capture_authorization_snapshot(self) -> dict[str, Any]:
        """Validate current org policy and capture an immutable snapshot.

        Raises:
            TaskManagementError: When the policy is disabled or has no
                allowed source path prefixes.
        """
        if self._org_policy_store is None:
            raise TaskManagementError(
                "POLICY_STORE_UNAVAILABLE",
                "Organization policy store is not available — "
                "cannot create auto_organize scheduled check",
            )

        try:
            policy: OrganizationAutomationPolicy = self._org_policy_store.load()
        except Exception as exc:
            raise TaskManagementError(
                "POLICY_LOAD_FAILED",
                f"Failed to load organization policy: {exc}",
            ) from exc

        if not policy.enabled:
            raise TaskManagementError(
                "POLICY_DISABLED",
                "Organization automation is currently disabled. "
                "Enable it in Settings before creating auto_organize scheduled checks.",
            )

        if not policy.allowed_source_path_prefixes:
            raise TaskManagementError(
                "NO_ALLOWED_PREFIXES",
                "No allowed source path prefixes configured. "
                "Configure at least one prefix in Settings.",
            )

        if not policy.destination_root:
            raise TaskManagementError(
                "NO_DESTINATION_ROOT",
                "No destination root configured. "
                "Set a destination root in Settings.",
            )

        return {
            "enabled": True,
            "allowed_source_path_prefixes": list(policy.allowed_source_path_prefixes),
            "destination_root": policy.destination_root,
            # allow_delete and allow_overwrite are always forced False
            # by the Pydantic validator — no need to snapshot them.
        }
