"""In-process task worker loop.

Claims due tasks from RuntimeTaskStore, dispatches them to registered
handlers, and applies outcomes (Complete / Reschedule / Fail / Spawn) back
to the store.  Runs in the same event loop as FastAPI (started via lifespan).

V1 concurrency defaults:

* ``organize_download``: 1 (serial)
* ``download_watch``: 4

These are configured via ``TaskWorkerConfig.per_kind_semaphores``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from app.domain.runtime_tasks import (
    ChildTaskSpec,
    Complete,
    Fail,
    Reschedule,
    RuntimeTask,
    Spawn,
    TaskEvent,
    TaskEventSeverity,
    TaskOutcome,
    TaskStatus,
    WorkerRun,
    is_terminal,
)
from app.runtime.registry import HandlerRegistry
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class TaskWorkerConfig:
    """Configuration for the :class:`TaskWorker` loop.

    Attributes:
        tick_seconds: Interval (in seconds) between claim polls.
        lease_seconds: Duration (in seconds) for each claimed task's lease.
        max_concurrency: Global limit on in-flight handler executions.
        per_kind_semaphores: Per-kind concurrency limits; unlisted kinds
            default to 1 (serial execution).
        clock: Callable returning the current ``datetime``.  Inject a
            deterministic implementation in tests.
        worker_id: Unique identifier for this worker instance, used as
            ``lease_owner`` when claiming tasks.
    """

    tick_seconds: int = 2
    lease_seconds: int = 120
    max_concurrency: int = 4
    per_kind_semaphores: dict[str, int] = field(default_factory=dict)
    clock: Callable[[], datetime] = datetime.now
    worker_id: str = "worker-1"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class TaskWorker:
    """In-process async worker that orchestrates the task lifecycle.

    Owns a main ``run()`` coroutine intended to be started as an asyncio
    Task during the FastAPI lifespan.  Graceful shutdown is signalled via
    ``stop()``.

    Concurrency is controlled at two levels:

    * A **global semaphore** (``max_concurrency``) limits total in-flight
      handlers across all task kinds.
    * **Per-kind semaphores** (``per_kind_semaphores``) limit concurrent
      handlers for the same task kind.  Kinds not explicitly configured
      default to serial execution (1 concurrent).
    """

    def __init__(
        self,
        store: RuntimeTaskStore,
        registry: HandlerRegistry,
        config: TaskWorkerConfig,
    ) -> None:
        self._store = store
        self._registry = registry
        self._config = config
        self._stop_event = asyncio.Event()
        self._global_sem = asyncio.Semaphore(config.max_concurrency)
        # Lazy-created per-kind semaphores: kind -> asyncio.Semaphore
        self._kind_sems: dict[str, asyncio.Semaphore] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main worker loop.

        Every ``tick_seconds``, claims due tasks and spawns handler
        coroutines.  Returns when ``stop()`` is called and all in-flight
        handlers have completed.
        """
        logger.info(
            "TaskWorker started (tick=%ds, lease=%ds, max_concurrency=%d, "
            "worker=%s)",
            self._config.tick_seconds,
            self._config.lease_seconds,
            self._config.max_concurrency,
            self._config.worker_id,
        )

        while not self._stop_event.is_set():
            await self._tick()

            # Wait for the next tick interval or until stop is signalled.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.tick_seconds,
                )
                break
            except asyncio.TimeoutError:
                continue

        logger.info("TaskWorker main loop exited")

    async def stop(self) -> None:
        """Signal graceful shutdown.

        Sets the stop event so the next poll exits the loop.  In-flight
        handlers run to completion; the caller should give the worker a
        short grace period before cancelling the run task.
        """
        logger.info("TaskWorker stop requested")
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        """One claim-and-dispatch cycle."""
        try:
            now = self._config.clock()

            # Purge terminal tasks older than 60 seconds.
            try:
                purged = self._store.purge_terminal_tasks(
                    now, max_age_seconds=60,
                )
                if purged:
                    logger.info("Purged %d terminal task(s)", purged)
            except Exception:
                logger.warning("Failed to purge terminal tasks", exc_info=True)

            kinds = self._registry.list_kinds()
            if not kinds:
                return

            tasks = self._store.claim_due(
                kinds=kinds,
                limit=self._config.max_concurrency,
                lease_owner=self._config.worker_id,
                lease_seconds=self._config.lease_seconds,
                now=now,
            )
        except Exception:
            logger.exception("Error claiming due tasks")
            return

        for task in tasks:
            logger.info(
                "Claimed task %s kind=%r attempt=%d",
                task.task_id,
                task.kind,
                task.attempts,
            )
            asyncio.ensure_future(self._execute_with_semaphores(task))

    # ------------------------------------------------------------------
    # Concurrency control
    # ------------------------------------------------------------------

    async def _execute_with_semaphores(self, task: RuntimeTask) -> None:
        """Acquire per-kind and global semaphores, then run the handler."""
        kind_sem = self._kind_semaphore(task.kind)
        async with kind_sem:
            async with self._global_sem:
                await self._execute(task)

    def _kind_semaphore(self, kind: str) -> asyncio.Semaphore:
        """Return the per-kind semaphore for *kind*, created lazily.

        Kinds not present in ``per_kind_semaphores`` default to a limit of
        1 (serial execution).
        """
        if kind not in self._kind_sems:
            max_conc = self._config.per_kind_semaphores.get(kind, 1)
            self._kind_sems[kind] = asyncio.Semaphore(max_conc)
        return self._kind_sems[kind]

    # ------------------------------------------------------------------
    # Single task execution
    # ------------------------------------------------------------------

    async def _execute(self, task: RuntimeTask) -> None:
        """Run the registered handler for *task* and apply its outcome."""
        task_id = task.task_id
        kind = task.kind
        attempt = task.attempts
        start_time = time.monotonic()

        # Look up the handler.
        handler = self._registry.get(kind)
        if handler is None:
            logger.warning("No handler registered for kind %r (task %s)", kind, task_id)
            self._store.finish(
                task_id=task_id,
                status=TaskStatus.FAILED,
                result_json=None,
                error_json={
                    "code": "NO_HANDLER",
                    "message": f"No handler registered for task kind {kind!r}",
                },
                now=self._config.clock(),
            )
            return

        # Record the WorkerRun for this attempt.
        run_id = uuid.uuid4().hex
        now = self._config.clock()
        run = WorkerRun(
            run_id=run_id,
            task_id=task_id,
            attempt=attempt,
            status=TaskStatus.RUNNING,
            started_at=now.isoformat(),
        )
        try:
            self._store.record_run(run)
        except Exception:
            logger.exception("Failed to persist WorkerRun for task %s", task_id)
            # Continue execution -- the run record is best-effort for V1.

        # Build a scheduler so the handler can spawn child tasks.
        scheduler = TaskScheduler(
            store=self._store,
            clock=self._config.clock,
            id_factory=lambda: uuid.uuid4().hex,
        )

        # TODO(V2): Start a background asyncio task to periodically extend
        # the lease for long-running handlers.  Requires a ``renew_lease``
        # method on RuntimeTaskStore.

        try:
            outcome = await handler(task, self._store, scheduler)
        except asyncio.CancelledError:
            logger.warning("Handler for task %s was cancelled", task_id)
            outcome = Fail(
                code="CANCELLED",
                message="Handler was cancelled during shutdown",
                retryable=False,
            )
        except Exception as exc:
            logger.exception(
                "Handler for task %s (kind=%r) raised exception",
                task_id,
                kind,
            )
            outcome = Fail(
                code="HANDLER_EXCEPTION",
                message=str(exc),
                retryable=True,
            )

        duration = time.monotonic() - start_time

        logger.info(
            "Handler finished task=%s kind=%r attempt=%d duration=%.2fs "
            "outcome=%s",
            task_id,
            kind,
            attempt,
            duration,
            outcome.kind,
        )

        # Apply the outcome to the store.
        try:
            self._apply_outcome(task, outcome, run_id, now)
        except Exception:
            logger.exception(
                "Failed to apply outcome %r for task %s",
                outcome.kind,
                task_id,
            )

    # ------------------------------------------------------------------
    # Outcome application
    # ------------------------------------------------------------------

    def _apply_outcome(
        self,
        task: RuntimeTask,
        outcome: TaskOutcome,
        run_id: str,
        now: datetime,
    ) -> None:
        """Persist the outcome to the store and update the WorkerRun."""
        match outcome.kind:
            case "complete":
                self._on_complete(task, outcome, run_id, now)
            case "reschedule":
                self._on_reschedule(task, outcome, now)
            case "fail":
                self._on_fail(task, outcome, run_id, now)
            case "spawn":
                self._on_spawn(task, outcome, run_id, now)

    # -- individual outcome handlers --------------------------------

    def _on_complete(
        self,
        task: RuntimeTask,
        outcome: Complete,
        run_id: str,
        now: datetime,
    ) -> None:
        """Transition to SUCCEEDED and publish events."""
        self._create_events(task, outcome.events, now)

        self._store.finish(
            task_id=task.task_id,
            status=TaskStatus.SUCCEEDED,
            result_json=outcome.result,
            error_json=None,
            now=now,
        )
        self._update_run(run_id, TaskStatus.SUCCEEDED, now, result=outcome.result)

    def _on_reschedule(
        self,
        task: RuntimeTask,
        outcome: Reschedule,
        now: datetime,
    ) -> None:
        """Transition to WAITING with a new ``run_after``."""
        self._store.reschedule(
            task_id=task.task_id,
            run_after=outcome.run_after,
            payload_patch=outcome.payload_patch or None,
            now=now,
        )

    def _on_fail(
        self,
        task: RuntimeTask,
        outcome: Fail,
        run_id: str,
        now: datetime,
    ) -> None:
        """Transition to FAILED, or reschedule with backoff if retryable."""
        error_json: dict[str, Any] = {
            "code": outcome.code,
            "message": outcome.message,
            "details": outcome.details,
        }

        if outcome.retryable and task.attempts < task.max_attempts:
            # Exponential backoff: 30s, 60s, 120s, ... capped at 3600s.
            delay = min(30 * (2 ** (task.attempts - 1)), 3600)
            run_after = (
                now.replace(microsecond=0) + timedelta(seconds=delay)
            ).isoformat()

            logger.info(
                "Rescheduling task %s after %ds (attempt %d/%d)",
                task.task_id,
                delay,
                task.attempts,
                task.max_attempts,
            )

            self._store.reschedule(
                task_id=task.task_id,
                run_after=run_after,
                payload_patch={
                    "_last_error": error_json,
                    "_last_retry_at": now.isoformat(),
                },
                now=now,
            )
            return

        logger.info(
            "Failing task %s (attempt %d/%d, retryable=%s)",
            task.task_id,
            task.attempts,
            task.max_attempts,
            outcome.retryable,
        )

        self._create_events(
            task,
            [
                {
                    "kind": "task_failed",
                    "severity": TaskEventSeverity.ERROR,
                    "title": "任务失败",
                    "summary": outcome.message,
                    "payload": error_json,
                }
            ],
            now,
        )

        self._store.finish(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            result_json=None,
            error_json=error_json,
            now=now,
        )
        self._update_run(run_id, TaskStatus.FAILED, now, error=error_json)

    def _on_spawn(
        self,
        task: RuntimeTask,
        outcome: Spawn,
        run_id: str,
        now: datetime,
    ) -> None:
        """Create child tasks and transition parent to SUCCEEDED."""
        self._spawn_children(task, outcome.children, now)
        self._create_events(task, outcome.events, now)

        self._store.finish(
            task_id=task.task_id,
            status=TaskStatus.SUCCEEDED,
            result_json=outcome.result,
            error_json=None,
            now=now,
        )
        self._update_run(run_id, TaskStatus.SUCCEEDED, now, result=outcome.result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_run(
        self,
        run_id: str,
        status: TaskStatus,
        now: datetime,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Update the WorkerRun with a terminal status (best-effort)."""
        try:
            self._store.update_run(
                run_id=run_id,
                status=status,
                result_json=result,
                error_json=error,
                now=now,
            )
        except Exception:
            logger.exception("Failed to update WorkerRun %s", run_id)

    def _create_events(
        self,
        task: RuntimeTask,
        event_dicts: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        """Persist TaskEvent objects from outcome event dicts (best-effort)."""
        if not event_dicts:
            return

        now_iso = now.isoformat()

        for ed in event_dicts:
            severity = ed.get("severity", TaskEventSeverity.INFO)
            if isinstance(severity, str):
                try:
                    severity = TaskEventSeverity(severity)
                except ValueError:
                    severity = TaskEventSeverity.INFO

            event = TaskEvent(
                event_id=uuid.uuid4().hex,
                task_id=task.task_id,
                source_session_id=task.source_session_id,
                kind=ed.get("kind", "unknown"),
                severity=severity,
                title=ed.get("title", ""),
                summary=ed.get("summary", ""),
                payload=ed.get("payload"),
                created_at=now_iso,
            )
            try:
                self._store.create_event(event)
            except Exception:
                logger.exception(
                    "Failed to persist event for task %s", task.task_id
                )

    def _spawn_children(
        self,
        parent: RuntimeTask,
        children: list[ChildTaskSpec],
        now: datetime,
    ) -> None:
        """Enqueue child tasks via the store (best-effort per child)."""
        for spec in children:
            try:
                self._store.enqueue(
                    kind=spec.kind,
                    payload_json=spec.payload,
                    source_session_id=parent.source_session_id,
                    parent_task_id=parent.task_id,
                    dedupe_key=spec.dedupe_key,
                    run_after=spec.run_after,
                    now=now,
                    id_factory=lambda: uuid.uuid4().hex,
                )
            except Exception:
                logger.exception(
                    "Failed to enqueue child task kind=%r for parent %s",
                    spec.kind,
                    parent.task_id,
                )
