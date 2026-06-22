"""Handler registry keyed by task kind.

Maps ``RuntimeTask.kind`` strings to async handler callables so the
dispatcher can look up the right handler for a claimed task without a
chain of ``if``/``elif`` branches.

Typical usage::

    registry = HandlerRegistry()
    registry.register("download_watch", handle_download_watch)
    registry.register("organize_download", handle_organize_download)

    handler = registry.get(task.kind)
    if handler is not None:
        outcome = await handler(task, store, scheduler)
"""

from __future__ import annotations

from typing import Awaitable, Callable

from app.domain.runtime_tasks import RuntimeTask, TaskOutcome
from app.runtime.scheduler import TaskScheduler
from app.runtime.store import RuntimeTaskStore

# ---------------------------------------------------------------------------
# Handler type alias
# ---------------------------------------------------------------------------

Handler = Callable[
    [RuntimeTask, RuntimeTaskStore, TaskScheduler],
    Awaitable[TaskOutcome],
]
"""Signature for a per-kind task handler.

Args:
    task: The claimed ``RuntimeTask`` to execute.
    store: The concrete ``RuntimeTaskStore`` for state transitions and
        event persistence.
    scheduler: The external-facing ``TaskScheduler`` for spawning child
        tasks.

Returns:
    A ``TaskOutcome`` discriminated union (``Complete``, ``Reschedule``,
    ``Fail``, or ``Spawn``).
"""

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class HandlerRegistry:
    """Dict-backed registry mapping task kind strings to async handlers.

    Thread-safety is the caller's responsibility (the registry is read
    from the dispatcher loop and written during application startup).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, kind: str, handler: Handler) -> None:
        """Register a handler for *kind*.

        Args:
            kind: The task kind string (e.g. ``"download_watch"``).
            handler: An async callable matching the ``Handler`` signature.

        Raises:
            ValueError: When *kind* is already registered.
        """
        if kind in self._handlers:
            raise ValueError(
                f"A handler is already registered for kind {kind!r}"
            )
        self._handlers[kind] = handler

    def get(self, kind: str) -> Handler | None:
        """Return the registered handler for *kind*, or ``None``.

        Args:
            kind: The task kind string to look up.
        """
        return self._handlers.get(kind)

    def list_kinds(self) -> list[str]:
        """Return all registered task kind strings in insertion order."""
        return list(self._handlers.keys())
