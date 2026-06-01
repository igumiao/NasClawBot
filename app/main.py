"""FastAPI app bootstrap for the current MVP.

This module wires routes and static frontend assets into a single app instance.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat_routes import build_router
from app.config import get_settings
from app.logging_config import configure_logging


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend"


def create_app() -> FastAPI:
    """Create and configure the application object."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name)
    app.include_router(build_router())

    frontend_dir = _frontend_dir()
    frontend_dist = frontend_dir / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    return app


app = create_app()
