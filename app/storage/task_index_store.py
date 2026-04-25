"""Persistence helpers for external-resource <-> qB task mapping.

This index supports de-dup checks and execution receipts.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from app.storage.db import connect, ensure_schema


class TaskIndexStore:
    """CRUD-style access to the `task_index` table."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_schema(self.db_path)

    def upsert(
        self,
        external_source: str,
        external_id: str,
        resource_title: str,
        status: str,
        qb_hash: str | None = None,
        qb_name: str | None = None,
        qb_category: str | None = None,
    ) -> None:
        """Insert/update one task-index row identified by source + external id."""
        with closing(connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO task_index (
                    external_source,
                    external_id,
                    resource_title,
                    qb_hash,
                    qb_name,
                    qb_category,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_source, external_id) DO UPDATE SET
                    resource_title = excluded.resource_title,
                    qb_hash = excluded.qb_hash,
                    qb_name = excluded.qb_name,
                    qb_category = excluded.qb_category,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    external_source,
                    external_id,
                    resource_title,
                    qb_hash,
                    qb_name,
                    qb_category,
                    status,
                ),
            )

    def get(self, external_source: str, external_id: str) -> dict[str, Any] | None:
        """Fetch one task-index row, or `None` when missing."""
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT * FROM task_index
                WHERE external_source = ? AND external_id = ?
                """,
                (external_source, external_id),
            ).fetchone()
        return dict(row) if row else None
