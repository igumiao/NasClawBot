"""SQLite connection and schema bootstrap helpers.

All store classes import these functions so schema creation behavior stays
consistent across modules.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def _normalize_db_path(db_path: str | Path) -> Path:
    """Resolve db path and create parent directory when needed."""
    resolved = Path(db_path)
    if resolved.parent and not resolved.parent.exists():
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Create a configured SQLite connection for store operations."""
    path = _normalize_db_path(db_path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create tables/indexes required by the current MVP."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runtime_sessions (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'in_progress',
            current_workflow TEXT NOT NULL DEFAULT 'search_download',
            domain_state_json TEXT,
            pending_approval_json TEXT,
            confirmation_payload_json TEXT,
            tool_trace_json TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def ensure_schema(db_path: str | Path) -> None:
    """Idempotently ensure schema exists for a database path."""
    with closing(connect(db_path)) as conn, conn:
        initialize_schema(conn)
