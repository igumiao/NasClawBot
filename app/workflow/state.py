"""Typed LangGraph state for the minimal search-to-confirmation flow."""

from typing import Any, TypedDict

from app.domain.models import ResourceCandidate


class AgentState(TypedDict, total=False):
    """Shared state passed between workflow nodes."""

    session_id: str
    user_message: str
    keyword: str
    search_results: list[ResourceCandidate]
    confirmation_payload: dict[str, Any]
    receipt: dict[str, Any]
    status: str
    error: str
