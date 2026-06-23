"""Handler that runs the OrganizeWorkerAgent for post-download file organization.

The ``OrganizeDownloadHandler`` is registered for the ``organize_download``
task kind.  It builds a handoff from the task payload, invokes the worker
agent in a thread executor, and publishes ``TaskEvents`` based on the
structured result.

This handler does **not** poll — it runs once per invocation and returns
a terminal outcome (``Complete`` or ``Fail``).  If the organization fails
with a retryable error the worker loop's standard retry logic applies.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.agent.organize_worker import OrganizeWorkerAgent, OrganizeWorkerResult
from app.domain.runtime_tasks import (
    Complete,
    Fail,
    RuntimeTask,
    TaskEventSeverity,
    TaskOutcome,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_JOURNAL_PATH = "memory/runtime/organize-journal.json"
"""Default filesystem path for the organisation operation journal."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class OrganizeDownloadConfig:
    """Configuration for the :class:`OrganizeDownloadHandler`.

    Attributes:
        destination_root: Root directory for organized media
            (e.g. ``/影视``).  When empty, the handler reads it from the
            task payload ``content_path`` parent chain or the
            ``authorization_snapshot``.
        worker_max_steps: Maximum tool-calling steps for the worker agent.
        journal_path: Filesystem path for the operation journal used for
            idempotent retry.
        enabled: When ``False``, the handler returns a ``Complete`` outcome
            without running the worker.  Useful for temporarily disabling
            automation.
    """

    destination_root: str = ""
    worker_max_steps: int = 15
    journal_path: str = DEFAULT_JOURNAL_PATH
    enabled: bool = True


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class OrganizeDownloadHandler:
    """Run the ``OrganizeWorkerAgent`` for a completed download.

    Constructed with infrastructure dependencies shared across invocations.
    The ``__call__`` method matches the ``Handler`` protocol from the runtime
    registry.
    """

    def __init__(
        self,
        config: OrganizeDownloadConfig,
        scheduler: TaskScheduler,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        worker_factory: Callable[[int], OrganizeWorkerAgent] | None = None,
        organization_policy_store: Any | None = None,
    ) -> None:
        """Initialise the handler.

        Args:
            config: Configuration including destination_root and worker
                settings.
            scheduler: The ``TaskScheduler`` for spawning child tasks.
            store: The ``RuntimeTaskStore`` for state transitions.
            clock: Callable returning the current ``datetime``.
            worker_factory: Callable that accepts ``max_steps`` and returns
                an ``OrganizeWorkerAgent``.  Defaults to ``OrganizeWorkerAgent``
                constructor.  Override in tests to inject a mock worker.
            organization_policy_store: Optional store for reading the current
                organisation automation policy at execution time.  When
                provided, the handler re-validates the task's authorization
                snapshot against the current policy before running the worker.
        """
        self._config = config
        self._scheduler = scheduler
        self._store = store
        self._clock = clock
        self._worker_factory = worker_factory or (
            lambda ms: OrganizeWorkerAgent(max_steps=ms)
        )
        self._org_policy_store = organization_policy_store

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    async def __call__(
        self,
        task: RuntimeTask,
        store: RuntimeTaskStore,
        scheduler: TaskScheduler,
    ) -> TaskOutcome:
        """Execute one organisation run for *task*.

        Args:
            task: The claimed ``RuntimeTask`` with a payload containing
                ``content_path`` and optionally ``destination_root``,
                ``save_path``, ``torrent_name``, and ``qb_hash``.
            store: The concrete ``RuntimeTaskStore`` (forwarded by the
                worker loop).
            scheduler: The ``TaskScheduler`` (forwarded by the worker
                loop — not used by this handler).

        Returns:
            A ``TaskOutcome``:

            - ``Complete`` — organisation finished successfully.
            - ``Fail`` — organisation failed (retryable or terminal).
        """
        if not self._config.enabled:
            logger.info("Organize handler is disabled — skipping task %s", task.task_id)
            return Complete(
                result={"skipped": True, "reason": "handler_disabled"},
                events=[],
            )

        payload = task.payload or {}
        content_path = (payload.get("content_path") or "").strip()
        save_path = (payload.get("save_path") or "").strip()
        torrent_name = (payload.get("torrent_name") or "").strip()
        qb_hash = (payload.get("qb_hash") or "").strip()

        if not content_path:
            return Fail(
                code="MISSING_CONTENT_PATH",
                message="Task payload is missing content_path",
                retryable=False,
                details={"payload_keys": list(payload.keys())},
            )

        # Resolve destination_root: config > payload > default.
        destination_root = self._config.destination_root
        if not destination_root:
            destination_root = payload.get("destination_root", "")
        if not destination_root:
            destination_root = self._resolve_destination_root(content_path, save_path)

        if not destination_root:
            return Fail(
                code="MISSING_DESTINATION_ROOT",
                message=(
                    "No destination_root configured and could not be derived "
                    "from content_path or save_path"
                ),
                retryable=False,
                details={"content_path": content_path, "save_path": save_path},
            )

        logger.info(
            "Organizing torrent %s (%s) content_path=%s dest_root=%s",
            qb_hash or "?",
            torrent_name or "?",
            content_path,
            destination_root,
        )

        # ── Policy revalidation (SS9.2) ──
        # Before running any MCP/LLM calls, verify the authorization snapshot
        # against the current policy.  This is especially important for
        # future tasks that may have been created days ago.
        auth_snapshot = payload.get("authorization_snapshot") or {}
        if isinstance(auth_snapshot, dict) and auth_snapshot.get("enabled"):
            policy_error = self._validate_against_current_policy(
                content_path=content_path,
                destination_root=destination_root,
                auth_snapshot=auth_snapshot,
            )
            if policy_error is not None:
                return policy_error

        # Run the worker agent in the default thread executor.
        loop = asyncio.get_event_loop()
        try:
            worker = self._worker_factory(self._config.worker_max_steps)
            result: OrganizeWorkerResult = await loop.run_in_executor(
                None,
                lambda: worker.run(
                    source_path=content_path,
                    destination_root=destination_root,
                ),
            )
        except Exception as exc:
            logger.exception(
                "OrganizeWorkerAgent raised exception for task %s", task.task_id
            )
            return Fail(
                code="WORKER_EXCEPTION",
                message=f"OrganizeWorkerAgent raised: {exc}",
                retryable=True,
                details={"error": str(exc)},
            )

        if result.status != "success":
            logger.warning(
                "OrganizeWorkerAgent failed for torrent %s: status=%s moved=%d issues=%s",
                torrent_name or qb_hash or "?",
                result.status,
                result.moved_count,
                result.issues,
            )

        return self._outcome_from_result(result, torrent_name, qb_hash)

    # ------------------------------------------------------------------
    # Policy revalidation
    # ------------------------------------------------------------------

    def _validate_against_current_policy(
        self,
        content_path: str,
        destination_root: str,
        auth_snapshot: dict[str, Any],
    ) -> TaskOutcome | None:
        """Re-validate the authorization snapshot against the current policy.

        Returns ``None`` when the task is still authorized.  Returns a
        ``Fail`` outcome when the current policy has been disabled or
        narrowed in a way that should block this organization run.

        Rules:
        - Current policy must be enabled.
        - ``content_path`` must be under a prefix allowed by **both** the
          snapshot and the current policy (intersection — current narrowing
          wins).
        - ``destination_root`` must match the snapshot.  Current policy
          expansion does **not** grant extra permissions.
        """
        if self._org_policy_store is None:
            # No policy store configured — allow execution (backward compat).
            return None

        try:
            from app.domain.organization import OrganizationAutomationPolicy

            current: OrganizationAutomationPolicy = self._org_policy_store.load()
        except Exception as exc:
            logger.warning(
                "Failed to load current organization policy: %s — allowing execution",
                exc,
            )
            return None

        # 1. Policy must be enabled.
        if not current.enabled:
            return Fail(
                code="ORGANIZE_POLICY_DISABLED",
                message=(
                    "Organization automation has been disabled since this "
                    "task was created.  Enable it in Settings and retry, "
                    "or cancel the task."
                ),
                retryable=False,
                details={
                    "content_path": content_path,
                    "destination_root": destination_root,
                },
            )

        # 2. Source path must be under a prefix allowed by BOTH snapshot
        #    and current policy.
        snapshot_prefixes: list[str] = auth_snapshot.get(
            "allowed_source_path_prefixes", []
        ) or []
        current_prefixes: list[str] = current.allowed_source_path_prefixes or []

        # Intersection: only prefixes present in both sets.
        effective_prefixes = [
            p for p in snapshot_prefixes
            if p in current_prefixes
        ]

        if not effective_prefixes:
            return Fail(
                code="ORGANIZE_SOURCE_SCOPE_REVOKED",
                message=(
                    "The allowed source paths for organization have been "
                    "narrowed or removed since this task was created.  "
                    "The task can no longer access its source directory."
                ),
                retryable=False,
                details={
                    "content_path": content_path,
                    "snapshot_prefixes": snapshot_prefixes,
                    "current_prefixes": current_prefixes,
                },
            )

        source_allowed = any(
            content_path.startswith(prefix) for prefix in effective_prefixes
        )
        if not source_allowed:
            return Fail(
                code="ORGANIZE_SOURCE_NOT_IN_SCOPE",
                message=(
                    f"The source path {content_path!r} is no longer within "
                    f"the allowed organization prefixes."
                ),
                retryable=False,
                details={
                    "content_path": content_path,
                    "effective_prefixes": effective_prefixes,
                },
            )

        # 3. Destination root must match snapshot.
        snapshot_dest = auth_snapshot.get("destination_root", "")
        if snapshot_dest and destination_root != snapshot_dest:
            return Fail(
                code="ORGANIZE_DESTINATION_MISMATCH",
                message=(
                    f"The destination root has changed since this task was "
                    f"created (snapshot={snapshot_dest!r}, "
                    f"current={destination_root!r})."
                ),
                retryable=False,
                details={
                    "snapshot_destination": snapshot_dest,
                    "current_destination": destination_root,
                },
            )

        return None

    # ------------------------------------------------------------------
    # Outcome builder
    # ------------------------------------------------------------------

    def _outcome_from_result(
        self,
        result: OrganizeWorkerResult,
        torrent_name: str,
        qb_hash: str,
    ) -> TaskOutcome:
        """Build a ``Complete`` or ``Fail`` outcome from the worker result."""
        result_data = {
            "qb_hash": qb_hash,
            "torrent_name": torrent_name,
            "status": result.status,
            "moved_count": result.moved_count,
            "destination": result.destination,
            "summary": result.summary,
            "issues": result.issues,
            "tool_calls": result.tool_calls,
        }

        if result.status == "success":
            title = "下载整理完成"
            summary_parts = [f"文件已整理到 {result.destination or '目标目录'}"]
            if result.moved_count > 0:
                summary_parts.append(f"移动了 {result.moved_count} 个文件")
            if torrent_name:
                summary_parts.insert(0, f"种子 {torrent_name}")
            if result.issues:
                summary_parts.append(f"({len(result.issues)} 个警告)")

            return Complete(
                result=result_data,
                events=[
                    {
                        "kind": "organize_completed",
                        "severity": TaskEventSeverity.SUCCESS,
                        "title": title,
                        "summary": " — ".join(summary_parts),
                        "payload": {
                            "qb_hash": qb_hash,
                            "torrent_name": torrent_name,
                            "moved_count": result.moved_count,
                            "destination": result.destination,
                            "issues": result.issues,
                        },
                    },
                ],
            )

        if result.status == "failed":
            return Fail(
                code="ORGANIZE_FAILED",
                message=result.summary[:500] if result.summary else "Organization failed",
                retryable=True,
                details=result_data,
            )

        # status == "error"
        return Fail(
            code="ORGANIZE_ERROR",
            message=result.summary[:500] if result.summary else "Organization error",
            retryable=True,
            details=result_data,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_destination_root(
        content_path: str,
        save_path: str,
    ) -> str:
        """Best-effort derivation of the destination root.

        Walks up from ``content_path`` looking for known category directory
        names (电影, 剧集, 动漫, 综艺, 纪录片).  Falls back to the parent
        of ``save_path`` when nothing is found.
        """
        path = Path(content_path)
        known_categories = {"电影", "剧集", "动漫", "综艺", "纪录片", "未整理", "其他"}
        for parent in path.parents:
            if parent.name in known_categories:
                return str(parent.parent)
        if save_path:
            return str(Path(save_path).resolve())
        return str(path.parent.resolve())
