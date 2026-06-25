"""FastAPI app bootstrap for the current MVP.

This module wires routes and static frontend assets into a single app instance.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.adapters.qbittorrent import QBittorrentAdapter
from app.api.chat_routes import build_router
from app.api.memory_routes import build_memory_router
from app.api.mteam_routes import build_mteam_router
from app.api.task_routes import build_task_router
from app.config import get_settings
from app.logging_config import configure_logging
from app.mcp_pool import init_mcp_pool, shutdown_mcp_pool
from app.runtime.handlers.download_watch import DownloadWatchConfig
from app.runtime.worker import TaskWorkerConfig
from app.storage.db import ensure_schema
from app.domain.runtime_tasks import app_now
from app.task_runtime import (
    create_task_runtime,
    setup_download_watch_handler,
    setup_organize_download_handler,
)

logger = logging.getLogger(__name__)


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend"


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Manage MCP pool and task runtime lifecycle alongside the FastAPI application."""
    settings = get_settings()
    await init_mcp_pool()

    # -- Build task runtime --------------------------------------------------
    _task_db_path = settings.task_db_path
    ensure_schema(_task_db_path)
    task_runtime = create_task_runtime(
        db_path=_task_db_path,
        config=TaskWorkerConfig(
            per_kind_semaphores={
                "download_watch": settings.download_watch_concurrency,
                "organize_download": settings.organize_worker_concurrency,
            },
            tick_seconds=settings.task_worker_tick_seconds,
            lease_seconds=settings.task_lease_seconds,
            max_concurrency=settings.task_worker_concurrency,
            purge_max_age_seconds=settings.task_purge_max_age_seconds,
            event_consumed_purge_seconds=settings.event_consumed_purge_seconds,
            event_max_age_seconds=settings.event_max_age_seconds,
        ),
        clock=app_now,
    )

    # qB adapter for the download-watch handler.
    qb = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )
    setup_download_watch_handler(
        runtime=task_runtime,
        qb_adapter=qb,
        config=DownloadWatchConfig(
            poll_seconds=settings.download_watch_poll_seconds,
            error_backoff_max=settings.download_watch_error_backoff_max_seconds,
        ),
    )
    from app.services.organization_policy_store import (
        OrganizationAuthorizationPolicyStore,
    )

    settings_dir = Path(__file__).resolve().parents[1] / "memory" / "settings"
    organization_authorization_store = OrganizationAuthorizationPolicyStore(
        settings_dir
    )
    setup_organize_download_handler(
        runtime=task_runtime,
        organization_policy_store=organization_authorization_store,
    )

    task_runtime.reconcile_stale_initializing()
    asyncio.create_task(task_runtime.start())
    _app.state.task_runtime = task_runtime

    # ── Build shared TaskManagementService for task routes ──
    from app.services.task_management import TaskManagementService

    task_mgmt = TaskManagementService(
        scheduler=task_runtime.scheduler,
    )
    _app.state.task_management_service = task_mgmt
    _app.state.organization_authorization_store = organization_authorization_store

    try:
        yield
    finally:
        await task_runtime.stop()
        await shutdown_mcp_pool()


def create_app() -> FastAPI:
    """Create and configure the application object."""
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, lifespan=_app_lifespan)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        # Skip logging for high-frequency polling endpoints.
        path = request.url.path
        if path in ("/health",) or path.startswith("/task-events"):
            return response
        logger.info(
            "%s %s -> %d (%.0fms)",
            request.method,
            path,
            response.status_code,
            elapsed * 1000,
        )
        return response

    app.include_router(build_mteam_router())
    app.include_router(build_router())
    app.include_router(build_memory_router())
    app.include_router(build_task_router())

    frontend_dir = _frontend_dir()
    frontend_dist = frontend_dir / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    return app


app = create_app()
