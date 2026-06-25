"""Deep module for download submission and durable download monitoring."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Callable, Iterable

from app.adapters.qbittorrent import QBittorrentAdapter
from app.domain.downloads import (
    BatchDownloadSubmissionResult,
    DownloadCompletionAction,
    DownloadMonitorReceipt,
    DownloadMonitorRequest,
    DownloadMonitorSpec,
    DownloadMonitorUpdate,
    DownloadSubmissionRequest,
    DownloadSubmissionResult,
    build_download_monitor_payload,
    download_monitor_exclusive_key,
    is_future_time,
    normalize_to_utc,
    parse_download_monitor,
)
from app.domain.organization import (
    OrganizationAuthorizationPolicy,
    OrganizationAuthorizationSnapshot,
)
from app.domain.path_mapping import translate_path
from app.domain.runtime_tasks import RuntimeTask, TaskStatus
from app.runtime.scheduler import TaskScheduler
from app.services.download_submission import DownloadSubmission
from app.services.organization_policy_store import OrganizationAuthorizationPolicyStore

logger = logging.getLogger(__name__)

WATCH_TASK_KIND = "download_watch"
DOWNLOAD_MONITOR_DEDUPE_PREFIX = "download-monitor-approval"
DOWNLOAD_SUBMISSION_DEDUPE_PREFIX = "download-submission-approval"


class DownloadAutomationError(ValueError):
    """Download-automation failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DownloadAutomation:
    """The only application service that creates or mutates download tasks."""

    def __init__(
        self,
        submission: DownloadSubmission,
        qb_adapter: QBittorrentAdapter,
        scheduler: TaskScheduler,
        policy_store: OrganizationAuthorizationPolicyStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
        mcp_allowed_dirs: Iterable[str] = (),
        path_mapping: dict[str, str] | None = None,
    ) -> None:
        self._submission = submission
        self._qb = qb_adapter
        self._scheduler = scheduler
        self._policy_store = policy_store
        self._clock = clock
        self._id_factory = id_factory
        self._mcp_allowed_dirs = tuple(
            path.strip() for path in mcp_allowed_dirs if str(path).strip()
        )
        self._path_mapping = dict(path_mapping or {})

    def submit_downloads(
        self,
        requests: list[DownloadSubmissionRequest],
        completion_action: DownloadCompletionAction,
        source_session_id: str | None,
        idempotency_key: str = "",
    ) -> BatchDownloadSubmissionResult:
        """Submit paused qB downloads and optionally activate durable monitors."""

        items = [
            self._submit_one(
                request,
                completion_action=completion_action,
                source_session_id=source_session_id,
                idempotency_key=(f"{idempotency_key}:{index}" if idempotency_key else ""),
            )
            for index, request in enumerate(requests)
        ]
        summary: dict[str, int] = {}
        for item in items:
            summary[item.status] = summary.get(item.status, 0) + 1
        return BatchDownloadSubmissionResult(items=items, summary=summary)

    def create_monitor(
        self,
        request: DownloadMonitorRequest,
        source_session_id: str | None,
        idempotency_key: str,
    ) -> DownloadMonitorReceipt:
        """Create one canonical active monitor for an existing qB torrent."""

        torrent_hash = request.torrent_hash.strip()
        if not torrent_hash:
            raise DownloadAutomationError(
                "MISSING_TORRENT_HASH", "torrent_hash is required"
            )
        torrent = self._get_torrent(torrent_hash)
        torrent_name = str(torrent.get("name") or torrent_hash)
        source_path = self._torrent_source_path(torrent)
        start_at = self._normalize_create_time(request.start_at)
        snapshot = (
            self._capture_organization_snapshot(source_path)
            if request.on_completed == "organize"
            else None
        )
        monitor = DownloadMonitorSpec(
            mode=request.mode,
            on_completed=request.on_completed,
        )
        payload = build_download_monitor_payload(
            torrent_hash=torrent_hash,
            torrent_name=torrent_name,
            save_path=source_path,
            monitor=monitor,
            authorization_snapshot=(snapshot.model_dump() if snapshot else None),
        )
        dedupe_key = (
            f"{DOWNLOAD_MONITOR_DEDUPE_PREFIX}:{source_session_id or ''}:{idempotency_key}"
        )
        try:
            task = self._scheduler.enqueue(
                kind=WATCH_TASK_KIND,
                payload=payload,
                source_session_id=source_session_id,
                dedupe_key=dedupe_key,
                exclusive_key=self._exclusive_key(torrent_hash),
                run_after=start_at,
            )
        except ValueError as exc:
            raise DownloadAutomationError("MONITOR_CONFLICT", str(exc)) from exc
        return self._monitor_receipt(task)

    def update_monitor(
        self,
        request: DownloadMonitorUpdate,
    ) -> DownloadMonitorReceipt:
        """Atomically update time, mode, and completion action."""

        task = self._scheduler.get(request.task_id)
        if task is None:
            raise DownloadAutomationError(
                "TASK_NOT_FOUND", f"Task {request.task_id!r} was not found"
            )
        if task.kind != WATCH_TASK_KIND:
            raise DownloadAutomationError(
                "WRONG_TASK_KIND", "Only download_watch tasks can be updated"
            )
        start_at: str | None = None
        if "start_at" in request.model_fields_set:
            start_at = self._normalize_update_time(request.start_at or "")

        current = parse_download_monitor(task.payload)
        target_action = request.on_completed or current.on_completed
        if target_action == "none":
            raise DownloadAutomationError(
                "LEGACY_MONITOR_IMMUTABLE",
                "Legacy silent-completion monitors cannot be updated; create a new monitor after it terminates",
            )

        snapshot: dict | None = None
        if request.on_completed == "organize":
            source_path = str(task.payload.get("save_path") or "").strip()
            if not source_path:
                torrent = self._get_torrent(str(task.payload.get("qb_hash") or ""))
                source_path = self._torrent_source_path(torrent)
            snapshot = self._capture_organization_snapshot(source_path).model_dump()

        try:
            updated = self._scheduler.update_download_monitor(
                request.task_id,
                run_after=start_at,
                mode=request.mode,
                on_completed=request.on_completed,
                authorization_snapshot=snapshot,
            )
        except ValueError as exc:
            raise DownloadAutomationError("UPDATE_REJECTED", str(exc)) from exc
        return self._monitor_receipt(updated)

    def _submit_one(
        self,
        request: DownloadSubmissionRequest,
        *,
        completion_action: DownloadCompletionAction,
        source_session_id: str | None,
        idempotency_key: str,
    ) -> DownloadSubmissionResult:
        receipt_id = self._id_factory()
        if completion_action == "none":
            submission = self._submission.submit(request)
            return self._submission_result(
                receipt_id, request, submission, watch_task_id=None
            )

        source_path = self._translate_path(
            self._submission.resolve_save_path(request)
        )
        snapshot = (
            self._capture_organization_snapshot(source_path)
            if completion_action == "organize"
            else None
        )
        monitor = DownloadMonitorSpec(
            mode="until_complete",
            on_completed=completion_action,
        )
        reservation_nonce = self._id_factory()
        payload = build_download_monitor_payload(
            torrent_hash="",
            torrent_name=request.torrent_id,
            save_path=source_path,
            monitor=monitor,
            authorization_snapshot=(snapshot.model_dump() if snapshot else None),
        )
        payload.update(
            {
                "torrent_id": request.torrent_id,
                "reservation_nonce": reservation_nonce,
            }
        )
        dedupe_key = (
            f"{DOWNLOAD_SUBMISSION_DEDUPE_PREFIX}:{source_session_id or ''}:{idempotency_key}"
            if idempotency_key
            else None
        )
        task = self._scheduler.prepare(
            kind=WATCH_TASK_KIND,
            payload=payload,
            source_session_id=source_session_id,
            dedupe_key=dedupe_key,
        )
        if task.payload.get("reservation_nonce") != reservation_nonce:
            return self._replayed_submission_result(receipt_id, request, task)

        submission = self._submission.submit(request, correlation_tag=task.task_id)
        if submission.get("status") not in ("submitted", "submitted_paused"):
            error_msg = str(submission.get("error") or "Unknown submission error")
            error_code = str(submission.get("error_code") or "SUBMISSION_FAILED")
            self._scheduler.fail_initialization(
                task.task_id,
                error={"code": error_code, "message": error_msg},
            )
            return DownloadSubmissionResult(
                receipt_id=receipt_id,
                torrent_id=request.torrent_id,
                status="duplicate" if error_code == "CONFLICT" else "failed",
                error=error_msg,
            )

        qb_hash = str(submission.get("qb_hash") or "").strip()
        try:
            payload_patch = {
                "torrent_name": str(
                    submission.get("resource_title") or request.torrent_id
                ),
                "receipt": submission,
                "reservation_nonce": None,
            }
            if qb_hash:
                payload_patch["qb_hash"] = qb_hash
            self._scheduler.activate(
                task.task_id,
                payload_patch=payload_patch,
                exclusive_key=(self._exclusive_key(qb_hash) if qb_hash else None),
            )
        except ValueError as exc:
            # qB side effect already occurred. Preserve the reservation as a
            # failed audit row and report the conflict without resubmitting.
            self._scheduler.fail_initialization(
                task.task_id,
                error={"code": "MONITOR_CONFLICT", "message": str(exc)},
            )
            return DownloadSubmissionResult(
                receipt_id=receipt_id,
                torrent_id=request.torrent_id,
                status="duplicate",
                error=f"Download submitted, but monitor activation failed: {exc}",
                submission_receipt=submission,
            )
        return DownloadSubmissionResult(
            receipt_id=receipt_id,
            torrent_id=request.torrent_id,
            status="accepted",
            watch_task_id=task.task_id,
            submission_receipt=submission,
        )

    def _replayed_submission_result(
        self,
        receipt_id: str,
        request: DownloadSubmissionRequest,
        task: RuntimeTask,
    ) -> DownloadSubmissionResult:
        if task.status in {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.WAITING,
            TaskStatus.SUCCEEDED,
        }:
            receipt = task.payload.get("receipt")
            return DownloadSubmissionResult(
                receipt_id=receipt_id,
                torrent_id=request.torrent_id,
                status="accepted",
                watch_task_id=task.task_id,
                submission_receipt=(receipt if isinstance(receipt, dict) else None),
            )
        return DownloadSubmissionResult(
            receipt_id=receipt_id,
            torrent_id=request.torrent_id,
            status="failed",
            watch_task_id=task.task_id,
            error=(
                "A prior approval attempt is still initializing; qB submission was not repeated"
                if task.status == TaskStatus.INITIALIZING
                else "A prior approval attempt already failed or was cancelled"
            ),
        )

    @staticmethod
    def _submission_result(
        receipt_id: str,
        request: DownloadSubmissionRequest,
        submission: dict,
        *,
        watch_task_id: str | None,
    ) -> DownloadSubmissionResult:
        if submission.get("status") in ("submitted", "submitted_paused"):
            return DownloadSubmissionResult(
                receipt_id=receipt_id,
                torrent_id=request.torrent_id,
                status="accepted",
                watch_task_id=watch_task_id,
                submission_receipt=submission,
            )
        error_code = str(submission.get("error_code") or "SUBMISSION_FAILED")
        return DownloadSubmissionResult(
            receipt_id=receipt_id,
            torrent_id=request.torrent_id,
            status="duplicate" if error_code == "CONFLICT" else "failed",
            error=str(submission.get("error") or "Unknown submission error"),
        )

    def _get_torrent(self, torrent_hash: str) -> dict:
        try:
            torrent = self._qb.get_torrent(torrent_hash)
        except Exception as exc:
            raise DownloadAutomationError(
                "QB_UNAVAILABLE", f"Cannot reach qBittorrent: {exc}"
            ) from exc
        if torrent is None:
            raise DownloadAutomationError(
                "TORRENT_NOT_FOUND",
                f"Torrent with hash {torrent_hash!r} was not found",
            )
        return torrent

    def _normalize_create_time(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._normalize_future_time(value, field="start_at")

    def _normalize_update_time(self, value: str) -> str:
        return self._normalize_future_time(value, field="start_at")

    def _normalize_future_time(self, value: str, *, field: str) -> str:
        try:
            normalized = normalize_to_utc(value)
        except ValueError as exc:
            raise DownloadAutomationError("INVALID_START_AT", str(exc)) from exc
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            now = now.replace(tzinfo=timezone.utc)
        if not is_future_time(normalized, now=now):
            raise DownloadAutomationError(
                "START_AT_NOT_FUTURE", f"{field} must be in the future"
            )
        return normalized

    def _capture_organization_snapshot(
        self,
        source_path: str,
    ) -> OrganizationAuthorizationSnapshot:
        try:
            policy = self._policy_store.load()
        except Exception as exc:
            raise DownloadAutomationError(
                "ORGANIZATION_POLICY_UNAVAILABLE",
                "Background organization authorization could not be read",
            ) from exc
        self._validate_policy(policy, source_path)
        return OrganizationAuthorizationSnapshot(
            allowed_source_path_prefixes=list(policy.allowed_source_path_prefixes),
            destination_root=policy.destination_root,
        )

    def _validate_policy(
        self,
        policy: OrganizationAuthorizationPolicy,
        source_path: str,
    ) -> None:
        if not policy.background_organization_allowed:
            raise DownloadAutomationError(
                "ORGANIZATION_NOT_AUTHORIZED",
                "Background organization is not authorized in Settings",
            )
        if not source_path or not self._path_in_prefixes(
            source_path, policy.allowed_source_path_prefixes
        ):
            raise DownloadAutomationError(
                "SOURCE_PATH_NOT_AUTHORIZED",
                f"Source path is outside the authorized prefixes: {source_path or '<empty>'}",
            )
        if not policy.destination_root:
            raise DownloadAutomationError(
                "DESTINATION_NOT_AUTHORIZED",
                "Organization destination_root is empty",
            )
        if not self._mcp_allowed_dirs or not self._path_in_prefixes(
            policy.destination_root, list(self._mcp_allowed_dirs)
        ):
            raise DownloadAutomationError(
                "DESTINATION_OUTSIDE_MCP_SCOPE",
                "Organization destination_root is outside MCP filesystem allowed directories",
            )

    def _torrent_source_path(self, torrent: dict) -> str:
        source = str(
            torrent.get("content_path") or torrent.get("save_path") or ""
        ).strip()
        return self._translate_path(source)

    def _translate_path(self, path: str) -> str:
        return translate_path(path, self._path_mapping)

    @staticmethod
    def _path_in_prefixes(path: str, prefixes: list[str]) -> bool:
        if not path or not os.path.isabs(path):
            return False
        candidate = os.path.normpath(path)
        for prefix in prefixes:
            if not prefix or not os.path.isabs(prefix):
                continue
            clean = os.path.normpath(prefix)
            try:
                if os.path.commonpath((candidate, clean)) == clean:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _exclusive_key(torrent_hash: str) -> str:
        return download_monitor_exclusive_key(torrent_hash)

    @staticmethod
    def _monitor_receipt(task: RuntimeTask) -> DownloadMonitorReceipt:
        monitor = parse_download_monitor(task.payload)
        if monitor.on_completed == "none":
            raise DownloadAutomationError(
                "LEGACY_MONITOR",
                "Legacy silent-completion task has no canonical receipt",
            )
        return DownloadMonitorReceipt(
            task_id=task.task_id,
            torrent_hash=str(task.payload.get("qb_hash") or ""),
            torrent_name=str(task.payload.get("torrent_name") or ""),
            start_at=task.run_after,
            mode=monitor.mode,
            on_completed=monitor.on_completed,
            status=task.status.value,
        )
