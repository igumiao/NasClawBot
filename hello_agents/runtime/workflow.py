"""Generic sequential workflow runner for HelloAgents runtime.

No NasClawBot-specific logic. Steps are callables that receive and return a
state dict. Execution stops when status reaches a terminal value.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

StepFunc = Callable[[dict[str, Any]], dict[str, Any]]

_TERMINAL_STATUSES = frozenset({"awaiting_approval", "completed", "canceled", "error"})


class SequentialWorkflow:
    """Run a list of steps in order, halting at terminal statuses."""

    def __init__(self, steps: list[StepFunc]) -> None:
        if not steps:
            raise ValueError("SequentialWorkflow requires at least one step.")
        self._steps = steps

    def run(self, envelope: dict[str, Any]) -> dict[str, Any]:
        for step in self._steps:
            envelope = step(envelope)
            if envelope.get("status") in _TERMINAL_STATUSES:
                break
        return envelope
