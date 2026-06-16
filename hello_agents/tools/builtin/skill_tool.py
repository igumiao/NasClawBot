"""SkillTool — 将 SkillLoader 包装为 Agent 可调用的工具。

Agent 调用 skill_load("renaming-rules") → 获取对应 SKILL.md 的完整内容，
注入到对话上下文中。实现三级渐进式披露的 L2（按需加载）。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from hello_agents.tools.base import Tool, ToolParameter, ToolResponse

if TYPE_CHECKING:
    from hello_agents.skills.loader import SkillLoader


class SkillTool(Tool):
    """允许 Agent 按需加载 skill 的完整内容。

    技能列表（名称 + 简介）已在系统提示词中可见（L1 元数据）。
    当 Agent 需要某个技能的详细指导时，调用本工具获取完整 markdown
    内容（L2 body），内容会作为 tool_result 注入对话上下文。
    """

    def __init__(self, skill_loader: SkillLoader) -> None:
        super().__init__(
            name="skill_load",
            description=(
                "加载指定技能的完整指导文档。当你需要执行某个领域相关的"
                "任务时（如文件重命名、格式转换等），先调用此工具查看详细规范。"
                "可用的技能名称请参考系统提示词末尾的技能列表。"
            ),
        )
        self._skill_loader = skill_loader

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="name",
                type="string",
                description="要加载的技能名称（与系统提示词中技能列表的名称一致）",
                required=True,
            ),
        ]

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        name = str(parameters.get("name", "")).strip()
        if not name:
            return ToolResponse.error(
                code="INVALID_PARAM",
                message="请指定要加载的技能名称（name）。",
            )

        skill = self._skill_loader.get_skill(name)
        if skill is None:
            available = self._skill_loader.list_skills()
            hint = f"可用技能: {', '.join(available)}" if available else "暂无可用技能"
            return ToolResponse.error(
                code="SKILL_NOT_FOUND",
                message=f"未找到技能 '{name}'。{hint}",
            )

        return ToolResponse.success(
            text=skill.body,
            data={"name": skill.name, "description": skill.description},
        )
