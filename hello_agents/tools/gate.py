"""执行闸门 — 工具调用在 run() 之前过三道闸门。

流程:
    ToolCall → 闸门 1 (deny) → DENY
            → 闸门 2 (confirm) → ASK_USER
            → 都没命中 → ALLOW

与 Filter 的区别: Filter 管"给 LLM 看哪些工具"，Gate 管"这次调用能不能执行"。
同一个工具 (如 bash)，参数不同结果不同——bash("ls") 三闸全过，bash("sudo rm -rf /") 被闸门 1 拦下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class GateResult(Enum):
    ALLOW = auto()       # 直接执行
    DENY = auto()        # 拒绝，不执行
    ASK_USER = auto()    # 暂停，等用户确认


@dataclass
class ToolCall:
    """Gate 检查的输入——一次具体的工具调用。"""
    tool_name: str
    params: dict[str, Any] = field(default_factory=dict)


Rule = Callable[[ToolCall], bool]


class Gate:
    """三道闸门: deny_rules → confirm_rules → 默认放行。

    deny_rules 和 confirm_rules 都是 ToolCall → bool 的谓词。
    返回 True 表示"命中该闸门"。
    """

    def __init__(
        self,
        deny: list[Rule] | None = None,
        confirm: list[Rule] | None = None,
    ) -> None:
        self.deny_rules: list[Rule] = deny or []
        self.confirm_rules: list[Rule] = confirm or []

    def check(self, call: ToolCall) -> GateResult:
        for rule in self.deny_rules:
            if rule(call):
                return GateResult.DENY
        for rule in self.confirm_rules:
            if rule(call):
                return GateResult.ASK_USER
        return GateResult.ALLOW


# ── 常用规则工厂 ──────────────────────────────────────────────


def deny_command(*patterns: str) -> Rule:
    """拒绝参数中包含特定命令模式的操作。

    Gate(deny=[deny_command("sudo", "rm -rf", "mkfs", "dd if=")])  # 封锁危险指令
    """

    def rule(call: ToolCall) -> bool:
        params_str = str(call.params).lower()
        return any(p.lower() in params_str for p in patterns)

    return rule


def deny_paths(*paths: str) -> Rule:
    """拒绝操作指定路径前缀的操作。

    Gate(deny=[deny_paths("/", "/etc", "/usr", "/boot")])  # 禁止触碰系统路径
    """

    def rule(call: ToolCall) -> bool:
        target = str(call.params.get("path") or call.params.get("command") or "")
        return any(target == p or target.startswith(p + "/") for p in paths)

    return rule


def deny_outside_workspace(workspace: str) -> Rule:
    """拒绝操作工作区外路径的操作。

    Gate(deny=[deny_outside_workspace("/home/user/project")])
    """

    def rule(call: ToolCall) -> bool:
        target = str(call.params.get("path") or "")
        if not target:
            return False
        from pathlib import Path as _Path

        try:
            _Path(target).resolve().relative_to(_Path(workspace).resolve())
            return False
        except ValueError:
            return True

    return rule


def deny_regex(pattern: str) -> Rule:
    r"""拒绝参数匹配正则表达式的操作。

    Gate(deny=[deny_regex(r"curl\s+.*\|\s*(ba)*sh")])  # 禁止 curl pipe bash
    """
    import re as _re

    compiled = _re.compile(pattern)

    def rule(call: ToolCall) -> bool:
        return bool(compiled.search(str(call.params)))

    return rule
