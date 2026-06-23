"""Concrete SQLite store for runtime_tasks, runtime_task_runs, and runtime_task_events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.domain.runtime_tasks import (
    RuntimeTask,
    TaskEvent,
    TaskEventSeverity,
    TaskStatus,
    WorkerRun,
    is_terminal,
    validate_status_transition,
)
from app.storage.db import connect


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> str | None:
    """Serialize *value* to a JSON string, or return None for None inputs."""
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _parse_task(row: sqlite3.Row) -> RuntimeTask:
    """Convert a SQLite row to a RuntimeTask, parsing JSON columns."""
    d = dict(row)
    for col in ("payload_json", "result_json", "error_json"):
        if d.get(col) is not None:
            d[col] = json.loads(d[col])
    return RuntimeTask.model_validate_sql(d)


def _parse_run(row: sqlite3.Row) -> WorkerRun:
    """Convert a SQLite row to a WorkerRun, parsing JSON columns."""
    d = dict(row)
    for col in ("handoff_json", "history_json", "result_json", "error_json"):
        if d.get(col) is not None:
            d[col] = json.loads(d[col])
    return WorkerRun.model_validate_sql(d)


def _parse_event(row: sqlite3.Row) -> TaskEvent:
    """Convert a SQLite row to a TaskEvent, parsing JSON columns."""
    d = dict(row)
    if d.get("payload_json") is not None:
        d["payload_json"] = json.loads(d["payload_json"])
    return TaskEvent.model_validate_sql(d)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class RuntimeTaskStore:
    """Concrete SQLite store for the runtime task persistence layer.

    Manages three tables:
    - ``runtime_tasks``        — durable business-work items
    - ``runtime_task_runs``    — per-attempt execution records
    - ``runtime_task_events``  — user-visible notifications

    Every public method opens one short-lived connection, performs its work,
    and closes the connection before returning.  State transitions are
    validated against :func:`validate_status_transition` before persisting.
    Terminal transitions are idempotent.  Concurrent-safe claim is achieved
    via ``BEGIN IMMEDIATE``.

    Inject *clock* (a callable returning the current ``datetime``) and
    *id_factory* (a callable returning a unique ``str``) via the constructor
    so tests can replace them with deterministic implementations.
    """

    def __init__(
        self,
        db_path: str | Path,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        """Store initialisation.

        Args:
            db_path: Filesystem path to the SQLite database file.
            clock: Callable returning the current ``datetime`` (used as the
                authoritative time source when a caller does not provide
                ``now``).
            id_factory: Callable returning a unique ``str`` (used as a
                default ID generator when a caller does not provide an
                ``id_factory``).
        """
        self._db_path = Path(db_path)
        self._clock = clock
        self._id_factory = id_factory

    # ------------------------------------------------------------------
    # Internal worker-facing methods
    # ------------------------------------------------------------------

    def claim_due(
        self,
        kinds: list[str],
        limit: int,
        lease_owner: str,
        lease_seconds: int,
        now: datetime,
    ) -> list[RuntimeTask]:
        """Atomically claim up to *limit* due tasks matching *kinds*.

        Uses ``BEGIN IMMEDIATE`` to prevent concurrent claim races.
        Selected tasks transition from ``QUEUED`` / ``WAITING`` to
        ``RUNNING`` with a lease held by *lease_owner* that expires after
        *lease_seconds*.  Tasks whose ``run_after`` is in the future are
        skipped.

        Args:
            kinds: Task kind strings to match (e.g. ``["download_watch"]``).
            limit: Maximum number of tasks to claim.
            lease_owner: Identifier for the worker claiming these tasks.
            lease_seconds: Lease duration in seconds.
            now: Current timestamp used for all time comparisons and writes.

        Returns:
            The claimed tasks in ``RUNNING`` status with lease fields set.
        """
        if not kinds or limit < 1:
            return []

        now_iso = now.isoformat()
        lease_expires_iso = (now.replace(microsecond=0) + timedelta(seconds=lease_seconds)).isoformat()
        placeholders = ",".join("?" for _ in kinds)

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            rows = conn.execute(
                f"SELECT * FROM runtime_tasks "
                f"WHERE status IN ('queued', 'waiting') "
                f"AND (run_after IS NULL OR run_after <= ?) "
                f"AND kind IN ({placeholders}) "
                f"ORDER BY run_after ASC NULLS FIRST, created_at ASC "
                f"LIMIT ?",
                (now_iso, *kinds, limit),
            ).fetchall()

            if rows:
                updates = [
                    (
                        lease_owner,
                        lease_expires_iso,
                        now_iso,
                        now_iso,
                        r["task_id"],
                    )
                    for r in rows
                ]
                conn.executemany(
                    "UPDATE runtime_tasks SET "
                    "status = 'running', "
                    "lease_owner = ?, "
                    "lease_expires_at = ?, "
                    "started_at = COALESCE(started_at, ?), "
                    "updated_at = ?, "
                    "attempts = attempts + 1 "
                    "WHERE task_id = ?",
                    updates,
                )

            conn.commit()

            # Build result objects with updated status fields.
            tasks: list[RuntimeTask] = []
            for r in rows:
                d = dict(r)
                d["status"] = TaskStatus.RUNNING.value
                d["lease_owner"] = lease_owner
                d["lease_expires_at"] = lease_expires_iso
                d["started_at"] = d.get("started_at") or now_iso
                d["updated_at"] = now_iso
                d["attempts"] = d.get("attempts", 0) + 1
                for col in ("payload_json", "result_json", "error_json"):
                    if d.get(col) is not None:
                        d[col] = json.loads(d[col])
                tasks.append(RuntimeTask.model_validate_sql(d))

            return tasks
        finally:
            conn.close()

    def reschedule(
        self,
        task_id: str,
        run_after: str,
        payload_patch: dict[str, Any] | None,
        now: datetime,
        failure_count: int | None = None,
    ) -> RuntimeTask:
        """Reschedule a ``RUNNING`` task back to ``WAITING``.

        Updates the task's ``run_after`` timestamp for the next eligible
        claim and optionally merges *payload_patch* into the existing
        payload.  The lease is cleared so another worker may claim the task.

        Args:
            task_id: The task to reschedule.
            run_after: ISO-8601 datetime for the next claim eligibility.
            payload_patch: Optional partial dict merged into the task payload.
            now: Current timestamp.
            failure_count: Optional explicit failure counter (updated when
                the worker is processing a ``Fail`` outcome).

        Returns:
            The updated task in ``WAITING`` status.

        Raises:
            ValueError: If the task does not exist or the status transition
                is not permitted.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id!r} not found")

            current = _parse_task(row)

            # Idempotent: already WAITING
            if current.status == TaskStatus.WAITING:
                conn.commit()
                return current

            validate_status_transition(current.status, TaskStatus.WAITING)

            new_payload = current.payload or {}
            if payload_patch:
                new_payload.update(payload_patch)

            set_clauses = [
                "status = 'waiting'",
                "run_after = ?",
                "payload_json = ?",
                "updated_at = ?",
                "lease_owner = NULL",
                "lease_expires_at = NULL",
            ]
            params = [run_after, _d(new_payload), now_iso]

            if failure_count is not None:
                set_clauses.append("failure_count = ?")
                params.append(failure_count)

            params.append(task_id)
            conn.execute(
                f"UPDATE runtime_tasks SET {', '.join(set_clauses)} "
                f"WHERE task_id = ?",
                params,
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row)
        finally:
            conn.close()

    def finish(
        self,
        task_id: str,
        status: TaskStatus,
        result_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
        now: datetime,
        failure_count: int | None = None,
    ) -> RuntimeTask:
        """Transition a task to a terminal status (``SUCCEEDED`` or ``FAILED``).

        Idempotent: calling ``finish`` on an already-terminal task returns
        the existing row without changes.

        Args:
            task_id: The task to complete.
            status: Target terminal status.
            result_json: Structured result (set on ``SUCCEEDED``).
            error_json: Structured error details (set on ``FAILED``).
            now: Current timestamp.
            failure_count: Optional explicit failure counter (set on
                ``FAILED`` when the worker processes a ``Fail`` outcome).

        Returns:
            The updated task in the terminal status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id!r} not found")

            current = _parse_task(row)

            # Idempotent: terminal states do not transition.
            if is_terminal(current.status):
                conn.commit()
                return current

            validate_status_transition(current.status, status)

            set_clauses = [
                "status = ?",
                "result_json = ?",
                "error_json = ?",
                "updated_at = ?",
                "completed_at = ?",
                "lease_owner = NULL",
                "lease_expires_at = NULL",
            ]
            params = [
                status.value,
                _d(result_json),
                _d(error_json),
                now_iso,
                now_iso,
            ]

            if failure_count is not None:
                set_clauses.append("failure_count = ?")
                params.append(failure_count)

            params.append(task_id)
            conn.execute(
                f"UPDATE runtime_tasks SET {', '.join(set_clauses)} "
                f"WHERE task_id = ?",
                params,
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row)
        finally:
            conn.close()

    def record_run(self, run: WorkerRun) -> WorkerRun:
        """Persist a new ``WorkerRun`` for a task attempt.

        Args:
            run: The ``WorkerRun`` instance to insert (must have a unique
                ``run_id``).

        Returns:
            The same ``WorkerRun`` instance (now persisted).
        """
        conn = connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO runtime_task_runs "
                "(run_id, task_id, attempt, status, handoff_json, history_json, "
                "result_json, error_json, started_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.task_id,
                    run.attempt,
                    run.status.value,
                    _d(run.handoff),
                    _d(run.history),
                    _d(run.result),
                    _d(run.error),
                    run.started_at,
                    run.completed_at,
                ),
            )
            conn.commit()
            return run
        finally:
            conn.close()

    def update_run(
        self,
        run_id: str,
        status: TaskStatus,
        result_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
        now: datetime,
    ) -> WorkerRun:
        """Update a ``WorkerRun`` with terminal fields.

        Sets ``completed_at`` only when *status* is terminal.

        Args:
            run_id: The run to update.
            status: New run status.
            result_json: Structured result data.
            error_json: Structured error data.
            now: Current timestamp.

        Returns:
            The updated ``WorkerRun``.

        Raises:
            ValueError: If the run does not exist.
        """
        now_iso = now.isoformat()
        completed_at = now_iso if is_terminal(status) else None

        conn = connect(self._db_path)
        try:
            conn.execute(
                "UPDATE runtime_task_runs SET "
                "status = ?, "
                "result_json = ?, "
                "error_json = ?, "
                "completed_at = COALESCE(completed_at, ?) "
                "WHERE run_id = ?",
                (
                    status.value,
                    _d(result_json),
                    _d(error_json),
                    completed_at,
                    run_id,
                ),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_task_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"WorkerRun {run_id!r} not found")
            return _parse_run(row)
        finally:
            conn.close()

    def create_event(self, event: TaskEvent) -> TaskEvent:
        """Persist a new ``TaskEvent``.

        Args:
            event: The ``TaskEvent`` instance to insert (must have a unique
                ``event_id``).

        Returns:
            The same ``TaskEvent`` instance (now persisted).
        """
        conn = connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO runtime_task_events "
                "(event_id, task_id, source_session_id, kind, severity, "
                "title, summary, payload_json, created_at, acknowledged_at, "
                "injected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.task_id,
                    event.source_session_id,
                    event.kind,
                    event.severity.value,
                    event.title,
                    event.summary,
                    _d(event.payload),
                    event.created_at,
                    event.acknowledged_at,
                    event.injected_at,
                ),
            )
            conn.commit()
            return event
        finally:
            conn.close()

    def get_events_for_session(
        self,
        source_session_id: str,
        uninjected_only: bool = False,
    ) -> list[TaskEvent]:
        """Fetch events scoped to a conversation session.

        Args:
            source_session_id: The session ID to scope results to.
            uninjected_only: When ``True``, only return events whose
                ``injected_at`` is ``NULL``.

        Returns:
            Chronologically descending list of matching events.
        """
        query = (
            "SELECT * FROM runtime_task_events "
            "WHERE source_session_id = ?"
        )
        if uninjected_only:
            query += " AND injected_at IS NULL"
        query += " ORDER BY created_at DESC"

        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(query, (source_session_id,)).fetchall()
            return [_parse_event(r) for r in rows]

    def mark_events_injected(self, event_ids: list[str], now: datetime) -> None:
        """Set ``injected_at`` for the listed events.

        No-op when *event_ids* is empty.

        Args:
            event_ids: Event IDs to mark as injected.
            now: Timestamp to write as the injection time.
        """
        if not event_ids:
            return

        now_iso = now.isoformat()
        placeholders = ",".join("?" for _ in event_ids)

        conn = connect(self._db_path)
        try:
            conn.execute(
                f"UPDATE runtime_task_events SET injected_at = ? "
                f"WHERE event_id IN ({placeholders})",
                (now_iso, *event_ids),
            )
            conn.commit()
        finally:
            conn.close()

    def acknowledge_event(
        self,
        event_id: str,
        now: datetime,
    ) -> TaskEvent:
        """Mark an event as acknowledged (seen by the user).

        Args:
            event_id: The event to acknowledge.
            now: Timestamp to write as the acknowledgement time.

        Returns:
            The updated ``TaskEvent``.

        Raises:
            ValueError: If the event does not exist.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute(
                "UPDATE runtime_task_events SET acknowledged_at = ? "
                "WHERE event_id = ?",
                (now_iso, event_id),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_task_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"TaskEvent {event_id!r} not found")
            return _parse_event(row)
        finally:
            conn.close()

    def list_events(
        self,
        after: str | None = None,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[TaskEvent]:
        """List events with cursor-based pagination and optional filters.

        Results are ordered newest-first by ``created_at``.

        Args:
            after: ISO-8601 cursor; only events with ``created_at``
                earlier (older) than this value are returned.
            limit: Maximum number of events to return.
            filters: Optional dict with zero or more of:
                ``kind``, ``severity``, ``source_session_id``.

        Returns:
            Chronologically descending list of matching events.
        """
        filters = filters or {}
        query = "SELECT * FROM runtime_task_events WHERE 1=1"
        params: list[Any] = []

        if after is not None:
            query += " AND created_at < ?"
            params.append(after)
        if "kind" in filters:
            query += " AND kind = ?"
            params.append(filters["kind"])
        if "severity" in filters:
            raw = filters["severity"]
            params.append(raw.value if isinstance(raw, TaskEventSeverity) else raw)
            query += " AND severity = ?"
        if "source_session_id" in filters:
            query += " AND source_session_id = ?"
            params.append(filters["source_session_id"])
        if "acknowledged" in filters:
            ack = filters["acknowledged"]
            if ack is True:
                query += " AND acknowledged_at IS NOT NULL"
            elif ack is False:
                query += " AND acknowledged_at IS NULL"

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
            return [_parse_event(r) for r in rows]

    # ------------------------------------------------------------------
    # External-facing methods
    # ------------------------------------------------------------------

    def prepare(
        self,
        kind: str,
        payload_json: dict[str, Any] | None,
        source_session_id: str | None,
        parent_task_id: str | None,
        dedupe_key: str | None,
        now: datetime,
        id_factory: Callable[[], str],
    ) -> RuntimeTask:
        """Create a task in ``INITIALIZING`` status.

        ``INITIALIZING`` serves as a crash-window reservation: the external
        side effect (e.g. qB submission) has not yet been confirmed.  The
        caller must call :meth:`activate` after confirming the side effect,
        or :meth:`fail_initialization` if it failed.

        When *dedupe_key* is provided, ``INSERT OR IGNORE`` + ``SELECT`` is
        used so that a duplicate key returns the existing row unchanged.

        Args:
            kind: Task kind discriminator.
            payload_json: Arbitrary JSON-serialisable invocation payload.
            source_session_id: Optional conversation session that originated
                this task.
            parent_task_id: Optional FK to the parent task.
            dedupe_key: Optional unique key for idempotent creation.
            now: Current timestamp.
            id_factory: Callable producing a unique task ID.

        Returns:
            The newly created (or existing, on dedupe match) ``RuntimeTask``.
        """
        task_id = id_factory()
        now_iso = now.isoformat()
        payload = payload_json or {}

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                "INSERT OR IGNORE INTO runtime_tasks "
                "(task_id, kind, status, payload_json, run_after, "
                "parent_task_id, source_session_id, dedupe_key, "
                "created_at, updated_at) "
                "VALUES (?, ?, 'initializing', ?, NULL, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    kind,
                    _d(payload),
                    parent_task_id,
                    source_session_id,
                    dedupe_key,
                    now_iso,
                    now_iso,
                ),
            )

            if dedupe_key is not None:
                row = conn.execute(
                    "SELECT * FROM runtime_tasks WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM runtime_tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()

            conn.commit()
            return _parse_task(row)
        finally:
            conn.close()

    def activate(
        self,
        task_id: str,
        payload_patch: dict[str, Any] | None,
        run_after: str | None,
        now: datetime,
    ) -> RuntimeTask:
        """Transition a task from ``INITIALIZING`` to ``QUEUED``.

        Called after the external side effect (e.g. qB submission) is
        confirmed.  Optionally merges *payload_patch* into the existing
        payload and sets the earliest claim eligibility via *run_after*.

        Args:
            task_id: The task to activate.
            payload_patch: Optional partial dict merged into the task payload.
            run_after: ISO-8601 datetime for the earliest claim time, or
                ``None`` for immediate eligibility.
            now: Current timestamp.

        Returns:
            The updated task in ``QUEUED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id!r} not found")

            current = _parse_task(row)
            validate_status_transition(current.status, TaskStatus.QUEUED)

            new_payload = current.payload or {}
            if payload_patch:
                new_payload.update(payload_patch)

            conn.execute(
                "UPDATE runtime_tasks SET "
                "status = 'queued', "
                "payload_json = ?, "
                "run_after = ?, "
                "updated_at = ? "
                "WHERE task_id = ?",
                (
                    _d(new_payload),
                    run_after,
                    now_iso,
                    task_id,
                ),
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row)
        finally:
            conn.close()

    def enqueue(
        self,
        kind: str,
        payload_json: dict[str, Any] | None,
        source_session_id: str | None,
        parent_task_id: str | None,
        dedupe_key: str | None,
        run_after: str | None,
        now: datetime,
        id_factory: Callable[[], str],
    ) -> RuntimeTask:
        """Create a task directly in ``QUEUED`` status.

        This is a convenience shortcut that skips the ``INITIALIZING``
        reservation phase.  Use :meth:`prepare` + :meth:`activate` when the
        external side effect needs a crash-window guard.

        When *dedupe_key* is provided, ``INSERT OR IGNORE`` + ``SELECT`` is
        used so that a duplicate key returns the existing row unchanged.

        Args:
            kind: Task kind discriminator.
            payload_json: Arbitrary JSON-serialisable invocation payload.
            source_session_id: Optional conversation session that originated
                this task.
            parent_task_id: Optional FK to the parent task.
            dedupe_key: Optional unique key for idempotent creation.
            run_after: ISO-8601 datetime for the earliest claim time, or
                ``None`` for immediate eligibility.
            now: Current timestamp.
            id_factory: Callable producing a unique task ID.

        Returns:
            The newly created (or existing, on dedupe match) ``RuntimeTask``.
        """
        task_id = id_factory()
        now_iso = now.isoformat()
        payload = payload_json or {}

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                "INSERT OR IGNORE INTO runtime_tasks "
                "(task_id, kind, status, payload_json, run_after, "
                "parent_task_id, source_session_id, dedupe_key, "
                "created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    kind,
                    _d(payload),
                    run_after,
                    parent_task_id,
                    source_session_id,
                    dedupe_key,
                    now_iso,
                    now_iso,
                ),
            )

            if dedupe_key is not None:
                row = conn.execute(
                    "SELECT * FROM runtime_tasks WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM runtime_tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()

            conn.commit()
            return _parse_task(row)
        finally:
            conn.close()

    def fail_initialization(
        self,
        task_id: str,
        error_json: dict[str, Any] | None,
        now: datetime,
    ) -> RuntimeTask:
        """Transition a task from ``INITIALIZING`` to ``FAILED``.

        Used when the external side effect fails before the task could be
        activated.  Idempotent on already-terminal tasks.

        Args:
            task_id: The task to fail.
            error_json: Structured error details.
            now: Current timestamp.

        Returns:
            The updated task in ``FAILED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id!r} not found")

            current = _parse_task(row)

            if is_terminal(current.status):
                conn.commit()
                return current

            validate_status_transition(current.status, TaskStatus.FAILED)

            conn.execute(
                "UPDATE runtime_tasks SET "
                "status = 'failed', "
                "error_json = ?, "
                "updated_at = ?, "
                "completed_at = ? "
                "WHERE task_id = ?",
                (
                    _d(error_json),
                    now_iso,
                    now_iso,
                    task_id,
                ),
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row)
        finally:
            conn.close()

    def cancel(
        self,
        task_id: str,
        now: datetime,
    ) -> RuntimeTask:
        """Cancel a task from any non-terminal status.

        Idempotent on already-terminal tasks.  Clears any lease held on the
        task.

        Args:
            task_id: The task to cancel.
            now: Current timestamp.

        Returns:
            The updated task in ``CANCELLED`` status.

        Raises:
            ValueError: If the task does not exist or the transition is
                not permitted.
        """
        now_iso = now.isoformat()

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id!r} not found")

            current = _parse_task(row)

            if is_terminal(current.status):
                conn.commit()
                return current

            validate_status_transition(current.status, TaskStatus.CANCELLED)

            conn.execute(
                "UPDATE runtime_tasks SET "
                "status = 'cancelled', "
                "updated_at = ?, "
                "completed_at = ?, "
                "lease_owner = NULL, "
                "lease_expires_at = NULL "
                "WHERE task_id = ?",
                (now_iso, now_iso, task_id),
            )

            conn.commit()

            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row)
        finally:
            conn.close()

    def get(self, task_id: str) -> RuntimeTask | None:
        """Fetch a single task by its ID.

        Args:
            task_id: The task to fetch.

        Returns:
            The ``RuntimeTask``, or ``None`` when not found.
        """
        with closing(connect(self._db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _parse_task(row) if row else None

    def list_tasks(
        self,
        source_session_id: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        parent_task_id: str | None = None,
        limit: int = 50,
    ) -> list[RuntimeTask]:
        """List tasks with optional filters, newest first.

        All filter parameters are optional.  When ``None`` the filter is
        not applied.

        Args:
            source_session_id: Filter by originating session.
            status: Filter by status value (database string, e.g.
                ``"queued"``, ``"running"``).
            kind: Filter by task kind.
            parent_task_id: Filter by parent task ID.  Pass ``"__none__"``
                to find tasks with no parent.
            limit: Maximum number of tasks to return.

        Returns:
            Chronologically descending list of matching tasks.
        """
        query = "SELECT * FROM runtime_tasks WHERE 1=1"
        params: list[Any] = []

        if source_session_id is not None:
            query += " AND source_session_id = ?"
            params.append(source_session_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind)
        if parent_task_id is not None:
            if parent_task_id == "__none__":
                query += " AND parent_task_id IS NULL"
            else:
                query += " AND parent_task_id = ?"
                params.append(parent_task_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with closing(connect(self._db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
            return [_parse_task(r) for r in rows]

    def delete_task(self, task_id: str) -> bool:
        """Delete a task and its runs + events (cascading cleanup).

        Returns ``True`` if a row was deleted, ``False`` if the task did
        not exist.
        """
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM runtime_task_runs WHERE task_id = ?", (task_id,),
            )
            conn.execute(
                "DELETE FROM runtime_task_events WHERE task_id = ?", (task_id,),
            )
            cursor = conn.execute(
                "DELETE FROM runtime_tasks WHERE task_id = ?", (task_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def purge_terminal_tasks(
        self,
        now: datetime,
        max_age_seconds: int = 300,
    ) -> int:
        """Delete all terminal tasks (FAILED, SUCCEEDED, CANCELLED) whose
        ``updated_at`` is older than *max_age_seconds*.

        Also deletes associated runs and events.  Returns the number of
        tasks removed.
        """
        cutoff = (now - timedelta(seconds=max_age_seconds)).isoformat()
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT task_id FROM runtime_tasks "
                "WHERE status IN ('failed', 'succeeded', 'cancelled') "
                "AND updated_at < ? "
                # Keep terminal tasks that are still referenced as parent
                # by a non-terminal child — the FK is meaningful; we'll
                # purge the parent once the child becomes terminal too.
                "AND task_id NOT IN ("
                "  SELECT DISTINCT parent_task_id FROM runtime_tasks "
                "  WHERE parent_task_id IS NOT NULL "
                "  AND status NOT IN ('failed', 'succeeded', 'cancelled')"
                ")",
                (cutoff,),
            ).fetchall()
            task_ids = [r["task_id"] for r in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                conn.execute(
                    f"DELETE FROM runtime_task_runs WHERE task_id IN ({placeholders})",
                    task_ids,
                )
                conn.execute(
                    f"DELETE FROM runtime_task_events WHERE task_id IN ({placeholders})",
                    task_ids,
                )
                conn.execute(
                    f"DELETE FROM runtime_tasks WHERE task_id IN ({placeholders})",
                    task_ids,
                )
            conn.commit()
            return len(task_ids)
        finally:
            conn.close()

    def get_task_with_runs(
        self,
        task_id: str,
    ) -> tuple[RuntimeTask, list[WorkerRun]]:
        """Fetch a task together with all of its ``WorkerRun`` records.

        Runs are returned newest-first by attempt number (descending).

        Args:
            task_id: The task to fetch.

        Returns:
            A ``(RuntimeTask, list[WorkerRun])`` tuple.

        Raises:
            ValueError: If the task does not exist.
        """
        with closing(connect(self._db_path)) as conn:
            task_row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise ValueError(f"Task {task_id!r} not found")

            run_rows = conn.execute(
                "SELECT * FROM runtime_task_runs WHERE task_id = ? "
                "ORDER BY attempt DESC",
                (task_id,),
            ).fetchall()

            return _parse_task(task_row), [_parse_run(r) for r in run_rows]
