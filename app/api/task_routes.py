"""HTTP routes for organization authorization and safe task management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import (
    OrganizationAuthorizationPolicyResponse,
    TaskCancelResponse,
    TaskDetail,
    TaskDetailResponse,
    TaskEventAcknowledgeResponse,
    TaskEventListResponse,
    TaskEventSummary,
    TaskListResponse,
    TaskSummary,
)
from app.domain.organization import OrganizationAuthorizationPolicy
from app.domain.runtime_tasks import TaskEvent
from app.runtime.store import RuntimeTaskStore
from app.services.organization_policy_store import OrganizationAuthorizationPolicyStore
from app.services.task_management import (
    TaskListQuery,
    TaskManagementError,
    TaskManagementService,
    TaskView,
)

_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"


def _organization_policy_store() -> OrganizationAuthorizationPolicyStore:
    return OrganizationAuthorizationPolicyStore(_SETTINGS_DIR)


def _get_runtime_store(request: Request) -> RuntimeTaskStore:
    """Retrieve the shared RuntimeTaskStore from the FastAPI application state.

    The store is owned by the ``TaskRuntime`` instance created during the
    application lifespan.  This helper avoids passing the store through the
    router factory and keeps dependency wiring in ``main.py``.
    """
    runtime = getattr(request.app.state, "task_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Task runtime not available")
    return runtime.store


def _get_task_management(request: Request) -> TaskManagementService:
    service = getattr(request.app.state, "task_management_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Task management not available")
    return service


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _task_to_summary(task: TaskView) -> TaskSummary:
    """Convert a ``RuntimeTask`` (or compatible dict) to ``TaskSummary``.

    Secrets (payload, result, error) are intentionally excluded.
    """
    return TaskSummary(
        task_id=task.task_id,
        kind=task.kind,
        status=task.status,
        run_after=task.run_after,
        description=task.description,
        torrent_hash=task.torrent_hash,
        torrent_name=task.torrent_name,
        mode=task.mode,
        on_completed=task.on_completed,
        source_session_id=task.source_session_id,
        parent_task_id=task.parent_task_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


def _task_to_detail(task: TaskView, child_ids: list[str]) -> TaskDetail:
    """Convert a ``RuntimeTask`` to ``TaskDetail`` with relations.

    Secrets (payload, result, error) are intentionally excluded.
    """
    detail = TaskDetail(
        task_id=task.task_id,
        kind=task.kind,
        status=task.status,
        run_after=task.run_after,
        description=task.description,
        torrent_hash=task.torrent_hash,
        torrent_name=task.torrent_name,
        mode=task.mode,
        on_completed=task.on_completed,
        source_session_id=task.source_session_id,
        parent_task_id=task.parent_task_id,
        child_task_ids=child_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )
    return detail


def _event_to_summary(event: TaskEvent) -> TaskEventSummary:
    """Convert a ``TaskEvent`` to ``TaskEventSummary``."""
    return TaskEventSummary(
        event_id=event.event_id,
        task_id=event.task_id,
        source_session_id=event.source_session_id,
        kind=event.kind,
        severity=event.severity.value if hasattr(event.severity, "value") else str(event.severity),
        title=event.title,
        summary=event.summary,
        created_at=event.created_at,
        acknowledged_at=event.acknowledged_at,
    )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def build_task_router() -> APIRouter:
    """Build a router exposing organization automation policy and runtime task endpoints."""
    router = APIRouter(tags=["organization", "tasks"])

    # ======================================================================
    # Organization Automation Policy (existing)
    # ======================================================================

    @router.get(
        "/settings/organization-authorization",
        response_model=OrganizationAuthorizationPolicyResponse,
    )
    def get_organization_authorization_policy() -> OrganizationAuthorizationPolicyResponse:
        """Return the user-configured organization automation policy.

        This policy controls whether and how media files are automatically
        organized after torrent downloads complete.
        """
        policy = _organization_policy_store().load()
        return OrganizationAuthorizationPolicyResponse.model_validate(policy.model_dump())

    @router.put(
        "/settings/organization-authorization",
        response_model=OrganizationAuthorizationPolicyResponse,
    )
    def update_organization_authorization_policy(
        body: OrganizationAuthorizationPolicy,
    ) -> OrganizationAuthorizationPolicyResponse:
        """Persist the user-configured organization automation policy.

        Accepts the policy fields; ``allow_delete`` and ``allow_overwrite``
        are always forced to ``False`` for safety regardless of the submitted
        value.
        """
        policy = _organization_policy_store().save(body)
        return OrganizationAuthorizationPolicyResponse.model_validate(policy.model_dump())

    # ======================================================================
    # Runtime Task endpoints (Task 10)
    # ======================================================================

    @router.get("/tasks", response_model=TaskListResponse)
    def list_tasks(
        request: Request,
        source_session_id: str | None = Query(None, description="Filter by originating conversation session"),
        status: str | None = Query(None, description="Filter by status (e.g. queued, running, succeeded)"),
        kind: str | None = Query(None, description="Filter by task kind (e.g. download_watch, organize_download)"),
        limit: int = Query(50, ge=1, le=200, description="Max tasks to return"),
    ) -> TaskListResponse:
        """List runtime tasks with optional filters.

        Returns compact task summaries without payload, result, or error
        details to avoid leaking secrets or tokenized URLs.
        """
        tasks = _get_task_management(request).list_tasks(TaskListQuery(
            source_session_id=source_session_id,
            status=status,
            kind=kind,
            limit=limit,
        ))
        return TaskListResponse(
            tasks=[_task_to_summary(t) for t in tasks],
            total_count=len(tasks),
        )

    @router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
    def get_task_detail(
        request: Request,
        task_id: str,
    ) -> TaskDetailResponse:
        """Return detailed information for one runtime task.

        Includes parent and child task IDs plus the latest WorkerRun summary.
        Payload, result, and error details are excluded to avoid leaking
        secrets or tokenized URLs.
        """
        try:
            service = _get_task_management(request)
            task = service.get_task(task_id)
        except TaskManagementError:
            raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")

        # Find child tasks (tasks whose parent_task_id equals this task_id).
        children = service.list_tasks(TaskListQuery(limit=200))
        child_ids = [c.task_id for c in children if c.parent_task_id == task_id]
        detail = _task_to_detail(task, child_ids)
        return TaskDetailResponse(task=detail)

    @router.post("/tasks/{task_id}/cancel", response_model=TaskCancelResponse)
    def cancel_task(
        request: Request,
        task_id: str,
    ) -> TaskCancelResponse:
        """Cancel a non-terminal runtime task.

        Idempotent: cancelling an already-terminal task returns the existing
        state without changes.
        """
        service = _get_task_management(request)
        try:
            previous = service.get_task(task_id)
            updated = service.cancel_task(task_id)
        except TaskManagementError as exc:
            status_code = 404 if exc.code == "TASK_NOT_FOUND" else 409
            raise HTTPException(status_code=status_code, detail=exc.message)
        return TaskCancelResponse(
            task_id=task_id,
            status=updated.status,
            previous_status=previous.status,
        )

    @router.get("/task-events", response_model=TaskEventListResponse)
    def list_task_events(
        request: Request,
        source_session_id: str | None = Query(None, description="Filter by originating conversation session"),
        acknowledged: bool | None = Query(None, description="Filter by acknowledged state (true/false)"),
        after: str | None = Query(None, description="ISO-8601 cursor; return only older events"),
        limit: int = Query(50, ge=1, le=200, description="Max events to return"),
    ) -> TaskEventListResponse:
        """List task events with optional filters, newest first.

        Events are user-visible notifications emitted by completed task
        handlers.
        """
        store = _get_runtime_store(request)
        filters: dict[str, Any] = {}
        if source_session_id is not None:
            filters["source_session_id"] = source_session_id
        if acknowledged is not None:
            filters["acknowledged"] = acknowledged

        events = store.list_events(after=after, limit=limit, filters=filters)
        return TaskEventListResponse(
            events=[_event_to_summary(e) for e in events],
            total_count=len(events),
        )

    @router.post("/task-events/{event_id}/acknowledge", response_model=TaskEventAcknowledgeResponse)
    def acknowledge_task_event(
        request: Request,
        event_id: str,
    ) -> TaskEventAcknowledgeResponse:
        """Acknowledge a task event (idempotent).

        Marks an event as seen/dismissed by setting ``acknowledged_at``.
        Safe to call multiple times.
        """
        store = _get_runtime_store(request)
        now = _utc_now()
        try:
            updated = store.acknowledge_event(event_id, now=now)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"TaskEvent {event_id!r} not found")

        return TaskEventAcknowledgeResponse(
            event_id=event_id,
            status="acknowledged" if updated.acknowledged_at else "not_acknowledged",
        )

    return router


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

from datetime import datetime, timezone


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)
