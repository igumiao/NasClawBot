"""OperationJournal — append-only operation journal for idempotent retry.

The journal records filesystem operations (create_directory, move_file) so
that if the organize handler retries after a crash or error, it can detect
which operations were already applied and skip them.  Each entry is a
``FilesystemOperationRecord`` persisted as a JSON array in a single file.

Thread-safe via ``threading.Lock`` (the journal may be accessed from the
async handler thread pool or the sync agent thread).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.domain.runtime_tasks import FilesystemOperationRecord

logger = logging.getLogger(__name__)


class OperationJournal:
    """Thread-safe, append-only journal of filesystem operations.

    Stores entries as a JSON array in a single file.  Operations are
    identified by their ``operation_id`` (UUID hex).

    Typical usage::

        journal = OperationJournal("memory/runtime/organize-journal.json")
        journal.record_start("op-123", "create_directory", {"path": "/a/b"})
        # ... do the actual MCP call ...
        journal.record_success("op-123")
    """

    def __init__(self, path: str | Path) -> None:
        """Initialise the journal.

        Args:
            path: Filesystem path for the journal JSON file.  Parent
                directories are created automatically.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Record helpers
    # ------------------------------------------------------------------

    def record_start(
        self,
        operation_id: str,
        tool_name: Literal["create_directory", "move_file"],
        arguments: dict[str, str],
    ) -> FilesystemOperationRecord:
        """Record the start of a filesystem operation.

        Args:
            operation_id: Unique identifier for this operation.
            tool_name: The MCP filesystem tool being called.
            arguments: Tool arguments as passed to the MCP call.

        Returns:
            The newly created ``FilesystemOperationRecord``.
        """
        record = FilesystemOperationRecord(
            operation_id=operation_id,
            tool_name=tool_name,
            arguments=arguments,
            status="started",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._append(record)
        logger.debug("Journal record_start: %s (%s)", operation_id, tool_name)
        return record

    def record_success(
        self,
        operation_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record that an operation completed successfully.

        Args:
            operation_id: The operation to mark successful.
            result: Optional response data from the tool call.
        """
        self._update_status(operation_id, "succeeded", result=result)

    def record_already_applied(
        self,
        operation_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record that an operation was detected as already applied.

        This is the idempotent-retry path: on re-execution the source
        directory already exists or the file is already at the destination.

        Args:
            operation_id: The operation to mark.
            result: Optional diagnostic data.
        """
        self._update_status(operation_id, "already_applied", result=result)

    def record_failure(
        self,
        operation_id: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Record that an operation failed.

        Args:
            operation_id: The operation to mark failed.
            error: Optional structured error details.
        """
        self._update_status(operation_id, "failed", result=error)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_applied(self, operation_id: str) -> bool:
        """Check if an operation has reached a terminal applied state.

        Returns ``True`` when the operation's status is ``succeeded`` or
        ``already_applied``.
        """
        record = self._find(operation_id)
        return record is not None and record.status in ("succeeded", "already_applied")

    def list_applied(self) -> list[FilesystemOperationRecord]:
        """Return all operations whose status is ``succeeded`` or ``already_applied``."""
        return [
            r
            for r in self._load()
            if r.status in ("succeeded", "already_applied")
        ]

    def list_all(self) -> list[FilesystemOperationRecord]:
        """Return all journal entries."""
        return self._load()

    def clear(self) -> None:
        """Delete all journal entries."""
        with self._lock:
            if self._path.exists():
                self._path.write_text("[]", encoding="utf-8")
                logger.debug("Journal cleared")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> list[FilesystemOperationRecord]:
        """Load all records from the journal file."""
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else []
            if not isinstance(data, list):
                return []
            return [FilesystemOperationRecord.model_validate(item) for item in data]
        except (OSError, json.JSONDecodeError, Exception):
            logger.exception("Failed to load journal from %s", self._path)
            return []

    def _find(self, operation_id: str) -> FilesystemOperationRecord | None:
        """Locate a record by operation_id (linear scan, small dataset)."""
        for record in self._load():
            if record.operation_id == operation_id:
                return record
        return None

    def _append(self, record: FilesystemOperationRecord) -> None:
        """Append a record to the journal under lock."""
        with self._lock:
            records = self._load()
            records.append(record)
            self._write(records)

    def _update_status(
        self,
        operation_id: str,
        status: Literal["succeeded", "already_applied", "failed"],
        result: dict[str, Any] | None = None,
    ) -> None:
        """Update the status of an existing record under lock."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            records = self._load()
            for i, r in enumerate(records):
                if r.operation_id == operation_id:
                    records[i] = r.model_copy(update={
                        "status": status,
                        "result": result,
                        "completed_at": now,
                    })
                    break
            else:
                logger.warning(
                    "Journal _update_status: operation %s not found",
                    operation_id,
                )
                return
            self._write(records)

    def _write(self, records: list[FilesystemOperationRecord]) -> None:
        """Write all records to the journal file."""
        self._path.write_text(
            json.dumps(
                [r.model_dump(mode="json") for r in records],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
