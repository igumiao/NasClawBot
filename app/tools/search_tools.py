"""Search tool wrappers used by workflow nodes.

This module keeps workflow nodes decoupled from specific adapter call styles.
"""

from collections.abc import Callable
from typing import Protocol

from app.domain.models import ResourceCandidate


class SearchTool(Protocol):
    """Protocol for a callable search tool used by the workflow."""

    def __call__(self, keyword: str) -> list[ResourceCandidate]:
        ...


def search_mteam_candidates(
    search_tool: SearchTool | Callable[[str], list[ResourceCandidate]],
    keyword: str,
) -> list[ResourceCandidate]:
    """Execute the injected search capability with a single keyword."""

    return search_tool(keyword)
