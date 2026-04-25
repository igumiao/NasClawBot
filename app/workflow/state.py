"""Typed LangGraph state for the minimal search-to-confirmation flow."""

from typing import Any, TypedDict

from app.domain.models import ResourceCandidate, ScoredCandidate


class AgentState(TypedDict, total=False):
    """Shared state passed between workflow nodes."""

    session_id: str
    user_message: str
    constraints: dict[str, Any]
    search_results: list[ResourceCandidate]
    scored_results: list[ScoredCandidate]
    confirmation_payload: dict[str, Any]
    status: str
