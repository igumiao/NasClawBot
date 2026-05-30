"""Thin SQLite store for runtime workflow sessions.

Only Runtime reads and writes this store. Agents and workflows do not access it directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.storage.db import connect, ensure_schema


class RuntimeSessionStore:
    """Persist WorkflowEnvelope to the runtime_sessions SQLite table."""

    def __init__(self, db_path: str | Path) -> None:
        ensure_schema(db_path)
        self._db_path = str(db_path)

    def save(self, session_id: str, envelope: dict[str, Any]) -> None:
        domain = envelope.get("domain") or {}
        # Derive top-level projection from domain so the compatibility column
        # stays in sync with the source of truth.
        confirmation_payload = envelope.get("confirmation_payload") or domain.get("confirmation_payload")
        conn = connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    """INSERT INTO runtime_sessions
                       (session_id, status, current_workflow, domain_state_json,
                        pending_approval_json, confirmation_payload_json,
                        tool_trace_json, error, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                       ON CONFLICT(session_id) DO UPDATE SET
                        status=excluded.status,
                        current_workflow=excluded.current_workflow,
                        domain_state_json=excluded.domain_state_json,
                        pending_approval_json=excluded.pending_approval_json,
                        confirmation_payload_json=excluded.confirmation_payload_json,
                        tool_trace_json=excluded.tool_trace_json,
                        error=excluded.error,
                        updated_at=datetime('now')""",
                    (
                        session_id,
                        envelope.get("status", "in_progress"),
                        envelope.get("current_workflow", "search_download"),
                        json.dumps(domain, ensure_ascii=False),
                        json.dumps(envelope.get("pending_approval"), ensure_ascii=False),
                        json.dumps(confirmation_payload, ensure_ascii=False),
                        json.dumps(envelope.get("tool_trace", []), ensure_ascii=False),
                        envelope.get("error"),
                    ),
                )
        finally:
            conn.close()

    def load(self, session_id: str) -> dict[str, Any] | None:
        conn = connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "session_id": row["session_id"],
                "status": row["status"],
                "current_workflow": row["current_workflow"],
                "domain": json.loads(row["domain_state_json"]) if row["domain_state_json"] else None,
                "pending_approval": json.loads(row["pending_approval_json"]) if row["pending_approval_json"] else None,
                "confirmation_payload": json.loads(row["confirmation_payload_json"]) if row["confirmation_payload_json"] else None,
                "tool_trace": json.loads(row["tool_trace_json"]) if row["tool_trace_json"] else [],
                "error": row["error"],
            }
        finally:
            conn.close()

    def delete(self, session_id: str) -> None:
        conn = connect(self._db_path)
        try:
            with conn:
                conn.execute(
                    "DELETE FROM runtime_sessions WHERE session_id = ?",
                    (session_id,),
                )
        finally:
            conn.close()
