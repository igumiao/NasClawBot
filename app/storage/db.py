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
    # ------------------------------------------------------------------
    # WAL mode -- best-effort; fall back to rollback journal silently.
    # ------------------------------------------------------------------
    try:
        conn.execute("PRAGMA journal_mode = wal")
    except sqlite3.OperationalError:
        # Filesystem or platform may not support WAL (e.g. network mount).
        # Deployment limitation; startup continues with rollback journal.
        pass

    conn.execute("PRAGMA busy_timeout = 5000")

    conn.executescript("""
    -- ------------------------------------------------------------------
    -- Runtime tasks (plan SS7.1)
    -- ------------------------------------------------------------------
    CREATE TABLE IF NOT EXISTS runtime_tasks (
        task_id          TEXT PRIMARY KEY,
        kind             TEXT NOT NULL,
        status           TEXT NOT NULL,
        payload_json     TEXT NOT NULL,
        result_json      TEXT,
        error_json       TEXT,
        run_after        TEXT,
        attempts             INTEGER NOT NULL DEFAULT 0,
        max_attempts         INTEGER NOT NULL DEFAULT 8,
        failure_count        INTEGER NOT NULL DEFAULT 0,
        parent_task_id   TEXT,
        source_session_id TEXT,
        dedupe_key       TEXT UNIQUE,
        exclusive_key    TEXT,
        lease_owner      TEXT,
        lease_expires_at TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        started_at       TEXT,
        completed_at     TEXT,
        FOREIGN KEY (parent_task_id) REFERENCES runtime_tasks (task_id)
    );

    CREATE INDEX IF NOT EXISTS idx_runtime_tasks_due
        ON runtime_tasks (status, run_after);

    CREATE INDEX IF NOT EXISTS idx_runtime_tasks_session
        ON runtime_tasks (source_session_id, created_at DESC);

    -- ------------------------------------------------------------------
    -- Worker runs (plan SS7.2)
    -- ------------------------------------------------------------------
    CREATE TABLE IF NOT EXISTS runtime_task_runs (
        run_id          TEXT PRIMARY KEY,
        task_id         TEXT NOT NULL,
        attempt         INTEGER NOT NULL,
        status          TEXT NOT NULL,
        handoff_json    TEXT,
        history_json    TEXT,
        result_json     TEXT,
        error_json      TEXT,
        started_at      TEXT NOT NULL,
        completed_at    TEXT,
        FOREIGN KEY (task_id) REFERENCES runtime_tasks (task_id)
    );

    CREATE INDEX IF NOT EXISTS idx_runtime_task_runs_task
        ON runtime_task_runs (task_id, attempt DESC);

    -- ------------------------------------------------------------------
    -- Task events (plan SS7.3)
    --
    -- NOTE: no FK on ``task_id`` — events outlive their parent task so
    -- that users have time to see and acknowledge them before purge.
    -- ------------------------------------------------------------------
    CREATE TABLE IF NOT EXISTS runtime_task_events (
        event_id           TEXT PRIMARY KEY,
        task_id            TEXT NOT NULL,
        source_session_id  TEXT,
        kind               TEXT NOT NULL,
        severity           TEXT NOT NULL,
        title              TEXT NOT NULL,
        summary            TEXT NOT NULL,
        payload_json       TEXT,
        created_at         TEXT NOT NULL,
        acknowledged_at    TEXT,
        injected_at        TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_runtime_task_events_session
        ON runtime_task_events (source_session_id, created_at);
    """)

    # -- schema migrations (idempotent) -------------------------------
    # Add ``failure_count`` column for existing databases created before
    # the ``attempts`` / ``failure_count`` split (2026-06-23).
    _ensure_column(conn, "runtime_tasks", "failure_count",
                   "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "runtime_tasks", "exclusive_key", "TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_tasks_active_exclusive "
        "ON runtime_tasks (exclusive_key) "
        "WHERE exclusive_key IS NOT NULL "
        "AND status IN ('initializing', 'queued', 'running', 'waiting')"
    )

    # Remove FK from runtime_task_events so events can outlive their
    # parent task.  SQLite does not support ALTER TABLE DROP CONSTRAINT
    # so we recreate the table (2026-06-23).
    _migrate_events_no_fk(conn)


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add *column* to *table* if it does not already exist.

    Idempotent: catches ``OperationalError`` for duplicate columns.
    """
    try:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
    except sqlite3.OperationalError:
        # Column already exists — safe to ignore.
        pass


def _migrate_events_no_fk(conn: sqlite3.Connection) -> None:
    """Recreate ``runtime_task_events`` without the FK on ``task_id``.

    SQLite does not support ``ALTER TABLE DROP CONSTRAINT``, so the table
    must be recreated.  Idempotent: queries ``PRAGMA foreign_key_list``
    first and returns immediately when no FK is present.
    """
    fk_list = conn.execute(
        "PRAGMA foreign_key_list('runtime_task_events')"
    ).fetchall()
    if not fk_list:
        return  # Already migrated

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executescript(
            """
            CREATE TABLE runtime_task_events_new (
                event_id           TEXT PRIMARY KEY,
                task_id            TEXT NOT NULL,
                source_session_id  TEXT,
                kind               TEXT NOT NULL,
                severity           TEXT NOT NULL,
                title              TEXT NOT NULL,
                summary            TEXT NOT NULL,
                payload_json       TEXT,
                created_at         TEXT NOT NULL,
                acknowledged_at    TEXT,
                injected_at        TEXT
            );

            INSERT INTO runtime_task_events_new
                SELECT * FROM runtime_task_events;

            DROP TABLE runtime_task_events;

            ALTER TABLE runtime_task_events_new RENAME TO runtime_task_events;

            CREATE INDEX IF NOT EXISTS idx_runtime_task_events_session
                ON runtime_task_events (source_session_id, created_at);
            """
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_schema(db_path: str | Path) -> None:
    """Idempotently ensure schema exists for a database path."""
    with closing(connect(db_path)) as conn, conn:
        initialize_schema(conn)
