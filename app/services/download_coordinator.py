"""DownloadCoordinator -- coordinates the plan submission sequence.

Wires together DownloadSubmission (qB add), TaskScheduler (watch-task
lifecycle), and OrganizationAutomationPolicyStore (after-download resolution)
into a single orchestration step.

Flow per single submission:

1. Resolve the after-download follow-up mode (request -> settings -> fallback).
2. Validate that ``auto_organize`` is permitted by the current organization
   automation policy; capture an immutable authorization snapshot when it is.
3. Create a ``download_watch`` task in ``INITIALIZING`` status (crash-window
   reservation).
4. Submit the torrent to qBittorrent via ``DownloadSubmission``, passing the
   watch task ID as the correlation tag so the qB tag tracks back to the task.
5. On qB success: activate the watch task (``INITIALIZING`` -> ``QUEUED``)
   with the qB hash and resolved follow-up embedded in its payload.
6. On qB failure: fail-initialize the watch task so it is never picked up by
   the worker loop.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from app.domain.downloads import (
    BatchDownloadSubmissionResult,
    DownloadSubmissionRequest,
    DownloadSubmissionResult,
    ResolvedFollowUp,
    FOLLOW_UP_AUTO_ORGANIZE,
    FOLLOW_UP_NONE,
)
from app.domain.organization import OrganizationAutomationPolicy
from app.domain.runtime_tasks import RuntimeTask, TaskStatus, utc_now_iso
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.services.download_submission import DownloadSubmission
from app.services.organization_policy_store import OrganizationAutomationPolicyStore

logger = logging.getLogger(__name__)

# Task kind used for download-watch tasks created by the coordinator.
WATCH_TASK_KIND = "download_watch"


class DownloadCoordinator:
    """Orchestrates the plan submission sequence for one or more torrents."""

    def __init__(
        self,
        submission: DownloadSubmission,
        scheduler: TaskScheduler,
        policy_store: OrganizationAutomationPolicyStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        store: RuntimeTaskStore | None = None,
    ) -> None:
        """Initialise the coordinator.

        Args:
            submission: Reusable download-submission service (M-Team detail
                -> token -> qB add paused -> community subtitles).
            scheduler: External-facing seam over ``RuntimeTaskStore`` for
                watch-task lifecycle.
            policy_store: JSON store for the organization automation policy
                (``default_after_download``, ``enabled``, etc.).
            clock: Callable returning the current ``datetime``, used as the
                authoritative time source for all task mutations.
            id_factory: Callable returning a unique ``str``, used as the
                receipt ID generator.
            store: Optional ``RuntimeTaskStore`` for startup reconciliation
                of stale ``INITIALIZING`` tasks. Not needed when only using
                ``submit`` / ``submit_many``.
        """
        self._submission = submission
        self._scheduler = scheduler
        self._policy_store = policy_store
        self._clock = clock
        self._id_factory = id_factory
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        request: DownloadSubmissionRequest,
        source_session_id: str | None = None,
    ) -> DownloadSubmissionResult:
        """Execute the plan submission sequence for one torrent.

        Args:
            request: Internal transfer model carrying the torrent id,
                category, save path, media-type tag, and optional
                after-download preference.
            source_session_id: Optional conversation session that originated
                this request; forwarded to the watch-task metadata for
                event scoping.

        Returns:
            A ``DownloadSubmissionResult`` receipt with the watch task ID
            and resolved follow-up mode.
        """
        # 1 -- Resolve after-download follow-up mode
        resolved = self._resolve_after_download(request)

        # 2 -- Validate auto_organize against the current org policy
        if resolved.mode == FOLLOW_UP_AUTO_ORGANIZE:
            policy = self._policy_store.load()
            if not policy.enabled:
                return DownloadSubmissionResult(
                    receipt_id=self._id_factory(),
                    torrent_id=request.torrent_id,
                    status="failed",
                    watch_task_id="",
                    resolved_follow_up=resolved,
                    error="Organization automation is disabled; auto_organize is not permitted.",
                )
            # Capture an immutable snapshot of the policy that was in effect
            # at submission time so the organize worker can reference it
            # without re-reading a potentially-changed setting.
            resolved.authorization_snapshot = self._build_authorization_snapshot(policy)

        # 3 -- Reserve a watch task in INITIALIZING (crash-window guard)
        watch_payload = self._build_watch_payload(request, resolved)
        logger.info(
            "download_coordinator.submit: torrent_id=%s source_session_id=%r",
            request.torrent_id,
            source_session_id,
        )
        watch_task = self._scheduler.prepare(
            kind=WATCH_TASK_KIND,
            payload=watch_payload,
            source_session_id=source_session_id,
        )
        watch_task_id = watch_task.task_id

        # 4 -- Submit to qBittorrent; use the watch task ID as the
        #     correlation tag so the qB tag nasclaw-task-{id} links
        #     the torrent back to the task.
        correlation_tag = watch_task_id
        submission_result = self._submission.submit(
            request,
            correlation_tag=correlation_tag,
        )

        # 5 -- Handle qB success
        if submission_result.get("status") == "submitted_paused":
            qb_hash = submission_result.get("qb_hash")
            payload_patch: dict[str, Any] = {
                "qb_hash": qb_hash,
                "receipt": submission_result,
                "submitted_at": utc_now_iso(),
            }
            self._scheduler.activate(watch_task_id, payload_patch=payload_patch)
            return DownloadSubmissionResult(
                receipt_id=self._id_factory(),
                torrent_id=request.torrent_id,
                status="accepted",
                watch_task_id=watch_task_id,
                resolved_follow_up=resolved,
                submission_receipt=submission_result,
            )

        # 6 -- qB submission failed
        error_msg = str(
            submission_result.get("error", "Unknown submission error")
        )
        error_code = str(
            submission_result.get("error_code", "SUBMISSION_FAILED")
        )
        status = "duplicate" if error_code == "CONFLICT" else "failed"

        self._scheduler.fail_initialization(
            watch_task_id,
            error={"code": error_code, "message": error_msg},
        )
        return DownloadSubmissionResult(
            receipt_id=self._id_factory(),
            torrent_id=request.torrent_id,
            status=status,
            watch_task_id="",
            resolved_follow_up=resolved,
            error=error_msg,
        )

    def submit_many(
        self,
        requests: list[DownloadSubmissionRequest],
        source_session_id: str | None = None,
    ) -> BatchDownloadSubmissionResult:
        """Submit multiple torrents, each with its own watch task.

        Every request is processed independently: a failure for one
        torrent does not prevent the others from being submitted.

        Args:
            requests: One ``DownloadSubmissionRequest`` per torrent.
            source_session_id: Optional conversation session that
                originated these requests.

        Returns:
            An aggregated ``BatchDownloadSubmissionResult``.
        """
        items: list[DownloadSubmissionResult] = []
        for req in requests:
            result = self.submit(req, source_session_id=source_session_id)
            items.append(result)

        summary: dict[str, int] = {}
        for item in items:
            summary[item.status] = summary.get(item.status, 0) + 1

        return BatchDownloadSubmissionResult(items=items, summary=summary)

    def reconcile_stale_initializing(self) -> list[RuntimeTask]:
        """Fail any ``download_watch`` tasks still in ``INITIALIZING`` status.

        Call this once at application startup.  Tasks that were created but
        never activated (process crash before the qB submission result was
        processed) are transitioned to ``FAILED`` so the worker loop never
        picks them up.

        Returns the list of reconciled (now-failed) tasks.  Requires the
        ``store`` constructor argument; logs a warning and returns an empty
        list when the store was not provided.
        """
        if self._store is None:
            logger.warning(
                "No RuntimeTaskStore provided; "
                "skipping stale initializing reconciliation"
            )
            return []

        stale = self._store.list_tasks(
            kind=WATCH_TASK_KIND,
            status=TaskStatus.INITIALIZING.value,
        )
        if not stale:
            return []

        logger.info(
            "Reconciling %d stale %s tasks in INITIALIZING status",
            len(stale),
            WATCH_TASK_KIND,
        )
        reconciled: list[RuntimeTask] = []
        for task in stale:
            failed = self._scheduler.fail_initialization(
                task.task_id,
                error={
                    "code": "STARTUP_RECONCILE",
                    "message": "Stale initializing task reconciled at startup.",
                },
            )
            reconciled.append(failed)
            logger.info(
                "Stale task %s (%s) failed at startup",
                task.task_id,
                task.kind,
            )
        return reconciled

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_after_download(
        self,
        request: DownloadSubmissionRequest,
    ) -> ResolvedFollowUp:
        """Three-way precedence: request -> settings -> fallback.

        Per the current simplification, ``after_download`` is not exposed
        to the LLM as a tool parameter.  The field on
        ``DownloadSubmissionRequest`` is available for other callers (e.g.
        the ``/download`` endpoint) but the Agent path always sends
        ``None``, making the resolution fall through to the policy default.
        """
        policy = self._policy_store.load()

        # Precedence 1: explicitly provided in the request.
        if request.after_download is not None:
            return ResolvedFollowUp(
                mode=request.after_download,
                source="request",
                reason="Explicitly provided in the submission request.",
            )

        # Precedence 2: settings-level policy default.
        if policy.default_after_download:
            return ResolvedFollowUp(
                mode=policy.default_after_download,
                source="settings",
                reason="Resolved from the organization automation policy default.",
            )

        # Precedence 3: hard-coded system fallback.
        return ResolvedFollowUp(
            mode=FOLLOW_UP_NONE,
            source="fallback",
            reason="No explicit value or policy default; using system fallback.",
        )

    @staticmethod
    def _build_watch_payload(
        request: DownloadSubmissionRequest,
        resolved: ResolvedFollowUp,
    ) -> dict[str, Any]:
        """Build the initial payload for a ``download_watch`` task.

        Captures everything known *before* the qB submission so the
        watch-task handler has full context regardless of outcome.
        """
        payload: dict[str, Any] = {
            "torrent_id": request.torrent_id,
            "qb_category": request.qb_category or "",
            "save_path": request.save_path,
            "tag": request.tag,
            "resolved_follow_up": resolved.model_dump(),
        }
        return payload

    @staticmethod
    def _build_authorization_snapshot(
        policy: OrganizationAutomationPolicy,
    ) -> dict[str, Any]:
        """Capture an immutable snapshot of the current org automation policy.

        The snapshot is stored in the watch-task payload so the organize
        worker can authorise its operations against the policy that was in
        effect at submission time, even if the Settings change later.
        """
        return {
            "enabled": policy.enabled,
            "allowed_source_path_prefixes": list(policy.allowed_source_path_prefixes),
            "destination_root": policy.destination_root,
        }
