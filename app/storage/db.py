from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def _normalize_db_path(db_path: str | Path) -> Path:
    resolved = Path(db_path)
    if resolved.parent and not resolved.parent.exists():
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = _normalize_db_path(db_path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            latest_user_message TEXT NOT NULL,
            constraints_json TEXT NOT NULL,
            confirmation_payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS preferences (
            user_id TEXT PRIMARY KEY,
            preferred_resolution TEXT,
            subtitle_preference TEXT,
            encoding_preference TEXT,
            default_download_profile TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS task_index (
            external_source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            resource_title TEXT NOT NULL,
            qb_hash TEXT,
            qb_name TEXT,
            qb_category TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (external_source, external_id)
        );

        CREATE INDEX IF NOT EXISTS idx_task_index_qb_hash ON task_index (qb_hash);
        """
    )


def ensure_schema(db_path: str | Path) -> None:
    with closing(connect(db_path)) as conn, conn:
        initialize_schema(conn)
