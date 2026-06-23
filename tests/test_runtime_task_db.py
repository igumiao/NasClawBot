"""Tests for the runtime task DB schema (app.storage.db).

Verifies schema creation, constraints, JSON round-trips, and index existence
using an in-memory SQLite database.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.storage.db import connect, initialize_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn() -> sqlite3.Connection:
    """Create an in-memory SQLite connection with the schema applied."""
    db = connect(":memory:")
    initialize_schema(db)
    return db


# ---------------------------------------------------------------------------
# Idempotent schema creation
# ---------------------------------------------------------------------------


class TestSchemaIdempotency:
    """initialize_schema can be safely called multiple times."""

    def test_double_init_does_not_raise(self, conn: sqlite3.Connection) -> None:
        initialize_schema(conn)
        initialize_schema(conn)

    def test_tables_still_exist_after_double_init(
        self, conn: sqlite3.Connection
    ) -> None:
        initialize_schema(conn)
        initialize_schema(conn)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in cursor.fetchall()}
        for expected in ("runtime_tasks", "runtime_task_runs", "runtime_task_events"):
            assert expected in names, f"table {expected} should exist after double init"

    def test_double_init_preserves_inserted_data(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t1", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        initialize_schema(conn)  # second call
        row = conn.execute(
            "SELECT task_id FROM runtime_tasks WHERE task_id = ?", ("t1",)
        ).fetchone()
        assert row is not None, "data should survive a second schema initialisation"


# ---------------------------------------------------------------------------
# Table and index existence
# ---------------------------------------------------------------------------


class TestTableAndIndexExistence:
    """All three tables and their indexes are created."""

    TABLE_NAMES = ("runtime_tasks", "runtime_task_runs", "runtime_task_events")

    INDEX_NAMES = (
        "idx_runtime_tasks_due",
        "idx_runtime_tasks_session",
        "idx_runtime_tasks_active_exclusive",
        "idx_runtime_task_runs_task",
        "idx_runtime_task_events_session",
    )

    def test_all_tables_exist(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in cursor.fetchall()}
        for expected in self.TABLE_NAMES:
            assert expected in names, f"missing table {expected}"

    def test_all_indexes_exist(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        names = {row["name"] for row in cursor.fetchall()}
        for expected in self.INDEX_NAMES:
            assert expected in names, f"missing index {expected}"

    def test_tables_have_expected_columns(self, conn: sqlite3.Connection) -> None:
        """Spot-check each table for a subset of columns that matter most."""
        # runtime_tasks
        cols = self._column_names(conn, "runtime_tasks")
        for col in (
            "task_id",
            "kind",
            "status",
            "payload_json",
            "dedupe_key",
            "exclusive_key",
            "parent_task_id",
            "created_at",
            "updated_at",
        ):
            assert col in cols, f"runtime_tasks missing column {col}"

        # runtime_task_runs
        cols = self._column_names(conn, "runtime_task_runs")
        for col in ("run_id", "task_id", "attempt", "status", "started_at"):
            assert col in cols, f"runtime_task_runs missing column {col}"

        # runtime_task_events
        cols = self._column_names(conn, "runtime_task_events")
        for col in ("event_id", "task_id", "kind", "severity", "title", "summary"):
            assert col in cols, f"runtime_task_events missing column {col}"

    @staticmethod
    def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return {row["name"] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Foreign key constraints
# ---------------------------------------------------------------------------


class TestForeignKeyConstraints:
    """runtime_task_runs enforce REFERENCES runtime_tasks(task_id).

    runtime_task_events intentionally has NO FK on task_id — events are
    decoupled from task lifecycle so they persist after task purge for
    the user and Agent to see.
    """

    def test_task_run_rejects_bogus_task_id(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO runtime_task_runs "
                "(run_id, task_id, attempt, status, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("r1", "no-such-task", 1, "running", "2026-06-01T00:00:00"),
            )

    def test_task_event_allows_bogus_task_id(
        self, conn: sqlite3.Connection
    ) -> None:
        """Events should accept a non-existent task_id — no FK on the column."""
        conn.execute(
            "INSERT INTO runtime_task_events "
            "(event_id, task_id, kind, severity, title, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "e1",
                "no-such-task",
                "status_change",
                "info",
                "Test event",
                "desc",
                "2026-06-01T00:00:00",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM runtime_task_events WHERE event_id = ?", ("e1",)
        ).fetchone()
        assert row is not None
        assert row["task_id"] == "no-such-task"

    def test_task_run_allows_valid_task_id(
        self, conn: sqlite3.Connection
    ) -> None:
        self._insert_minimal_task(conn, "t-valid")
        conn.execute(
            "INSERT INTO runtime_task_runs "
            "(run_id, task_id, attempt, status, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("r-valid", "t-valid", 1, "running", "2026-06-01T00:00:00"),
        )
        row = conn.execute(
            "SELECT run_id FROM runtime_task_runs WHERE run_id = ?", ("r-valid",)
        ).fetchone()
        assert row is not None

    def test_task_event_allows_valid_task_id(
        self, conn: sqlite3.Connection
    ) -> None:
        self._insert_minimal_task(conn, "t-valid2")
        conn.execute(
            "INSERT INTO runtime_task_events "
            "(event_id, task_id, kind, severity, title, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "e-valid",
                "t-valid2",
                "status_change",
                "info",
                "OK",
                "details",
                "2026-06-01T00:00:00",
            ),
        )
        row = conn.execute(
            "SELECT event_id FROM runtime_task_events WHERE event_id = ?",
            ("e-valid",),
        ).fetchone()
        assert row is not None

    def test_cascading_delete_not_enforced(
        self, conn: sqlite3.Connection
    ) -> None:
        """SQLite with foreign_keys=ON prevents deleting a parent with children.

        The FK definition uses the default NO ACTION clause, but SQLite
        effectively behaves like RESTRICT when foreign_keys pragma is ON.
        Application-level code must delete or reassign children first.
        """
        self._insert_minimal_task(conn, "t-cascade")
        conn.execute(
            "INSERT INTO runtime_task_runs "
            "(run_id, task_id, attempt, status, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("r-cascade", "t-cascade", 1, "running", "2026-06-01T00:00:00"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "DELETE FROM runtime_tasks WHERE task_id = ?", ("t-cascade",)
            )

    @staticmethod
    def _insert_minimal_task(conn: sqlite3.Connection, task_id: str) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# dedupe_key UNIQUE constraint
# ---------------------------------------------------------------------------


class TestDedupeKeyUniqueness:
    """NULL dedupe_key values are allowed; non-NULL values must be unique."""

    def test_multiple_null_dedupe_keys_allowed(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t1", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t2", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        # Both rows with NULL dedupe_key exist — no unique violation.
        rows = conn.execute(
            "SELECT count(*) AS cnt FROM runtime_tasks"
        ).fetchone()
        assert rows["cnt"] == 2

    def test_duplicate_non_null_dedupe_key_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "t1",
                "test",
                "pending",
                "{}",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
                "dedupe:abc123",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(
                "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
                "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "t2",
                    "test",
                    "pending",
                    "{}",
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:00:00",
                    "dedupe:abc123",
                ),
            )

    def test_unique_dedupe_keys_allowed(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "t1",
                "test",
                "pending",
                "{}",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
                "dedupe:unique1",
            ),
        )
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "t2",
                "test",
                "pending",
                "{}",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
                "dedupe:unique2",
            ),
        )
        rows = conn.execute(
            "SELECT count(*) AS cnt FROM runtime_tasks"
        ).fetchone()
        assert rows["cnt"] == 2

    def test_explicit_null_dedupe_key_and_non_null_coexist(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "t1",
                "test",
                "pending",
                "{}",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
                None,
            ),
        )
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, dedupe_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "t2",
                "test",
                "pending",
                "{}",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
                "dedupe:xyz",
            ),
        )
        rows = conn.execute(
            "SELECT count(*) AS cnt FROM runtime_tasks"
        ).fetchone()
        assert rows["cnt"] == 2


# ---------------------------------------------------------------------------
# JSON field round-trip (Unicode paths / Chinese titles)
# ---------------------------------------------------------------------------


class TestJsonFieldRoundTrip:
    """JSON text columns preserve Unicode, Chinese characters, and paths."""

    CHINESE_TITLE = "沙丘2：全面启动"
    NAS_PATH = "/volume1/影视/电影/沙丘2 (2024)"
    EMOJI_FALLBACK = "test ☃ snowman"

    def test_payload_json_round_trips_chinese_content(
        self, conn: sqlite3.Connection
    ) -> None:
        payload = {
            "title": self.CHINESE_TITLE,
            "path": self.NAS_PATH,
            "tags": ["电影", "科幻"],
        }
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "t-unicode",
                "download",
                "pending",
                json.dumps(payload, ensure_ascii=False),
                "2026-06-01T00:00:00",
                "2026-06-01T00:00:00",
            ),
        )
        row = conn.execute(
            "SELECT payload_json FROM runtime_tasks WHERE task_id = ?",
            ("t-unicode",),
        ).fetchone()
        restored = json.loads(row["payload_json"])
        assert restored["title"] == self.CHINESE_TITLE
        assert restored["path"] == self.NAS_PATH
        assert restored["tags"] == ["电影", "科幻"]

    def test_result_json_round_trips_chinese_content(
        self, conn: sqlite3.Connection
    ) -> None:
        self._insert_minimal_task(conn, "t-result")
        result = {"downloaded": True, "filename": self.CHINESE_TITLE}
        conn.execute(
            "UPDATE runtime_tasks SET result_json = ? WHERE task_id = ?",
            (json.dumps(result, ensure_ascii=False), "t-result"),
        )
        row = conn.execute(
            "SELECT result_json FROM runtime_tasks WHERE task_id = ?",
            ("t-result",),
        ).fetchone()
        restored = json.loads(row["result_json"])
        assert restored == result

    def test_error_json_round_trips_chinese_content(
        self, conn: sqlite3.Connection
    ) -> None:
        self._insert_minimal_task(conn, "t-err")
        error = {"message": f"下载失败: {self.CHINESE_TITLE}", "code": 500}
        conn.execute(
            "UPDATE runtime_tasks SET error_json = ? WHERE task_id = ?",
            (json.dumps(error, ensure_ascii=False), "t-err"),
        )
        row = conn.execute(
            "SELECT error_json FROM runtime_tasks WHERE task_id = ?",
            ("t-err",),
        ).fetchone()
        restored = json.loads(row["error_json"])
        assert restored == error

    def test_payload_json_with_emoji(
        self, conn: sqlite3.Connection
    ) -> None:
        payload = {"note": self.EMOJI_FALLBACK}
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "t-emoji",
                "test",
                "pending",
                json.dumps(payload, ensure_ascii=False),
                "2026-06-01T00:00:00",
                "2026-06-01T00:00:00",
            ),
        )
        row = conn.execute(
            "SELECT payload_json FROM runtime_tasks WHERE task_id = ?",
            ("t-emoji",),
        ).fetchone()
        assert json.loads(row["payload_json"]) == payload

    @staticmethod
    def _insert_minimal_task(conn: sqlite3.Connection, task_id: str) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# Timestamp field storage
# ---------------------------------------------------------------------------


class TestTimestampStorage:
    """ISO-8601 timestamps round-trip correctly in TEXT columns."""

    def test_timestamps_round_trip(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "t-ts",
                "download",
                "completed",
                "{}",
                "2026-06-01T12:30:00+08:00",
                "2026-06-01T13:00:00+08:00",
                "2026-06-01T12:31:00+08:00",
                "2026-06-01T12:59:00+08:00",
            ),
        )
        row = conn.execute(
            "SELECT created_at, updated_at, started_at, completed_at "
            "FROM runtime_tasks WHERE task_id = ?",
            ("t-ts",),
        ).fetchone()
        assert row["created_at"] == "2026-06-01T12:30:00+08:00"
        assert row["updated_at"] == "2026-06-01T13:00:00+08:00"
        assert row["started_at"] == "2026-06-01T12:31:00+08:00"
        assert row["completed_at"] == "2026-06-01T12:59:00+08:00"

    def test_timestamp_fields_default_to_null(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t-nullts", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        row = conn.execute(
            "SELECT started_at, completed_at FROM runtime_tasks WHERE task_id = ?",
            ("t-nullts",),
        ).fetchone()
        assert row["started_at"] is None
        assert row["completed_at"] is None

    def test_run_and_event_timestamps(self, conn: sqlite3.Connection) -> None:
        self._insert_minimal_task(conn, "t-ts2")
        conn.execute(
            "INSERT INTO runtime_task_runs "
            "(run_id, task_id, attempt, status, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "r-ts",
                "t-ts2",
                1,
                "completed",
                "2026-06-01T10:00:00Z",
                "2026-06-01T10:05:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO runtime_task_events "
            "(event_id, task_id, kind, severity, title, summary, created_at, "
            " acknowledged_at, injected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "e-ts",
                "t-ts2",
                "status_change",
                "info",
                "Started",
                "Task began processing",
                "2026-06-01T10:00:00Z",
                "2026-06-01T10:05:00Z",
                "2026-06-01T10:06:00Z",
            ),
        )
        run_row = conn.execute(
            "SELECT started_at, completed_at FROM runtime_task_runs WHERE run_id = ?",
            ("r-ts",),
        ).fetchone()
        assert run_row["started_at"] == "2026-06-01T10:00:00Z"
        assert run_row["completed_at"] == "2026-06-01T10:05:00Z"

        event_row = conn.execute(
            "SELECT created_at, acknowledged_at, injected_at "
            "FROM runtime_task_events WHERE event_id = ?",
            ("e-ts",),
        ).fetchone()
        assert event_row["created_at"] == "2026-06-01T10:00:00Z"
        assert event_row["acknowledged_at"] == "2026-06-01T10:05:00Z"
        assert event_row["injected_at"] == "2026-06-01T10:06:00Z"

    @staticmethod
    def _insert_minimal_task(conn: sqlite3.Connection, task_id: str) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# Insert required fields
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """Inserting into runtime_tasks requires certain fields; defaults apply."""

    def test_minimal_insert_succeeds(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t-min", "test", "pending", '{"key": "val"}', "2026-06-01T00:00:00", "2026-06-01T00:00:00"),
        )
        row = conn.execute(
            "SELECT * FROM runtime_tasks WHERE task_id = ?", ("t-min",)
        ).fetchone()
        assert row["task_id"] == "t-min"
        assert row["kind"] == "test"
        assert row["status"] == "pending"
        assert row["payload_json"] == '{"key": "val"}'
        assert row["attempts"] == 0, "attempts should default to 0"
        assert row["max_attempts"] == 8, "max_attempts should default to 8"
        assert row["failure_count"] == 0, "failure_count should default to 0"
        assert row["dedupe_key"] is None
        assert row["parent_task_id"] is None
        assert row["source_session_id"] is None
        assert row["result_json"] is None
        assert row["error_json"] is None
        assert row["run_after"] is None
        assert row["lease_owner"] is None
        assert row["lease_expires_at"] is None
        assert row["started_at"] is None
        assert row["completed_at"] is None

    def test_insert_with_all_optional_fields(
        self, conn: sqlite3.Connection
    ) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks ("
            "  task_id, kind, status, payload_json, result_json, error_json,"
            "  run_after, attempts, max_attempts, failure_count, parent_task_id,"
            "  source_session_id, dedupe_key, lease_owner, lease_expires_at,"
            "  created_at, updated_at, started_at, completed_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "t-full",
                "download",
                "completed",
                '{"url": "https://example.com/torrent"}',
                '{"success": true}',
                None,
                "2026-06-01T00:00:00",
                3,
                5,
                2,
                None,
                "session-abc",
                "dedupe:torrent-xyz",
                "worker-1",
                "2026-06-01T01:00:00",
                "2026-06-01T00:00:00",
                "2026-06-01T02:00:00",
                "2026-06-01T00:30:00",
                "2026-06-01T01:30:00",
            ),
        )
        row = conn.execute(
            "SELECT * FROM runtime_tasks WHERE task_id = ?", ("t-full",)
        ).fetchone()
        assert row["kind"] == "download"
        assert row["status"] == "completed"
        assert row["payload_json"] == '{"url": "https://example.com/torrent"}'
        assert row["result_json"] == '{"success": true}'
        assert row["error_json"] is None
        assert row["run_after"] == "2026-06-01T00:00:00"
        assert row["attempts"] == 3
        assert row["max_attempts"] == 5
        assert row["failure_count"] == 2
        assert row["parent_task_id"] is None
        assert row["source_session_id"] == "session-abc"
        assert row["dedupe_key"] == "dedupe:torrent-xyz"
        assert row["lease_owner"] == "worker-1"
        assert row["lease_expires_at"] == "2026-06-01T01:00:00"
        assert row["created_at"] == "2026-06-01T00:00:00"
        assert row["updated_at"] == "2026-06-01T02:00:00"
        assert row["started_at"] == "2026-06-01T00:30:00"
        assert row["completed_at"] == "2026-06-01T01:30:00"

    def test_insert_missing_required_column_raises(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO runtime_tasks (task_id, status, payload_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("t-miss", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            )


# ---------------------------------------------------------------------------
# Status transitions via SQL (schema-level only)
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    """Status is a free-text TEXT column at the schema level.

    The schema does not enforce a CHECK constraint on status; invalid values
    are accepted by SQLite and must be caught at the application layer.
    These tests document and verify that behaviour.
    """

    def test_arbitrary_status_accepted(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t-any", "test", "some_random_status", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        row = conn.execute(
            "SELECT status FROM runtime_tasks WHERE task_id = ?", ("t-any",)
        ).fetchone()
        assert row["status"] == "some_random_status"

    def test_status_can_be_updated(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t-upd", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "UPDATE runtime_tasks SET status = ? WHERE task_id = ?",
            ("running", "t-upd"),
        )
        row = conn.execute(
            "SELECT status FROM runtime_tasks WHERE task_id = ?", ("t-upd",)
        ).fetchone()
        assert row["status"] == "running"

        conn.execute(
            "UPDATE runtime_tasks SET status = ? WHERE task_id = ?",
            ("completed", "t-upd"),
        )
        row = conn.execute(
            "SELECT status FROM runtime_tasks WHERE task_id = ?", ("t-upd",)
        ).fetchone()
        assert row["status"] == "completed"

    def test_runs_and_events_also_accept_arbitrary_status(
        self, conn: sqlite3.Connection
    ) -> None:
        self._insert_minimal_task(conn, "t-arbitrary")
        conn.execute(
            "INSERT INTO runtime_task_runs "
            "(run_id, task_id, attempt, status, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("r-arb", "t-arbitrary", 1, "custom_run_status", "2026-01-01T00:00:00"),
        )
        row = conn.execute(
            "SELECT status FROM runtime_task_runs WHERE run_id = ?", ("r-arb",)
        ).fetchone()
        assert row["status"] == "custom_run_status"

    @staticmethod
    def _insert_minimal_task(conn: sqlite3.Connection, task_id: str) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )


# ---------------------------------------------------------------------------
# parent_task_id self-reference
# ---------------------------------------------------------------------------


class TestParentTaskSelfReference:
    """parent_task_id can reference another task in the same table."""

    def test_valid_parent_reference(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("t-parent", "download", "completed", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
            "created_at, updated_at, parent_task_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t-child", "download", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "t-parent"),
        )
        row = conn.execute(
            "SELECT parent_task_id FROM runtime_tasks WHERE task_id = ?",
            ("t-child",),
        ).fetchone()
        assert row["parent_task_id"] == "t-parent"

    def test_invalid_parent_reference_raises(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO runtime_tasks (task_id, kind, status, payload_json, "
                "created_at, updated_at, parent_task_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("t-orphan", "test", "pending", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "no-such-task"),
            )
