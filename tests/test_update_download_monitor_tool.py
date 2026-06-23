from unittest.mock import MagicMock

from app.domain.downloads import DownloadMonitorReceipt
from app.tools.update_download_monitor import UpdateDownloadMonitorTool


def test_update_download_monitor_delegates_atomic_request():
    automation = MagicMock()
    automation.update_monitor.return_value = DownloadMonitorReceipt(
        task_id="task-1", torrent_hash="abc", torrent_name="Movie",
        start_at="2026-06-24T00:00:00+00:00", mode="once",
        on_completed="organize", status="waiting",
    )
    response = UpdateDownloadMonitorTool(automation).run({
        "task_id": "task-1", "mode": "once", "on_completed": "organize"
    })
    assert response.status.value == "success"
    request = automation.update_monitor.call_args.args[0]
    assert request.mode == "once"
    assert request.on_completed == "organize"


def test_update_download_monitor_requires_mutation():
    response = UpdateDownloadMonitorTool(MagicMock()).run({"task_id": "task-1"})
    assert response.status.value == "error"
    assert response.error_info["code"] == "INVALID_REQUEST"
