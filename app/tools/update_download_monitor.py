"""Agent tool for atomic download-monitor mutation."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.domain.downloads import DownloadMonitorUpdate
from app.services.download_automation import DownloadAutomation, DownloadAutomationError


class UpdateDownloadMonitorTool(Tool):
    def __init__(self, automation: DownloadAutomation) -> None:
        super().__init__(
            name="update_download_monitor",
            description=(
                "原子修改 queued/waiting 下载监控的首次/下次检查时间、监控模式或完成动作。"
                "至少提供 start_at、mode、on_completed 之一；修改可能改变任务性质。"
                "start_at 必须是带时区且未来的 ISO-8601 绝对时间。"
            ),
        )
        self._automation = automation

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="task_id", type="string", description="下载监控任务 ID", required=True),
            ToolParameter(name="start_at", type="string", description="新的未来绝对检查时间", required=False),
            ToolParameter(name="mode", type="string", description="once 或 until_complete", required=False),
            ToolParameter(name="on_completed", type="string", description="notify 或 organize", required=False),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        fields: dict[str, Any] = {"task_id": str(parameters.get("task_id") or "").strip()}
        for name in ("start_at", "mode", "on_completed"):
            if name in parameters:
                fields[name] = parameters[name]
        try:
            receipt = self._automation.update_monitor(
                DownloadMonitorUpdate.model_validate(fields)
            )
        except DownloadAutomationError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)
        except Exception as exc:
            return ToolResponse.error(code="INVALID_REQUEST", message=str(exc))
        data = receipt.model_dump()
        return ToolResponse.success(
            data={**data, "receipt": data},
            text=(
                f"已更新下载监控 {receipt.task_id}：{receipt.mode}，"
                f"完成后 {receipt.on_completed}，下次检查 {receipt.start_at or '立即'}。"
            ),
        )
