"""FastAPI app bootstrap for the current MVP.

This module wires routes and static frontend assets into a single app instance.
"""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.chat_routes import build_router
from app.api.memory_routes import build_memory_router
from app.api.mteam_routes import build_mteam_router
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend"


def create_app() -> FastAPI:
    """Create and configure the application object."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        logger.info(
            "%s %s -> %d (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed * 1000,
        )
        return response

    app.include_router(build_mteam_router())
    app.include_router(build_router())
    app.include_router(build_memory_router())

    frontend_dir = _frontend_dir()
    frontend_dist = frontend_dir / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    return app


app = create_app()
