from datetime import datetime, timezone

import pytest

from app.domain.downloads import DownloadMonitorSpec, build_download_monitor_payload
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.services.task_management import TaskListQuery, TaskManagementError, TaskManagementService
from app.storage.db import ensure_schema


def _service(tmp_path):
    now = lambda: datetime.now(timezone.utc)
    ids = iter(["task-1", "task-2", "task-3"])
    db = tmp_path / "tasks.db"
    ensure_schema(db)
    scheduler = TaskScheduler(RuntimeTaskStore(db, now, lambda: next(ids)), now, lambda: next(ids))
    return TaskManagementService(scheduler), scheduler


def test_list_projects_monitor_semantics_without_payload(tmp_path):
    service, scheduler = _service(tmp_path)
    scheduler.enqueue(kind="download_watch", payload=build_download_monitor_payload(
        torrent_hash="abc", torrent_name="Movie", save_path="/downloads",
        monitor=DownloadMonitorSpec(mode="once", on_completed="notify"),
    ))
    view = service.list_tasks(TaskListQuery())[0]
    assert view.torrent_hash == "abc"
    assert view.mode == "once"
    assert view.on_completed == "notify"
    assert "payload" not in view.model_dump()


def test_cancel_only_pending(tmp_path):
    service, scheduler = _service(tmp_path)
    task = scheduler.enqueue(kind="download_watch", payload={})
    assert service.cancel_task(task.task_id).status == "cancelled"
    with pytest.raises(TaskManagementError) as exc:
        service.cancel_task(task.task_id)
    assert exc.value.code == "CANCEL_REJECTED"
