"""Persistence helpers for session-level workflow state.

This store only handles data access; workflow logic lives elsewhere.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from app.storage.db import connect, ensure_schema


class SessionStore:
    """CRUD-style access to the `sessions` table."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_schema(self.db_path)

    def upsert(
        self,
        session_id: str,
        latest_user_message: str,
        constraints_json: str,
        confirmation_payload_json: str,
        status: str,
    ) -> None:
        """Insert/update the latest snapshot for one session id."""
        with closing(connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id,
                    latest_user_message,
                    constraints_json,
                    confirmation_payload_json,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    latest_user_message = excluded.latest_user_message,
                    constraints_json = excluded.constraints_json,
                    confirmation_payload_json = excluded.confirmation_payload_json,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    session_id,
                    latest_user_message,
                    constraints_json,
                    confirmation_payload_json,
                    status,
                ),
            )

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Fetch one session snapshot, or `None` if not found."""
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None
