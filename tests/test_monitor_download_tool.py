from unittest.mock import MagicMock

from app.domain.downloads import DownloadMonitorReceipt
from app.tools.monitor_download import MonitorDownloadTool


def test_monitor_download_schema_and_delegation():
    automation = MagicMock()
    automation.create_monitor.return_value = DownloadMonitorReceipt(
        task_id="task-1", torrent_hash="abc", torrent_name="Movie",
        start_at=None, mode="until_complete", on_completed="notify", status="queued",
    )
    tool = MonitorDownloadTool(automation)
    params = {item.name: item for item in tool.get_parameters()}
    assert set(params) == {"torrent_hash", "start_at", "mode", "on_completed"}
    assert params["start_at"].required is False
    response = tool.run({
        "torrent_hash": "abc", "mode": "until_complete", "on_completed": "notify"
    })
    assert response.status.value == "success"
    assert response.data["receipt"]["task_id"] == "task-1"


def test_monitor_download_rejects_invalid_mode():
    response = MonitorDownloadTool(MagicMock()).run({
        "torrent_hash": "abc", "mode": "continuous", "on_completed": "notify"
    })
    assert response.status.value == "error"
