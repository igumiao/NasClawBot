"""Search tool wrappers used by workflow nodes.

This module keeps workflow nodes decoupled from specific adapter call styles.
"""

from collections.abc import Callable
from typing import Protocol

from app.domain.models import ResourceCandidate, SearchConstraints


class SearchTool(Protocol):
    """Protocol for a callable search tool used by the workflow."""

    def __call__(self, constraints: SearchConstraints) -> list[ResourceCandidate]:
        ...


def search_mteam_candidates(
    search_tool: SearchTool | Callable[[SearchConstraints], list[ResourceCandidate]],
    constraints_dict: dict,
) -> list[ResourceCandidate]:
    """Normalize constraints and execute the injected search capability."""

    constraints = SearchConstraints.model_validate(constraints_dict)
    return search_tool(constraints)
