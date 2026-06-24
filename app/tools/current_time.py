"""CurrentTimeTool -- expose server-local current date/time to the Agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse


class CurrentTimeTool(Tool):
    """Return the current date/time in a configured timezone.

    When *fixed_now* is provided the tool returns that datetime instead of
    calling ``datetime.now()``.  This allows evaluation runs to produce
    reproducible date/time output without monkeypatching.
    """

    def __init__(
        self,
        timezone_name: str = "Asia/Shanghai",
        fixed_now: datetime | None = None,
    ) -> None:
        super().__init__(
            name="current_time",
            description="获取当前日期、年份、月份、星期和时区。",
        )
        self._timezone_name = timezone_name
        self._fixed_now = fixed_now

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def to_openai_schema(self) -> dict[str, Any]:
        schema = super().to_openai_schema()
        schema["function"]["parameters"]["additionalProperties"] = False
        return schema

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        if not isinstance(parameters, dict):
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="current_time parameters must be an object.",
            )
        if parameters:
            unknown = ", ".join(sorted(parameters))
            return ToolResponse.error(
                code="INVALID_PARAM",
                message=f"current_time does not accept parameters: {unknown}",
            )

        try:
            timezone = ZoneInfo(self._timezone_name)
        except ZoneInfoNotFoundError:
            return ToolResponse.error(
                code="INVALID_TIMEZONE",
                message=f"Unknown timezone: {self._timezone_name}",
            )

        now = self._fixed_now or datetime.now(timezone)
        payload = {
            "iso": now.isoformat(),
            "date": now.date().isoformat(),
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "weekday": now.strftime("%A"),
            "timezone": self._timezone_name,
            "utc_offset": now.strftime("%z"),
        }
        return ToolResponse.success(
            text=(
                f"Current date is {payload['date']} "
                f"({payload['weekday']}, {payload['timezone']})."
            ),
            data=payload,
        )
