"""ScheduleDownloadCheckTool — Conversation Agent 创建一次性定时下载检查."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.task_management import TaskManagementService


class ScheduleDownloadCheckTool(Tool):
    """Create a one-shot future qBittorrent download completion check.

    The task will not query qB before the specified time.  At the scheduled
    time it performs exactly one business check:
    - Completed → follow the resolved follow-up (notify or auto-organize).
    - Incomplete → publish a notification and terminate (no further checks).
    """

    def __init__(self, service: TaskManagementService) -> None:
        super().__init__(
            name="schedule_download_check",
            description=(
                "为一个已存在的 qBittorrent 种子创建一次性未来下载完成检查。"
                "到期后执行一次检查：已完成则按本任务 follow_up 或 Settings 默认值通知/整理；"
                "未完成则仅通知并终止，不会继续反复检查。"
                "run_at 必须是带时区偏移的绝对 ISO-8601 时间，如 2026-06-25T20:00:00+08:00。"
                "follow_up 可选：notify_only（仅通知）或 auto_organize（自动整理）；"
                "不指定则使用 Settings 默认值。"
            ),
        )
        self._service = service

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="torrent_hash",
                type="string",
                description="qBittorrent info hash，标识要检查的种子",
                required=True,
            ),
            ToolParameter(
                name="run_at",
                type="string",
                description=(
                    "检查执行的绝对时间，必须是带时区偏移的 ISO-8601 格式，"
                    "如 2026-06-25T20:00:00+08:00。不接受不带时区的本地时间。"
                ),
                required=True,
            ),
            ToolParameter(
                name="follow_up",
                type="string",
                description=(
                    "下载完成后的行为：notify_only（仅通知）或 auto_organize（自动整理）。"
                    "不指定则使用 Settings 中的组织自动化默认值。"
                ),
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        from app.domain.downloads import ScheduleDownloadCheckRequest
        from app.services.task_management import TaskManagementError

        torrent_hash = str(parameters.get("torrent_hash", "")).strip()
        run_at = str(parameters.get("run_at", "")).strip()
        follow_up_raw = parameters.get("follow_up")

        if not torrent_hash:
            return ToolResponse.error(
                code="MISSING_TORRENT_HASH",
                message="torrent_hash 是必填参数，不能为空。",
            )

        if not run_at:
            return ToolResponse.error(
                code="MISSING_RUN_AT",
                message="run_at 是必填参数，必须是带时区的 ISO-8601 时间。",
            )

        follow_up = None
        if follow_up_raw is not None:
            follow_up = str(follow_up_raw).strip()
            if follow_up not in ("notify_only", "auto_organize"):
                return ToolResponse.error(
                    code="INVALID_FOLLOW_UP",
                    message=(
                        f"follow_up 必须是 notify_only 或 auto_organize，"
                        f"收到了 {follow_up!r}"
                    ),
                )

        try:
            request = ScheduleDownloadCheckRequest(
                torrent_hash=torrent_hash,
                run_at=run_at,
                follow_up=follow_up,  # type: ignore[arg-type]
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INVALID_REQUEST",
                message=f"参数验证失败：{exc}",
            )

        # The runner sets current_agent_session_id before the tool runs.
        from app.agent.runner import current_agent_session_id

        session_id = current_agent_session_id.get() or ""
        idempotency_key = str(parameters.get("idempotency_key", "") or "")

        try:
            receipt = self._service.create_download_check(
                request=request,
                source_session_id=session_id,
                idempotency_key=idempotency_key,
            )
        except TaskManagementError as exc:
            return ToolResponse.error(
                code=exc.code,
                message=exc.message,
            )
        except Exception as exc:
            return ToolResponse.error(
                code="INTERNAL_ERROR",
                message=f"创建定时检查失败：{exc}",
            )

        return ToolResponse.success(
            data=receipt.model_dump(),
            text=(
                f"已创建定时下载检查任务 {receipt.task_id}。"
                f"种子 {receipt.torrent_name} 将于 {receipt.run_at} 检查。"
                f"完成后将{'自动整理' if receipt.resolved_follow_up == 'auto_organize' else '通知你'}；"
                f"未完成仅通知并终止。"
            ),
        )
