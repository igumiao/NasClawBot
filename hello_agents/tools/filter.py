"""工具过滤器 — 在工具列表发给 LLM/子Agent 之前筛选范围。

职责：缩减 LLM 可用的工具集合，减少 context window 消耗，限定子 Agent 能力边界。
不关心工具怎么被调用——那是 Gate 的事。
"""

from __future__ import annotations

from typing import Callable, Iterable


def _identity(tool_name: str) -> str:
    return tool_name


class Filter:
    """按允许列表或谓词筛选工具。

    Filter(allow=["read", "grep", "glob"])           # 只暴露这三个
    Filter(allow=lambda t: t.permission == READONLY)  # 谓词模式（如果有 permission 属性）
    Filter()                                           # 空 filter = 不放行任何工具
    """

    def __init__(
        self,
        allow: Iterable[str] | Callable[[str], bool] | None = None,
    ) -> None:
        if allow is None:
            self._predicate: Callable[[str], bool] = lambda _: False
        elif callable(allow) and not isinstance(allow, (list, set, tuple)):
            self._predicate = allow
        else:
            allowed: set[str] = set(allow)  # type: ignore[arg-type]
            self._predicate = lambda name: name in allowed

    def apply(self, tool_names: list[str]) -> list[str]:
        """返回过滤后的工具名列表。"""
        return [n for n in tool_names if self._predicate(n)]
