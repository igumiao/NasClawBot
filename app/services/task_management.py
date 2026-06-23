"""Safe task query and cancellation service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.downloads import parse_download_monitor
from app.domain.runtime_tasks import RuntimeTask
from app.runtime.scheduler import TaskScheduler


class TaskView(BaseModel):
    """Safe task projection; never exposes payload, authorization, or leases."""

    task_id: str
    kind: str
    status: str
    run_after: str | None = None
    description: str = ""
    torrent_hash: str | None = None
    torrent_name: str | None = None
    mode: str | None = None
    on_completed: str | None = None
    source_session_id: str | None = None
    parent_task_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_runtime_task(cls, task: RuntimeTask) -> "TaskView":
        payload = task.payload or {}
        torrent_hash: str | None = None
        torrent_name: str | None = None
        mode: str | None = None
        on_completed: str | None = None
        if task.kind == "download_watch":
            torrent_hash = str(payload.get("qb_hash") or "") or None
            torrent_name = str(payload.get("torrent_name") or "") or None
            try:
                monitor = parse_download_monitor(payload)
                mode = monitor.mode
                on_completed = monitor.on_completed
            except (TypeError, ValueError):
                pass
        return cls(
            task_id=task.task_id,
            kind=task.kind,
            status=task.status.value,
            run_after=task.run_after,
            description=cls._build_description(task.kind, payload, mode),
            torrent_hash=torrent_hash,
            torrent_name=torrent_name,
            mode=mode,
            on_completed=on_completed,
            source_session_id=task.source_session_id,
            parent_task_id=task.parent_task_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )

    @staticmethod
    def _build_description(
        kind: str, payload: dict[str, Any], mode: str | None
    ) -> str:
        name = str(payload.get("torrent_name") or payload.get("qb_hash") or "?")
        if kind == "download_watch":
            return f"{'一次检查' if mode == 'once' else '下载监控'}: {name}"
        if kind == "organize_download":
            return f"整理: {name}"
        return kind


class TaskListQuery(BaseModel):
    status: str | None = None
    kind: str | None = None
    source_session_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class TaskManagementError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TaskManagementService:
    """Read/cancel boundary over the generic scheduler."""

    def __init__(self, scheduler: TaskScheduler) -> None:
        self._scheduler = scheduler

    def list_tasks(self, query: TaskListQuery | None = None) -> list[TaskView]:
        q = query or TaskListQuery()
        tasks = self._scheduler.list_tasks(
            status=q.status,
            kind=q.kind,
            source_session_id=q.source_session_id,
            limit=q.limit,
        )
        return [TaskView.from_runtime_task(task) for task in tasks]

    def get_task(self, task_id: str) -> TaskView:
        task = self._scheduler.get(task_id)
        if task is None:
            raise TaskManagementError("TASK_NOT_FOUND", f"Task {task_id!r} not found")
        return TaskView.from_runtime_task(task)

    def cancel_task(self, task_id: str) -> TaskView:
        try:
            return TaskView.from_runtime_task(self._scheduler.cancel_pending(task_id))
        except ValueError as exc:
            message = str(exc)
            code = "TASK_NOT_FOUND" if "not found" in message.lower() else "CANCEL_REJECTED"
            raise TaskManagementError(code, message) from exc
