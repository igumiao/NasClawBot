"""Application-level integration module for the runtime task system.

``TaskRuntime`` is the top-level composition root that owns:

* :class:`RuntimeTaskStore` — SQLite persistence layer
* :class:`TaskScheduler` — external-facing task lifecycle API
* :class:`TaskWorker` — in-process async worker loop
* :class:`HandlerRegistry` — kind-to-handler mapping

Typical usage in the FastAPI lifespan::

    from app.adapters.qbittorrent import QBittorrentAdapter
    from app.config import get_settings
    from app.runtime.handlers.download_watch import DownloadWatchConfig
    from app.task_runtime import create_task_runtime, setup_download_watch_handler

    settings = get_settings()
    qb = QBittorrentAdapter(
        base_url=settings.qb_base_url,
        username=settings.qb_username,
        password=settings.qb_password,
    )
    runtime = create_task_runtime(db_path="memory/runtime/tasks.db")
    setup_download_watch_handler(
        runtime=runtime,
        qb_adapter=qb,
        config=DownloadWatchConfig(
            poll_seconds=settings.download_watch_poll_seconds,
            error_backoff_max=settings.download_watch_error_backoff_max_seconds,
        ),
    )
    runtime.reconcile_stale_initializing()
    asyncio.create_task(runtime.start())

    yield

    await runtime.stop()
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.adapters.qbittorrent import QBittorrentAdapter
from pathlib import Path

from app.domain.runtime_tasks import RuntimeTask, TaskStatus
from app.runtime.handlers.download_watch import DownloadWatchConfig, DownloadWatchHandler
from app.runtime.handlers.organize_download import (
    OrganizeDownloadConfig,
    OrganizeDownloadHandler,
)
from app.runtime.registry import Handler, HandlerRegistry
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore
from app.runtime.worker import TaskWorker, TaskWorkerConfig

logger = logging.getLogger(__name__)

# Default stale threshold: tasks stuck in INITIALIZING longer than this are
# considered orphaned and will be failed during startup reconciliation.
_STALE_INITIALIZING_SECONDS = 300


class TaskRuntime:
    """Application-level composition root for the runtime task system.

    Owns the store, scheduler, worker, and handler registry.  Manages the
    worker lifecycle and provides crash-reconciliation for orphaned tasks
    left in ``INITIALIZING`` status after an unclean shutdown.
    """

    def __init__(
        self,
        db_path: str | Path,
        config: TaskWorkerConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Initialise the runtime.

        Args:
            db_path: Filesystem path to the SQLite database file.
            config: Worker configuration.  A default ``TaskWorkerConfig``
                is created when ``None``.
            clock: Authoritative datetime source for the store, scheduler,
                handlers, and worker claim loop.  When omitted, uses the
                clock from ``config`` (whose default is ``datetime.now``).
            id_factory: Callable returning a unique ``str``.  Defaults to
                ``lambda: uuid.uuid4().hex``.
        """
        base_config = config or TaskWorkerConfig()
        self._clock = clock or base_config.clock
        # One authoritative clock must drive every runtime participant.
        # Otherwise canonical UTC ``run_after`` values can be compared by
        # SQLite against local-naive worker timestamps as plain text, making
        # future tasks appear due on every worker tick.  Copy the dataclass so
        # a caller-owned config object is not mutated.
        self._config = replace(base_config, clock=self._clock)
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

        # Core instances.
        self._store = RuntimeTaskStore(
            db_path=db_path,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._scheduler = TaskScheduler(
            store=self._store,
            clock=self._clock,
            id_factory=self._id_factory,
        )
        self._registry = HandlerRegistry()

        # Worker lifecycle state.
        self._worker: TaskWorker | None = None
        self._worker_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def scheduler(self) -> TaskScheduler:
        """Expose the :class:`TaskScheduler` for external callers.

        Routes, agents, and integration code use this to enqueue tasks,
        check status, cancel, and manage the task lifecycle without
        accessing the store directly.
        """
        return self._scheduler

    @property
    def store(self) -> RuntimeTaskStore:
        """Expose the underlying :class:`RuntimeTaskStore`.

        Primarily intended for the worker loop and internal reconciliation.
        Most external callers should prefer :attr:`scheduler` for task
        lifecycle operations.
        """
        return self._store

    @property
    def registry(self) -> HandlerRegistry:
        """Expose the :class:`HandlerRegistry` for reading registered kinds."""
        return self._registry

    @property
    def clock(self) -> Callable[[], datetime]:
        """Expose the clock callable for dependent handler creation."""
        return self._clock

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(self, kind: str, handler: Handler) -> None:
        """Register an async handler for *kind*.

        Args:
            kind: Task kind string (e.g. ``"download_watch"``).
            handler: Async callable matching the ``Handler`` signature.

        Raises:
            ValueError: When *kind* is already registered.
        """
        self._registry.register(kind, handler)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the worker loop as a background asyncio task.

        Must be called after handlers are registered so the worker can
        dispatch claimed tasks.  Safe to call from the FastAPI lifespan
        startup::

            runtime = create_task_runtime(...)
            asyncio.create_task(runtime.start())

        No-op if the worker is already running.
        """
        if self._worker_task is not None:
            logger.warning("TaskRuntime worker is already running")
            return

        self._worker = TaskWorker(
            store=self._store,
            registry=self._registry,
            config=self._config,
        )

        self._worker_task = asyncio.create_task(
            self._worker.run(),
            name="task-worker-loop",
        )
        logger.info("TaskRuntime worker loop started")

    async def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish.

        In-flight handlers run to completion.  This coroutine returns when
        the worker's main loop has exited.

        Safe to call from the FastAPI lifespan shutdown::

            await runtime.stop()
        """
        if self._worker_task is None:
            return

        await self._worker.stop()
        try:
            await asyncio.wait_for(self._worker_task, timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("TaskRuntime worker did not stop within 30s, cancelling")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        self._worker = None
        self._worker_task = None
        logger.info("TaskRuntime worker stopped")

    # ------------------------------------------------------------------
    # Crash reconciliation (SS10)
    # ------------------------------------------------------------------

    def reconcile_stale_initializing(
        self,
        stale_seconds: int = _STALE_INITIALIZING_SECONDS,
    ) -> list[RuntimeTask]:
        """Fail any ``INITIALIZING`` tasks whose ``created_at`` is too old.

        Inspects all tasks in ``INITIALIZING`` status and transitions those
        whose ``created_at`` timestamp is older than *stale_seconds* to
        ``FAILED`` with a ``stale_initialization`` error code.

        Designed to be called once at application startup before the worker
        loop begins, after the store has been opened::

            runtime = create_task_runtime(...)
            runtime.register_handler("download_watch", my_handler)
            stale = runtime.reconcile_stale_initializing()
            asyncio.create_task(runtime.start())

        Args:
            stale_seconds: Age threshold in seconds.  Any ``INITIALIZING``
                task older than this is considered stale.  Default 300 (5
                minutes).

        Returns:
            The list of tasks that were failed by this reconciliation pass.
        """
        now = self._clock()
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
        stale_tasks: list[RuntimeTask] = []

        tasks = self._store.list_tasks(status="initializing")
        for task in tasks:
            if task.created_at < cutoff:
                try:
                    failed = self._store.fail_initialization(
                        task_id=task.task_id,
                        error_json={
                            "code": "stale_initialization",
                            "message": (
                                f"Task stuck in INITIALIZING since "
                                f"{task.created_at}; failed by startup "
                                f"reconciliation"
                            ),
                        },
                        now=now,
                    )
                    stale_tasks.append(failed)
                    logger.warning(
                        "Reconciled stale INITIALIZING task %s "
                        "(kind=%r, created_at=%s)",
                        task.task_id,
                        task.kind,
                        task.created_at,
                    )
                except Exception:
                    logger.exception(
                        "Failed to reconcile stale INITIALIZING task %s",
                        task.task_id,
                    )

        if stale_tasks:
            logger.info(
                "Reconciled %d stale INITIALIZING task(s)",
                len(stale_tasks),
            )

        return stale_tasks


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_task_runtime(
    db_path: str | Path,
    config: TaskWorkerConfig | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> TaskRuntime:
    """Create a fully wired :class:`TaskRuntime` instance.

    This is the recommended entry point for application code::

        runtime = create_task_runtime(
            db_path="memory/runtime/tasks.db",
            config=TaskWorkerConfig(
                worker_id="worker-1",
                tick_seconds=2,
                lease_seconds=120,
            ),
        )

    Args:
        db_path: Filesystem path to the SQLite database file.
        config: Worker configuration.  A default ``TaskWorkerConfig``
            is used when ``None``.
        clock: Injectable datetime source (defaults to ``datetime.now``).
        id_factory: Injectable ID generator (defaults to ``uuid4().hex``).

    Returns:
        A new ``TaskRuntime`` ready for handler registration and startup.
    """
    return TaskRuntime(
        db_path=db_path,
        config=config,
        clock=clock,
        id_factory=id_factory,
    )


# ---------------------------------------------------------------------------
# Handler setup
# ---------------------------------------------------------------------------


def _parse_path_mapping(raw: str) -> dict[str, str]:
    """Parse ``QB_PATH_MAPPING`` env var into a prefix translation dict.

    Format: ``"D:\\->/mnt/d/"``  (comma-separated pairs with ``->`` separator).
    Empty string returns an empty dict (translation disabled).
    """
    if not raw or not raw.strip():
        return {}
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "->" not in pair:
            logger.warning("Invalid QB_PATH_MAPPING entry (missing '->'): %r", pair)
            continue
        src, dst = pair.split("->", 1)
        src = src.strip()
        dst = dst.strip()
        if src and dst:
            mapping[src] = dst
    return mapping


def setup_download_watch_handler(
    runtime: TaskRuntime,
    qb_adapter: QBittorrentAdapter,
    config: DownloadWatchConfig,
    path_mapping: dict[str, str] | None = None,
) -> None:
    """Create and register the ``download_watch`` handler on *runtime*.

    Must be called **before** ``runtime.start()`` so the handler is
    registered before the worker loop begins dispatching tasks.

    Args:
        runtime: A :class:`TaskRuntime` instance (created via
            :func:`create_task_runtime`) that has not yet started.
        qb_adapter: Configured :class:`QBittorrentAdapter` instance for
            polling torrent status.
        config: :class:`DownloadWatchConfig` with polling interval, error
            backoff, and related settings.
        path_mapping: Optional dict mapping qB-reported path prefixes to
            local filesystem prefixes (e.g. ``{"D:\\": "/mnt/d/"}``).
            Read from ``QB_PATH_MAPPING`` env var if ``None``.

    Raises:
        ValueError: If ``download_watch`` is already registered on *runtime*.
    """
    if path_mapping is None:
        try:
            from app.config import get_settings
            path_mapping = _parse_path_mapping(get_settings().qb_path_mapping)
        except Exception:
            path_mapping = {}

    handler = DownloadWatchHandler(
        qb_adapter=qb_adapter,
        config=config,
        scheduler=runtime.scheduler,
        store=runtime.store,
        clock=runtime.clock,
        path_mapping=path_mapping,
    )
    runtime.register_handler("download_watch", handler)
    if path_mapping:
        logger.info(
            "download_watch handler registered (poll_seconds=%s, path_mapping=%s)",
            config.poll_seconds,
            path_mapping,
        )
    else:
        logger.info(
            "download_watch handler registered (poll_seconds=%s, error_backoff_max=%s)",
            config.poll_seconds,
            config.error_backoff_max,
        )


def setup_organize_download_handler(
    runtime: TaskRuntime,
    config: OrganizeDownloadConfig | None = None,
    organization_policy_store: Any | None = None,
) -> None:
    """Create and register the ``organize_download`` handler on *runtime*.

    Must be called **before** ``runtime.start()`` so the handler is
    registered before the worker loop begins dispatching tasks.

    When ``config.destination_root`` is empty, the handler attempts to
    derive it from the task payload or the organisation automation policy.

    Args:
        runtime: A :class:`TaskRuntime` instance (created via
            :func:`create_task_runtime`) that has not yet started.
        config: :class:`OrganizeDownloadConfig` with destination root,
            worker settings, and journal path.  A default config is used
            when ``None``.
        organization_policy_store: Optional store for reading the current
            organisation automation policy at execution time for policy
            revalidation.  Required for scheduled-check security.

    Raises:
        ValueError: If ``organize_download`` is already registered.
    """
    cfg = config or OrganizeDownloadConfig()

    # Resolve the policy store if not explicitly provided.
    if organization_policy_store is None:
        try:
            from app.services.organization_policy_store import (
                OrganizationAutomationPolicyStore,
            )
            settings_dir = Path(__file__).resolve().parents[1] / "memory" / "settings"
            organization_policy_store = OrganizationAutomationPolicyStore(settings_dir)
        except Exception:
            logger.warning(
                "Could not create organization policy store; "
                "policy revalidation will be skipped"
            )

    # If no destination_root is provided in the config, try to read it
    # from the organisation automation policy store.
    if not cfg.destination_root:
        try:
            if organization_policy_store is not None:
                policy = organization_policy_store.load()
                cfg.destination_root = policy.destination_root
        except Exception:
            logger.warning(
                "Could not read organization policy for destination_root; "
                "handler will derive it from task payload at runtime"
            )

    handler = OrganizeDownloadHandler(
        config=cfg,
        scheduler=runtime.scheduler,
        store=runtime.store,
        clock=runtime.clock,
        organization_policy_store=organization_policy_store,
    )
    runtime.register_handler("organize_download", handler)
    logger.info(
        "organize_download handler registered (destination_root=%s, worker_max_steps=%s)",
        cfg.destination_root or "(derived at runtime)",
        cfg.worker_max_steps,
    )
