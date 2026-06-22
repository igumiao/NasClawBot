"""Domain types for the runtime task persistence and execution layer.

TaskStatus enum, persistence models (RuntimeTask, WorkerRun, TaskEvent),
handler outcome types with discriminated unions, legal state transition
validation, and the FilesystemOperationRecord journal model from the
post-download automation plan (SS6, SS7, SS13).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    """Lifecycle states for a durable RuntimeTask.

    INITIALIZING
        Task reservation created; external side effect (e.g. qB submission)
        not yet confirmed.  Closes the crash window between task creation and
        external acceptance.
    QUEUED
        Ready for worker claim.  Run-after scheduling is enforced by the
        run_after column, not by a separate state.
    RUNNING
        Currently claimed and being executed by a handler.
    WAITING
        Handler requested a deferred retry (e.g. polling an incomplete
        download).  The loop treats waiting identically to queued for
        claim purposes.
    SUCCEEDED
        Terminal.  Handler completed successfully.
    FAILED
        Terminal.  Handler exhausted retries or encountered a non-retryable
        error.
    CANCELLED
        Terminal.  Explicitly cancelled by the user or an administrative
        action.
    """

    INITIALIZING = "initializing"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskEventSeverity(str, Enum):
    """Semantic severity for a user-facing TaskEvent.

    Values mirror common notification levels so the frontend can map them
    to colour / icon without additional translation.
    """

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# State transition rules (SS6.2)
# ---------------------------------------------------------------------------

LEGAL_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.INITIALIZING: {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.WAITING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.WAITING, TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
}

"""Legal state transitions keyed by source status.

Terminal states (SUCCEEDED, FAILED, CANCELLED) are immutable and do not
appear as source keys.
"""

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)

"""Status values that MUST NOT transition to any other status.

Repeated completion, failure, or cancellation requests must return the
existing row without publishing duplicate events.
"""


def validate_status_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Raise ``ValueError`` if *current* -> *target* is illegal.

    Checks both terminal immutability and the allowed-transition map.
    Safe to call before persisting any state change.
    """
    if current in TERMINAL_STATUSES:
        raise ValueError(
            f"Cannot transition from terminal status {current.value!r} "
            f"to {target.value!r}"
        )
    allowed = LEGAL_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(f"Unknown source status {current.value!r}")
    if target not in allowed:
        allowed_str = ", ".join(s.value for s in sorted(allowed, key=lambda s: s.value))
        raise ValueError(
            f"Invalid transition from {current.value!r} to {target.value!r}. "
            f"Allowed targets from {current.value!r}: {allowed_str}"
        )


def is_terminal(status: TaskStatus) -> bool:
    """Return ``True`` when *status* is a terminal (immutable) state."""
    return status in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Persistence models (SS7)
# ---------------------------------------------------------------------------

class RuntimeTask(BaseModel):
    """One durable business-work item that can wait across requests and restarts.

    Maps to the ``runtime_tasks`` SQLite table.  JSON-serializable fields
    (*_json suffixes in the schema) are represented as native Python dicts
    or None; the store layer handles serialization to TEXT.

    ``populate_by_name`` is enabled so callers may use the clean field name
    (``payload``) while SQL row parsing uses the alias (``payload_json``).

    Timestamps use UTC ISO-8601 strings.
    """

    model_config = {"populate_by_name": True}

    task_id: str
    """Primary key (UUID hex)."""

    kind: str
    """Task kind discriminator (e.g. ``"download_watch"``, ``"organize_download"``)."""

    status: TaskStatus = TaskStatus.INITIALIZING
    """Current lifecycle state."""

    payload: dict[str, Any] = Field(default_factory=dict, alias="payload_json")
    """Arbitrary JSON-serializable invocation payload."""

    result: dict[str, Any] | None = Field(default=None, alias="result_json")
    """Structured completion result populated on SUCCEEDED."""

    error: dict[str, Any] | None = Field(default=None, alias="error_json")
    """Structured error details populated on FAILED."""

    run_after: str | None = None
    """Earliest ISO-8601 datetime at which this task is due for claim.

    ``None`` means immediately eligible.
    """

    attempts: int = 0
    """Number of execution attempts so far."""

    max_attempts: int = 20
    """Maximum execution attempts before permanent FAILED."""

    parent_task_id: str | None = None
    """Optional FK to the task that spawned this one."""

    source_session_id: str | None = None
    """Conversation session ID that originated this task, if any."""

    dedupe_key: str | None = None
    """Optional unique key for idempotent creation (UNIQUE in SQLite)."""

    lease_owner: str | None = None
    """Worker instance that currently holds the execution lease."""

    lease_expires_at: str | None = None
    """ISO-8601 datetime when the current lease expires."""

    created_at: str = Field(default_factory=utc_now_iso)
    """Task creation timestamp."""

    updated_at: str = Field(default_factory=utc_now_iso)
    """Last modification timestamp."""

    started_at: str | None = None
    """Timestamp when the task first transitioned to RUNNING."""

    completed_at: str | None = None
    """Timestamp when the task entered a terminal state."""

    @field_validator("attempts")
    @classmethod
    def _non_negative_attempts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("attempts must be non-negative")
        return value

    @field_validator("max_attempts")
    @classmethod
    def _positive_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts must be >= 1")
        return value

    def model_dump_sql(self) -> dict[str, Any]:
        """Dump to a flat dict keyed by SQL column names.

        JSON fields are serialised to their ``*_json`` alias targets.
        Use this when writing to the database.
        """
        return self.model_dump(by_alias=True)

    @classmethod
    def model_validate_sql(cls, data: dict[str, Any]) -> RuntimeTask:
        """Construct from a flat SQL row dict (``*_json`` columns included).

        Use this when reading from the database.
        """
        return cls.model_validate(data)


