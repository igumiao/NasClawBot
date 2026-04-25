"""Minimal HTTP routes for the current chat-shell milestone.

These routes only provide health and frontend serving; workflow endpoints come
in later tasks.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# Route modules live in `app/api/`; move to repo root before joining frontend.
_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


@router.get("/health")
def health() -> dict[str, str]:
    """Basic liveness probe used by local checks/tests."""
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve the chat page when present, fallback to a tiny placeholder."""
    if _FRONTEND_INDEX.exists():
        return _FRONTEND_INDEX.read_text(encoding="utf-8")
    return "<h1>fnOS Media Agent</h1>"
