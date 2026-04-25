"""FastAPI app bootstrap for the current MVP.

This module wires routes and static frontend assets into a single app instance.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat_routes import router as chat_router
from app.config import get_settings


def create_app() -> FastAPI:
    """Create and configure the application object."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(chat_router)

    # `app/main.py` lives under `app/`, while static assets are in repo-level
    # `frontend/`, so we step one level up before appending `frontend`.
    static_dir = Path(__file__).resolve().parents[1] / "frontend"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app


app = create_app()
