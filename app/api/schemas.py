"""Request payload schemas for API endpoints.

These models establish an explicit contract even before full workflow wiring.
"""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Incoming user message for a specific session."""

    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    """Confirmation-stage action payload (approve/refine/cancel)."""

    session_id: str
    action: str
    selected_result_id: str | None = None
    feedback_text: str | None = None
