"""TaskListTool — Conversation Agent 查询后台任务列表（只读）."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.task_management import TaskListQuery, TaskManagementService


class TaskListTool(Tool):
    """List background runtime tasks with optional filters (read-only)."""

    def __init__(self, service: TaskManagementService) -> None:
        super().__init__(
            name="task_list",
            description=(
                "查询后台任务列表，可按状态和类型筛选。返回安全的语义摘要，"
                "不包含原始 payload 或授权快照等内部数据。"
            ),
        )
        self._service = service

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="status",
                type="string",
                description=(
                    "按状态筛选：queued, running, waiting, succeeded, failed, cancelled"
                ),
                required=False,
            ),
            ToolParameter(
                name="kind",
                type="string",
                description="按任务类型筛选，如 download_watch、organize_download",
                required=False,
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="返回条数上限，默认 50",
                required=False,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        query = TaskListQuery(
            status=parameters.get("status"),
            kind=parameters.get("kind"),
            limit=parameters.get("limit", 50),
        )
        try:
            tasks = self._service.list_tasks(query)
        except Exception as exc:
            return ToolResponse.error(
                code="LIST_FAILED",
                message=f"查询任务列表失败{f'：{exc}' if str(exc) else ''}",
            )

        if not tasks:
            return ToolResponse.success(
                data={"tasks": [], "count": 0},
                text="当前没有匹配的后台任务。",
            )

        task_dicts = [t.model_dump() for t in tasks]
        return ToolResponse.success(
            data={"tasks": task_dicts, "count": len(task_dicts)},
            text=f"找到 {len(task_dicts)} 个任务。",
        )
