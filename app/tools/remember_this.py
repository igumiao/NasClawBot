"""RememberThisTool -- append a memory entry to the memory inbox."""

from __future__ import annotations

from typing import Any

from hello_agents.tools.base import Tool, ToolParameter
from hello_agents.tools.response import ToolResponse

from app.services.markdown_memory_store import MarkdownMemoryStore


class RememberThisTool(Tool):
    """Append a dated memory entry to the memory inbox for later manual curation."""

    _MAX_TEXT_LENGTH = 2000

    def __init__(self, store: MarkdownMemoryStore | None = None) -> None:
        super().__init__(
            name="remember_this",
            description=(
                "将一条关于用户的信息追加到记忆收件箱，供后台记忆整理系统后续自动分类、"
                "合并或更新到对应的记忆文件中。\n"
                "\n"
                "把自己当成了解用户的贴身管家。对话中了解到关于用户的任何信息都可以记：\n"
                "- 身份背景：名字称呼、职业、所在城市、年龄段\n"
                "- 兴趣爱好：影视、音乐、游戏、运动、美食、阅读等任何提到的喜好\n"
                "- 生活状态：作息、工作节奏、近期在忙什么\n"
                "- 观点态度：对某部作品/话题的看法，喜欢什么讨厌什么\n"
                "- 影视偏好：画质、编码、音轨、字幕、类型偏好\n"
                "- 技术环境：硬件配置、NAS 型号、网络条件\n"
                "- 搜索/下载过程中学到的可复用技巧或踩过的坑\n"
                "\n"
                "绝对不要记录：\n"
                "- 本次搜索的候选列表或结果\n"
                "- 下载操作本身（那在 qB 历史里）\n"
                "- 你没有足够证据的推断\n"
                "\n"
                "不要担心与已有记忆重复或矛盾——后台记忆整理系统会自动去重、合并和更新。"
                "值得记的就直接记。"
                "\n"
                "内容要求：1-2 句描述值得记住的信息，再加 1 句记录原因。"
                "自由表述即可，无需遵循固定模板。"
            ),
        )
        self._store = store or MarkdownMemoryStore()

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="text",
                type="string",
                description=(
                    "要记录的内容，1-2 句信息加 1 句原因。"
                    "自由格式，无需遵循固定模板。"
                ),
                required=True,
            ),
        ]

    def to_openai_schema(self) -> dict[str, Any]:
        schema = super().to_openai_schema()
        schema["function"]["parameters"]["additionalProperties"] = False
        return schema

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        try:
            text = self._normalize_parameters(parameters)
        except ValueError as exc:
            return ToolResponse.error(code="INVALID_PARAM", message=str(exc))

        entry = self._store.append_to_inbox(text=text)
        return ToolResponse.success(
            text="已将一条知识追加到记忆收件箱。",
            data={
                "entry": entry.strip(),
            },
        )

    def _normalize_parameters(self, parameters: dict[str, Any]) -> str:
        if not isinstance(parameters, dict):
            raise ValueError("remember_this parameters must be an object.")

        unknown = sorted(set(parameters) - {"text"})
        if unknown:
            raise ValueError(f"Unsupported remember_this parameters: {', '.join(unknown)}")

        text = str(parameters.get("text") or "").strip()
        if not text:
            raise ValueError("text is required.")
        if len(text) > self._MAX_TEXT_LENGTH:
            raise ValueError(f"text must be <= {self._MAX_TEXT_LENGTH} characters.")

        return text
