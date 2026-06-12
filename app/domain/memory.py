"""Domain types for app-layer markdown memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    """Supported read-only markdown memory documents."""

    INDEX = "index"
    USER_PROFILE = "user_profile"
    KNOWLEDGE = "knowledge"

    @classmethod
    def parse(cls, value: object) -> "MemoryKind":
        text = str(value or "").strip().lower()
        for kind in cls:
            if kind.value == text:
                return kind
        allowed = ", ".join(kind.value for kind in cls)
        raise ValueError(f"kind must be one of: {allowed}.")


@dataclass(frozen=True)
class MemoryDocument:
    kind: MemoryKind
    text: str


@dataclass(frozen=True)
class MemoryContextLine:
    line_number: int
    text: str


@dataclass(frozen=True)
class MemoryHit:
    kind: MemoryKind
    line_number: int
    text: str
    section: str | None = None
    score: float = 1.0
    match_type: str = "body"
    context: list[MemoryContextLine] | None = None
