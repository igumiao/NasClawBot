"""External-facing seam over RuntimeTaskStore.

``TaskScheduler`` is a thin wrapper that exposes only the task-lifecycle
methods intended for callers outside the worker loop (routes, agents,
integration code).  It owns the mapping between the external vocabulary
(``payload``, ``error``) and the store's internal JSON-column parameter
names (``payload_json``, ``error_json``), and uses the injected ``clock``
and ``id_factory`` so callers never provide ``now`` or an ID generator.

Worker-facing methods (``claim_due``, ``reschedule``, ``finish``,
``record_run``, ``update_run``, event-management) are intentionally absent
from this class — they live on ``RuntimeTaskStore`` and are used only by
the dispatcher / worker loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.domain.runtime_tasks import RuntimeTask
from app.runtime.store import RuntimeTaskStore


class TaskScheduler:
    """External-facing seam over :class:`RuntimeTaskStore`.

    Wraps every public method with a cleaner external API:

    * ``payload`` / ``error`` / ``result`` (dict) instead of the store's
      ``payload_json`` / ``error_json`` / ``result_json`` parameter names.
    * ``now`` and ``id_factory`` are never exposed — the injected ``clock``
      and ``id_factory`` are used for every mutation.

    Does **not** expose worker-facing methods (``claim_due``, ``reschedule``,
    ``finish``, ``record_run``, ``update_run``, or any event-management
    methods).
    """

    def __init__(
        self,
        store: RuntimeTaskStore,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        """Initialise the scheduler.

        Args:
            store: The underlying :class:`RuntimeTaskStore` instance.
            clock: Callable returning the current ``datetime``, used as
                the authoritative time source for every mutation.
            id_factory: Callable returning a unique ``str``, used as the
                task ID generator for creation methods.
        """
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    # ------------------------------------------------------------------
    # External-facing task lifecycle
    # ------------------------------------------------------------------

    def prepare(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        source_session_id: str | None = None,
        parent_task_id: str | None = None,
        dedupe_key: str | None = None,
    ) -> RuntimeTask:
        """Create a task in ``INITIALIZING`` status.

        This is the crash-window reservation phase: the caller should
        confirm the external side effect (e.g. qB submission) and then
        call :meth:`activate`, or call :meth:`fail_initialization` if
        the side effect could not be completed.

        When *dedupe_key* is provided and a task with that key already
        exists, the existing task is returned unchanged (idempotent
        creation).

        Args:
            kind: Task kind discriminator (e.g. ``"download_watch"``).
            payload: Arbitrary JSON-serialisable invocation payload.
            source_session_id: Optional conversation session that
                originated this task.
            parent_task_id: Optional FK to the parent task.
            dedupe_key: Optional unique key for idempotent creation.

        Returns:
            The newly created (or existing, on dedupe match)
            ``RuntimeTask`` in ``INITIALIZING`` status.
        """
        return self._store.prepare(
            kind=kind,
            payload_json=payload,
            source_session_id=source_session_id,
            parent_task_id=parent_task_id,
            dedupe_key=dedupe_key,
            now=self._clock(),
            id_factory=self._id_factory,
        )

    def activate(
        self,
        task_id: str,
        payload_patch: dict[str, Any] | None = None,
        run_after: str | None = None,
    ) -> RuntimeTask:
        """Transition a task from ``INITIALIZING`` to ``QUEUED``.

        Called after the external side effect is confirmed.  Optionally
        merges *payload_patch* into the existing payload and sets the
        earliest claim eligibility via *run_after*.

        Args:
            task_id: The task to activate.
            payload_patch: Optional partial dict merged into the task
                payload.
            run_after: ISO-8601 datetime for the earliest claim time, or
                ``None`` for immediate eligibility.

        Returns:
            The updated task in ``QUEUED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        return self._store.activate(
            task_id=task_id,
            payload_patch=payload_patch,
            run_after=run_after,
            now=self._clock(),
        )

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        source_session_id: str | None = None,
        parent_task_id: str | None = None,
        dedupe_key: str | None = None,
        run_after: str | None = None,
    ) -> RuntimeTask:
        """Create a task directly in ``QUEUED`` status.

        Convenience shortcut that skips the ``INITIALIZING`` reservation
        phase.  Use :meth:`prepare` + :meth:`activate` when the external
        side effect needs a crash-window guard.

        When *dedupe_key* is provided and a task with that key already
        exists, the existing task is returned unchanged (idempotent
        creation).

        Args:
            kind: Task kind discriminator (e.g. ``"organize_download"``).
            payload: Arbitrary JSON-serialisable invocation payload.
            source_session_id: Optional conversation session that
                originated this task.
            parent_task_id: Optional FK to the parent task.
            dedupe_key: Optional unique key for idempotent creation.
            run_after: ISO-8601 datetime for the earliest claim time, or
                ``None`` for immediate eligibility.

        Returns:
            The newly created (or existing, on dedupe match) ``RuntimeTask``
            in ``QUEUED`` status.
        """
        return self._store.enqueue(
            kind=kind,
            payload_json=payload,
            source_session_id=source_session_id,
            parent_task_id=parent_task_id,
            dedupe_key=dedupe_key,
            run_after=run_after,
            now=self._clock(),
            id_factory=self._id_factory,
        )

    def fail_initialization(
        self,
        task_id: str,
        error: dict[str, Any] | None = None,
    ) -> RuntimeTask:
        """Transition a task from ``INITIALIZING`` to ``FAILED``.

        Used when the external side effect fails before the task could be
        activated.  Idempotent on already-terminal tasks.

        Args:
            task_id: The task to fail.
            error: Structured error details (e.g. ``{"code": "...",
                "message": "..."}``).

        Returns:
            The updated task in ``FAILED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        return self._store.fail_initialization(
            task_id=task_id,
            error_json=error,
            now=self._clock(),
        )

    def cancel(
        self,
        task_id: str,
    ) -> RuntimeTask:
        """Cancel a task from any non-terminal status.

        Idempotent on already-terminal tasks.  Clears any lease held on
        the task.

        Args:
            task_id: The task to cancel.

        Returns:
            The updated task in ``CANCELLED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        return self._store.cancel(
            task_id=task_id,
            now=self._clock(),
        )

    def get(
        self,
        task_id: str,
    ) -> RuntimeTask | None:
        """Fetch a single task by its ID.

        Args:
            task_id: The task to fetch.

        Returns:
            The ``RuntimeTask``, or ``None`` when not found.
        """
        return self._store.get(task_id=task_id)
