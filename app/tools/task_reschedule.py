"""TaskRescheduleTool — Conversation Agent 改期一次性定时检查任务."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.task_management import TaskManagementError, TaskManagementService


class TaskRescheduleTool(Tool):
    """Reschedule a pending once-mode download check task (confirm-gated).

    Only ``QUEUED`` / ``WAITING`` tasks with ``check_policy.mode=once``
    can be rescheduled.  Continuous watch tasks and terminal tasks are
    rejected.
    """

    def __init__(self, service: TaskManagementService) -> None:
        super().__init__(
            name="task_reschedule",
            description=(
                "修改一个尚未开始的一次性定时检查任务的执行时间。"
                "只能修改 check_policy.mode=once 且状态为 queued 或 waiting 的任务。"
                "run_at 必须是带时区偏移的未来 ISO-8601 时间。"
            ),
        )
        self._service = service

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="task_id",
                type="string",
                description="要改期的任务 ID",
                required=True,
            ),
            ToolParameter(
                name="run_at",
                type="string",
                description=(
                    "新的执行时间，必须是带时区偏移的 ISO-8601 格式，"
                    "如 2026-06-25T20:00:00+08:00，且必须在未来。"
                ),
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        task_id = str(parameters.get("task_id", "")).strip()
        run_at = str(parameters.get("run_at", "")).strip()

        if not task_id:
            return ToolResponse.error(
                code="MISSING_TASK_ID",
                message="task_id 是必填参数，不能为空。",
            )

        if not run_at:
            return ToolResponse.error(
                code="MISSING_RUN_AT",
                message="run_at 是必填参数，必须是带时区的 ISO-8601 时间。",
            )

        try:
            task_view = self._service.reschedule_task(task_id, run_at)
        except TaskManagementError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)
        except ValueError as exc:
            return ToolResponse.error(code="RESCHEDULE_REJECTED", message=str(exc))
        except Exception as exc:
            return ToolResponse.error(
                code="RESCHEDULE_FAILED",
                message=f"改期失败：{exc}",
            )

        return ToolResponse.success(
            data=task_view.model_dump(),
            text=(
                f"任务 {task_id}（{task_view.description}）"
                f"已改期至 {task_view.run_after}。"
            ),
        )
