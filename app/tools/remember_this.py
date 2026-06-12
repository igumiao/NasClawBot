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
                "将一条值得长期记忆的信息追加到记忆收件箱 (memory_inbox.md)，"
                "供操作者后续人工整理到对应的记忆文件中。\n"
                "\n"
                "只在以下情况调用，宁缺毋滥：\n"
                "- 学到了用户的新偏好（画质、编码、语言、下载策略等）\n"
                "- 发现了一个可复用的搜索/下载技巧或工作流\n"
                "- 用户明确表达了一个长期意图或偏好\n"
                "- 操作过程中踩了坑，值得记录下来避免重复\n"
                "\n"
                "绝对不要记录：\n"
                "- 本次搜索的候选列表或结果\n"
                "- 下载操作本身（那在 qB 历史里）\n"
                "- 你没有足够证据的推断\n"
                "- 和已有记忆明显重复的内容\n"
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
