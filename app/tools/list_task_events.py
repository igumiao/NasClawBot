"""ListTaskEventsTool — 查询当前会话的后台任务事件历史."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.agent.runner import current_agent_session_id
from app.domain.runtime_tasks import TaskEventSeverity
from app.runtime.store import RuntimeTaskStore


class ListTaskEventsTool(Tool):
    """Query background task events for the current conversation session.

    Events are user-visible notifications emitted by background tasks
    (download watch, organize, etc.).  Unlike the auto-injected event
    block that only shows uninjected events, this tool lets the Agent
    actively search the event history — including already-injected and
    already-acknowledged events — to understand what happened while the
    user was away or during previous conversation turns.
    """

    _VALID_KINDS = frozenset(
        {
            "download_completed",
            "download_completed_no_path",
            "download_check_incomplete",
            "organize_completed",
            "task_failed",
        }
    )

    _VALID_SEVERITIES = frozenset(s.value for s in TaskEventSeverity)

    _DEFAULT_LIMIT = 10
    _MAX_LIMIT = 50

    def __init__(self, store: RuntimeTaskStore) -> None:
        super().__init__(
            name="list_task_events",
            description=(
                "查询当前会话的后台任务事件历史。事件包括下载完成、整理完成、任务失败等。"
                "可按键值(kind)、严重程度(severity)和数量(limit)筛选。"
                "用于了解后台任务的执行结果，不要重复执行已完成的操作。"
            ),
        )
        self._store = store

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="kind",
                type="string",
                description=(
                    "按事件类型筛选: download_completed(下载完成), "
                    "download_completed_no_path(下载完成但无路径), "
                    "download_check_incomplete(定时检查未完成), "
                    "organize_completed(整理完成), task_failed(任务失败)。"
                    "不传则返回所有类型。"
                ),
                required=False,
            ),
            ToolParameter(
                name="severity",
                type="string",
                description=(
                    "按严重程度筛选: success(成功), info(信息), "
                    "warning(警告), error(错误)。不传则返回所有级别。"
                ),
                required=False,
                enum=sorted(self._VALID_SEVERITIES),
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description=f"返回条数上限，默认 {self._DEFAULT_LIMIT}，最大 {self._MAX_LIMIT}。",
                required=False,
                default=self._DEFAULT_LIMIT,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        session_id = current_agent_session_id.get()
        if not session_id:
            return ToolResponse.error(
                code="NO_SESSION",
                message="当前没有活跃的 Agent 会话，无法查询事件。",
            )

        # ── Normalize parameters ──
        kind = str(parameters.get("kind", "")).strip() or None
        if kind is not None and kind not in self._VALID_KINDS:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=(
                    f"不支持的事件类型: {kind!r}。"
                    f"支持: {', '.join(sorted(self._VALID_KINDS))}"
                ),
            )

        severity = str(parameters.get("severity", "")).strip() or None
        if severity is not None and severity not in self._VALID_SEVERITIES:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=(
                    f"不支持的严重程度: {severity!r}。"
                    f"支持: {', '.join(sorted(self._VALID_SEVERITIES))}"
                ),
            )

        raw_limit = parameters.get("limit", self._DEFAULT_LIMIT)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="limit must be an integer.",
            )
        if limit < 1:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="limit must be >= 1.",
            )
        limit = min(limit, self._MAX_LIMIT)

        # ── Query ──
        filters: dict[str, Any] = {"source_session_id": session_id}
        if kind is not None:
            filters["kind"] = kind
        if severity is not None:
            filters["severity"] = severity

        events = self._store.list_events(limit=limit, filters=filters)

        if not events:
            return ToolResponse.success(
                text="当前会话没有匹配的后台任务事件。",
                data={"events": [], "count": 0},
            )

        # ── Build compact summary ──
        lines = [f"当前会话共 {len(events)} 条匹配事件：", ""]
        for ev in events:
            ack = "✓已确认" if ev.acknowledged_at else "○未确认"
            inj = "✓已注入" if ev.injected_at else "○未注入"
            severity_emoji = {
                "success": "✅",
                "info": "ℹ️",
                "warning": "⚠️",
                "error": "❌",
            }.get(ev.severity.value if hasattr(ev.severity, 'value') else str(ev.severity), "•")
            lines.append(
                f"{severity_emoji} [{ev.kind}] {ev.title}"
            )
            if ev.summary:
                lines.append(f"   {ev.summary}")
            lines.append(f"   {ack} {inj} | task={ev.task_id}")

        return ToolResponse.success(
            text="\n".join(lines),
            data={
                "events": [
                    {
                        "event_id": e.event_id,
                        "task_id": e.task_id,
                        "kind": e.kind,
                        "severity": e.severity.value if hasattr(e.severity, 'value') else str(e.severity),
                        "title": e.title,
                        "summary": e.summary,
                        "acknowledged": e.acknowledged_at is not None,
                        "injected": e.injected_at is not None,
                    }
                    for e in events
                ],
                "count": len(events),
            },
        )
