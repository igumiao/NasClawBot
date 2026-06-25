"""TaskCancelTool — Conversation Agent 取消尚未开始的后台任务."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.task_management import TaskManagementError, TaskManagementService


class TaskCancelTool(Tool):
    """Cancel a queued/waiting background task (confirm-gated).

    Only tasks that have not yet been claimed by a worker can be cancelled.
    Running and terminal tasks are rejected.
    """

    def __init__(self, service: TaskManagementService) -> None:
        super().__init__(
            name="task_cancel",
            description=(
                "取消一个尚未开始的后台任务（状态为 queued 或 waiting 的任务）。"
                "正在运行或已完成的任务无法取消。取消后保留审计记录，不删除任务。"
            ),
        )
        self._service = service

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="task_id",
                type="string",
                description="要取消的任务 ID",
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        task_id = str(parameters.get("task_id", "")).strip()
        if not task_id:
            return ToolResponse.error(
                code="MISSING_TASK_ID",
                message="task_id 是必填参数，不能为空。",
            )

        try:
            task_view = self._service.cancel_task(task_id)
        except TaskManagementError as exc:
            return ToolResponse.error(code=exc.code, message=exc.message)
        except ValueError as exc:
            return ToolResponse.error(code="CANCEL_REJECTED", message=str(exc))
        except Exception as exc:
            return ToolResponse.error(
                code="CANCEL_FAILED",
                message=f"取消任务失败{f'：{exc}' if str(exc) else ''}",
            )

        return ToolResponse.success(
            data=task_view.model_dump(),
            text=f"任务 {task_id}（{task_view.description}）已取消。",
        )
