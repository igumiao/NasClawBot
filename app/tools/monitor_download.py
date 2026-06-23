"""Agent tool for creating a durable qB download monitor."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.domain.downloads import DownloadMonitorRequest
from app.services.download_automation import DownloadAutomation, DownloadAutomationError


class MonitorDownloadTool(Tool):
    def __init__(self, automation: DownloadAutomation) -> None:
        super().__init__(
            name="monitor_download",
            description=(
                "为已存在的 qBittorrent 种子创建下载监控。mode=once 时到首次检查后结束："
                "未完成则通知，完成则按 on_completed 通知或整理；mode=until_complete 时未完成会按动态间隔继续监督，"
                "完成后按 on_completed=notify|organize 执行。start_at 可省略表示立即开始；指定时必须是带时区且未来的 ISO-8601 绝对时间。"
            ),
        )
        self._automation = automation

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="torrent_hash", type="string", description="qBittorrent info hash", required=True),
            ToolParameter(
                name="start_at",
                type="string",
                description="可选首次检查时间；带时区的未来 ISO-8601 绝对时间，省略表示立即",
                required=False,
            ),
            ToolParameter(
                name="mode", type="string", description="监控模式：once 或 until_complete", required=True
            ),
            ToolParameter(
                name="on_completed", type="string", description="完成动作：notify 或 organize", required=True
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            from app.agent.runner import current_agent_session_id

            request = DownloadMonitorRequest(
                torrent_hash=str(parameters.get("torrent_hash") or "").strip(),
                start_at=(str(parameters["start_at"]).strip() if parameters.get("start_at") else None),
                mode=parameters.get("mode"),
                on_completed=parameters.get("on_completed"),
            )
            receipt = self._automation.create_monitor(
                request,
                source_session_id=current_agent_session_id.get(),
                idempotency_key=str(parameters.get("idempotency_key") or ""),
            )
        except DownloadAutomationError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)
        except Exception as exc:
            return ToolResponse.error(code="INVALID_REQUEST", message=str(exc))
        data = receipt.model_dump()
        return ToolResponse.success(
            data={**data, "receipt": data},
            text=(
                f"已创建下载监控 {receipt.task_id}：{receipt.mode}，"
                f"完成后 {receipt.on_completed}，首次检查 {receipt.start_at or '立即'}。"
            ),
        )
