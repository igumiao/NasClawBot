from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    if _FRONTEND_INDEX.exists():
        return _FRONTEND_INDEX.read_text(encoding="utf-8")
    return "<h1>fnOS Media Agent</h1>"
