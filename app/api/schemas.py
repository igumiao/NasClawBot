"""Request/response payload schemas for the API layer."""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming user message for a specific session."""

    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    """Confirmation-stage action payload for current workflow actions."""

    session_id: str
    action: str
    selected_result_id: str | None = None
    confirmation_payload: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    """Minimal chat response shape consumed by the browser shell."""

    session_id: str
    status: str
    confirmation_payload: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None


class ConfirmResponse(BaseModel):
    """Response shape for confirmation actions."""

    session_id: str
    status: str
    confirmation_payload: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: str | None = None
    messages: list[str] = Field(default_factory=list)
