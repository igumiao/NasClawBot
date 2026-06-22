"""Tests for the OperationJournal (app.runtime.organize_journal).

Exercises:
- record_start / record_success / record_failure / record_already_applied
- is_applied / list_applied / list_all / clear
- Thread safety (concurrent appends)
- Persistence across journal instances
- Edge cases: empty file, missing file, corrupt file
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.domain.runtime_tasks import FilesystemOperationRecord
from app.runtime.organize_journal import OperationJournal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_path(tmp_path: Path) -> str:
    return str(tmp_path / "organize-journal.json")


@pytest.fixture
def journal(journal_path: str) -> OperationJournal:
    return OperationJournal(journal_path)


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------


class TestRecordLifecycle:
    """Happy-path: start -> succeed/fail/already_applied."""

    def test_record_start_creates_entry(self, journal: OperationJournal) -> None:
        rec = journal.record_start("op-1", "create_directory", {"path": "/a/b"})
        assert rec.operation_id == "op-1"
        assert rec.tool_name == "create_directory"
        assert rec.arguments == {"path": "/a/b"}
        assert rec.status == "started"
        assert rec.started_at is not None
        assert rec.completed_at is None

    def test_record_start_then_success(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a/b"})
        journal.record_success("op-1", {"ok": True})
        assert journal.is_applied("op-1")
        rec = journal.list_all()[0]
        assert rec.status == "succeeded"
        assert rec.completed_at is not None
        assert rec.result == {"ok": True}

    def test_record_start_then_failure(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "move_file", {"source": "/a", "destination": "/b"})
        journal.record_failure("op-1", {"code": "NOT_FOUND"})
        assert not journal.is_applied("op-1")
        rec = journal.list_all()[0]
        assert rec.status == "failed"
        assert rec.completed_at is not None

    def test_record_start_then_already_applied(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_already_applied("op-1")
        assert journal.is_applied("op-1")
        rec = journal.list_all()[0]
        assert rec.status == "already_applied"

    def test_multiple_operations(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_start("op-2", "move_file", {"source": "/a/f", "destination": "/b/f"})
        journal.record_success("op-1")
        journal.record_success("op-2")
        assert len(journal.list_all()) == 2
        assert len(journal.list_applied()) == 2

    def test_partial_success(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_start("op-2", "move_file", {"source": "/a/f", "destination": "/b/f"})
        journal.record_success("op-1")
        journal.record_failure("op-2", {"code": "IO_ERROR"})
        assert len(journal.list_applied()) == 1
        assert len(journal.list_all()) == 2

    def test_clear_removes_all(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_success("op-1")
        assert len(journal.list_all()) == 1
        journal.clear()
        assert len(journal.list_all()) == 0


# ---------------------------------------------------------------------------
# Idempotent queries
# ---------------------------------------------------------------------------


class TestQueryHelpers:
    """is_applied and list_applied with missing / partial records."""

    def test_is_applied_with_nonexistent_id(self, journal: OperationJournal) -> None:
        assert journal.is_applied("nonexistent") is False

    def test_is_applied_with_started_status(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        assert journal.is_applied("op-1") is False

    def test_is_applied_with_failed_status(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_failure("op-1")
        assert journal.is_applied("op-1") is False

    def test_is_applied_after_success(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_success("op-1")
        assert journal.is_applied("op-1") is True

    def test_list_applied_empty(self, journal: OperationJournal) -> None:
        assert journal.list_applied() == []

    def test_list_applied_filters_out_failed(self, journal: OperationJournal) -> None:
        journal.record_start("op-1", "create_directory", {"path": "/a"})
        journal.record_start("op-2", "move_file", {"source": "/a/f", "destination": "/b/f"})
        journal.record_success("op-1")
        journal.record_failure("op-2")
        applied = journal.list_applied()
        assert len(applied) == 1
        assert applied[0].operation_id == "op-1"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Empty files, missing files, corrupt data."""

    def test_no_file_on_disk(self, journal_path: str) -> None:
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_empty_json_array(self, journal_path: str) -> None:
        Path(journal_path).write_text("[]", encoding="utf-8")
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_corrupt_json_returns_empty(self, journal_path: str) -> None:
        Path(journal_path).write_text("{corrupt", encoding="utf-8")
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_empty_file_returns_empty(self, journal_path: str) -> None:
        Path(journal_path).write_text("", encoding="utf-8")
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_whitespace_only_file(self, journal_path: str) -> None:
        Path(journal_path).write_text("   \n  ", encoding="utf-8")
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_not_a_list(self, journal_path: str) -> None:
        Path(journal_path).write_text('{"key": "value"}', encoding="utf-8")
        journal = OperationJournal(journal_path)
        assert journal.list_all() == []

    def test_update_nonexistent_does_not_crash(self, journal: OperationJournal) -> None:
        journal.record_success("nonexistent")
        assert journal.list_all() == []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Data survives across journal instances (same file)."""

    def test_data_persists_across_reload(self, journal_path: str) -> None:
        journal_a = OperationJournal(journal_path)
        journal_a.record_start("op-1", "create_directory", {"path": "/a"})
        journal_a.record_success("op-1")
        journal_b = OperationJournal(journal_path)
        assert len(journal_b.list_all()) == 1
        assert journal_b.is_applied("op-1")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Concurrent appends do not lose data."""

    def test_concurrent_appends(self, journal_path: str) -> None:
        journal = OperationJournal(journal_path)
        n_threads = 10
        events_per_thread = 5

        def worker(prefix: str) -> None:
            for i in range(events_per_thread):
                op_id = f"{prefix}-{i}"
                journal.record_start(op_id, "create_directory", {"path": f"/{op_id}"})
                journal.record_success(op_id)

        threads = [
            threading.Thread(target=worker, args=(f"t{t}",))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = journal.list_all()
        assert len(records) == n_threads * events_per_thread
        assert len(journal.list_applied()) == n_threads * events_per_thread
