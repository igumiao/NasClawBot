from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    action: str
    selected_result_id: str | None = None
    feedback_text: str | None = None
