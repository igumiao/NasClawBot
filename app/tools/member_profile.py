"""MemberProfileTool — read-only M-Team member profile query."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.adapters.mteam import MTeamAdapter


class MemberProfileTool(Tool):
    """Query M-Team member profile (read-only)."""

    def __init__(self, adapter: MTeamAdapter) -> None:
        super().__init__(
            name="member_profile",
            description="查询当前 M-Team 用户的个人资料，包括上传/下载量、分享率和最近登录时间",
        )
        self._adapter = adapter

    def get_parameters(self) -> list[ToolParameter]:
        return []

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        profile = self._adapter.get_member_profile()
        if not profile:
            return ToolResponse.error(
                code="PROFILE_FAILED",
                message="无法获取 M-Team 用户资料。",
            )

        member_status = profile.get("memberStatus") or {}
        member_count = profile.get("memberCount") or {}

        safe_data = {
            "username": profile.get("username", ""),
            "lastLogin": member_status.get("lastLogin"),
            "uploaded": member_count.get("uploaded", "0"),
            "downloaded": member_count.get("downloaded", "0"),
            "shareRate": member_count.get("shareRate", "0"),
        }

        return ToolResponse.success(
            text=(
                f"用户 {safe_data['username']}："
                f"上传 {self._format_bytes(safe_data['uploaded'])}，"
                f"下载 {self._format_bytes(safe_data['downloaded'])}，"
                f"分享率 {safe_data['shareRate']}，"
                f"最近登录 {safe_data['lastLogin'] or '未知'}"
            ),
            data=safe_data,
        )

    @staticmethod
    def _format_bytes(value: str) -> str:
        try:
            size_bytes = int(value)
        except (TypeError, ValueError):
            return str(value or "0")
        if size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        scale = 0
        size_float = float(size_bytes)
        while size_float >= 1024 and scale < len(units) - 1:
            size_float /= 1024
            scale += 1
        return f"{size_float:.2f} {units[scale]}"