class WorkerRun(BaseModel):
    """One execution attempt for a RuntimeTask, including structured handoff.

    Maps to the ``runtime_task_runs`` SQLite table.

    Every attempt creates a separate WorkerRun row.  ``history_json``
    belongs only to WorkerRuns for WorkerAgent-type tasks (e.g. organization);
    it must never be copied into a conversation checkpoint.
    """

    model_config = {"populate_by_name": True}

    run_id: str
    """Primary key (UUID hex)."""

    task_id: str
    """FK to ``runtime_tasks.task_id``."""

    attempt: int
    """Attempt number for this task (1-based)."""

    status: TaskStatus
    """Run-level status (usually RUNNING, SUCCEEDED, or FAILED)."""

    handoff: dict[str, Any] | None = Field(default=None, alias="handoff_json")
    """Structured handoff payload passed to the handler."""

    history: list[dict[str, Any]] | None = Field(default=None, alias="history_json")
    """Agent-provider message history for WorkerAgent-type runs."""

    result: dict[str, Any] | None = Field(default=None, alias="result_json")
    """Structured run-level completion result."""

    error: dict[str, Any] | None = Field(default=None, alias="error_json")
    """Structured run-level error details."""

    started_at: str = Field(default_factory=utc_now_iso)
    """Run start timestamp."""

    completed_at: str | None = None
    """Run completion timestamp."""

    @field_validator("attempt")
    @classmethod
    def _positive_attempt(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempt must be >= 1")
        return value

    def model_dump_sql(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)

    @classmethod
    def model_validate_sql(cls, data: dict[str, Any]) -> WorkerRun:
        return cls.model_validate(data)


class TaskEvent(BaseModel):
    """A typed user-visible result or attention notification emitted by a task.

    Maps to the ``runtime_task_events`` SQLite table.

    Events are derived from structured handler results -- the Worker Agent
    does not decide whether an event is published.  ``acknowledged_at`` and
    ``injected_at`` are dual-purpose: the former tracks UI dismissal while
    the latter tracks successful inclusion in a conversation Agent turn.
    """

    model_config = {"populate_by_name": True}

    event_id: str
    """Primary key (UUID hex)."""

    task_id: str
    """FK to ``runtime_tasks.task_id``."""

    source_session_id: str | None = None
    """Conversation session that originated the parent task, for scoped queries."""

    kind: str
    """Event kind discriminator (e.g. ``"download_completed"``, ``"organize_completed"``)."""

    severity: TaskEventSeverity
    """User-facing severity for UI rendering."""

    title: str
    """Short human-readable title (e.g. "下载整理完成")."""

    summary: str
    """Single-line human-readable summary (e.g. "《某某》已整理到 电影/...")."""

    payload: dict[str, Any] | None = Field(default=None, alias="payload_json")
    """Optional structured details (e.g. moved file count, destination path)."""

    created_at: str = Field(default_factory=utc_now_iso)
    """Event creation timestamp."""

    acknowledged_at: str | None = None
    """Timestamp when the UI/user saw or dismissed this event."""

    injected_at: str | None = None
    """Timestamp when this event was successfully included in a completed
    conversation Agent turn."""

    def model_dump_sql(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)

    @classmethod
    def model_validate_sql(cls, data: dict[str, Any]) -> TaskEvent:
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Handler outcome types (SS6.3)
# ---------------------------------------------------------------------------

class ChildTaskSpec(BaseModel):
    """Specification for a child task to be spawned by a handler outcome.

    The worker creates one ``RuntimeTask`` per child, deduplicating by
    ``dedupe_key`` when provided.
    """

    kind: str
    """Task kind for the child (e.g. ``"organize_download"``)."""

    payload: dict[str, Any] = Field(default_factory=dict)
    """Initial task payload."""

    dedupe_key: str | None = None
    """Optional deduplication key for idempotent child creation."""

    run_after: str | None = None
    """Optional ISO-8601 timestamp for deferred scheduling."""


class Complete(BaseModel):
    """Handler completed successfully."""

    kind: Literal["complete"] = "complete"
    result: dict[str, Any] = Field(default_factory=dict)
    """Structured completion data merged into task result."""

    events: list[dict[str, Any]] = Field(default_factory=list)
    """One or more event payloads to publish as TaskEvents."""


class Reschedule(BaseModel):
    """Handler wants to be retried later (e.g. waiting for download progress)."""

    kind: Literal["reschedule"] = "reschedule"
    run_after: str
    """ISO-8601 datetime for the next attempt."""

    payload_patch: dict[str, Any] = Field(default_factory=dict)
    """Optional partial payload update applied before the next run."""

    reason: str | None = None
    """Optional human-readable explanation for the reschedule."""


class Fail(BaseModel):
    """Handler failed with a structured error.

    The worker decides whether to retry based on ``retryable`` and the
    task's remaining attempts.
    """

    kind: Literal["fail"] = "fail"
    code: str
    """Machine-readable error code (e.g. ``"QB_TORRENT_MISSING"``)."""

    message: str
    """Human-readable error description."""

    retryable: bool = False
    """Whether the worker should retry up to ``max_attempts``."""

    details: dict[str, Any] = Field(default_factory=dict)
    """Optional structured error context."""


class Spawn(BaseModel):
    """Handler created child tasks and optionally completed itself.

    The worker creates one ``RuntimeTask`` per child (deduplicated by key),
    publishes any supplied events, and merges ``result`` into the parent
    task result.
    """

    kind: Literal["spawn"] = "spawn"
    children: list[ChildTaskSpec] = Field(default_factory=list)
    """Child tasks to create."""

    result: dict[str, Any] = Field(default_factory=dict)
    """Structured completion data merged into task result."""

    events: list[dict[str, Any]] = Field(default_factory=list)
    """Optional event payloads to publish alongside the spawn."""


# Discriminated union for runtime handler outcomes.
TaskOutcome = Annotated[
    Union[Complete, Reschedule, Fail, Spawn],
    Field(discriminator="kind"),
]
"""One of the four handler outcome types, discriminated by ``kind``.

Usage::

    outcome: TaskOutcome
    match outcome.kind:
        case "complete":
            ...
        case "reschedule":
            ...
        case "fail":
            ...
        case "spawn":
            ...
"""


# ---------------------------------------------------------------------------
# Journal model (SS13)
# ---------------------------------------------------------------------------

class FilesystemOperationRecord(BaseModel):
    """One durable entry in the filesystem operation journal.

    Written by scoped mutating wrappers before and after forwarding a call
    to the MCP filesystem server.  Used for crash-safe idempotency during
    retries and for the handler's post-execution verification.
    """

    operation_id: str
    """Unique operation identifier (UUID hex)."""

    tool_name: Literal["create_directory", "move_file"]
    """The scoped filesystem tool that was invoked."""

    arguments: dict[str, str]
    """Tool arguments as passed to the MCP call."""

    status: Literal["started", "succeeded", "already_applied", "failed"]
    """Current status of this journal entry.

    * ``started`` -- written *before* the MCP call.
    * ``succeeded`` -- MCP call returned successfully.
    * ``already_applied`` -- source absent / destination present with
      matching metadata (idempotent retry guard).
    * ``failed`` -- MCP call raised or returned an error.
    """

    result: dict[str, Any] | None = None
    """Response from the MCP tool call, if available."""

    started_at: str = Field(default_factory=utc_now_iso)
    """Timestamp when the operation started."""

    completed_at: str | None = None
    """Timestamp when the operation reached a terminal journal status."""
