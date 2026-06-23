"""Tests for ListTaskEventsTool."""

from datetime import datetime, timezone

import pytest

from app.agent.runner import current_agent_session_id
from app.domain.runtime_tasks import TaskEvent, TaskEventSeverity
from app.runtime.store import RuntimeTaskStore
from app.storage.db import ensure_schema
from app.tools.list_task_events import ListTaskEventsTool
from hello_agents.tools.response import ToolStatus


def _store(tmp_path):
    now = lambda: datetime.now(timezone.utc)
    ids = iter(["ev-1", "ev-2", "ev-3", "ev-4", "ev-5"])
    db = tmp_path / "tasks.db"
    ensure_schema(db)
    return RuntimeTaskStore(db, now, lambda: next(ids))


def _create_events(store, session_id):
    """Create a mix of event types for testing."""
    now = datetime.now(timezone.utc).isoformat()
    events = [
        TaskEvent(
            event_id="ev-1",
            task_id="task-1",
            source_session_id=session_id,
            kind="download_completed",
            severity=TaskEventSeverity.SUCCESS,
            title="下载完成",
            summary="种子 Movie 已下载完成",
            created_at=now,
        ),
        TaskEvent(
            event_id="ev-2",
            task_id="task-2",
            source_session_id=session_id,
            kind="organize_completed",
            severity=TaskEventSeverity.SUCCESS,
            title="整理完成",
            summary="文件已整理到 /media/Movie",
            created_at=now,
        ),
        TaskEvent(
            event_id="ev-3",
            task_id="task-3",
            source_session_id=session_id,
            kind="task_failed",
            severity=TaskEventSeverity.ERROR,
            title="任务失败",
            summary="下载监视失败",
            created_at=now,
        ),
        TaskEvent(
            event_id="ev-4",
            task_id="task-4",
            source_session_id="other-session",
            kind="download_completed",
            severity=TaskEventSeverity.SUCCESS,
            title="其他会话的下载",
            summary="不应出现在当前会话查询中",
            created_at=now,
        ),
    ]
    for ev in events:
        store.create_event(ev)
    return events


class TestListTaskEventsTool:
    """Unit tests for ListTaskEventsTool."""

    def test_no_session_returns_error(self, tmp_path):
        store = _store(tmp_path)
        tool = ListTaskEventsTool(store)

        # Reset session context
        token = current_agent_session_id.set(None)
        try:
            result = tool.run({})
            assert result.status == ToolStatus.ERROR
            assert result.error_info is not None
            assert result.error_info.get("code") == "NO_SESSION"
        finally:
            current_agent_session_id.reset(token)

    def test_returns_events_for_current_session(self, tmp_path):
        store = _store(tmp_path)
        _create_events(store, "session-1")
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("session-1")
        try:
            result = tool.run({})
            assert result.status == ToolStatus.SUCCESS
            assert result.data["count"] == 3  # 3 events for session-1
            kinds = {e["kind"] for e in result.data["events"]}
            assert kinds == {"download_completed", "organize_completed", "task_failed"}
            # other-session event must not appear
            for e in result.data["events"]:
                assert e["task_id"] != "task-4"
        finally:
            current_agent_session_id.reset(token)

    def test_filter_by_kind(self, tmp_path):
        store = _store(tmp_path)
        _create_events(store, "session-1")
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("session-1")
        try:
            result = tool.run({"kind": "download_completed"})
            assert result.status == ToolStatus.SUCCESS
            assert result.data["count"] == 1
            assert result.data["events"][0]["kind"] == "download_completed"
        finally:
            current_agent_session_id.reset(token)

    def test_filter_by_severity(self, tmp_path):
        store = _store(tmp_path)
        _create_events(store, "session-1")
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("session-1")
        try:
            result = tool.run({"severity": "error"})
            assert result.status == ToolStatus.SUCCESS
            assert result.data["count"] == 1
            assert result.data["events"][0]["severity"] == "error"
        finally:
            current_agent_session_id.reset(token)

    def test_invalid_kind_returns_error(self, tmp_path):
        store = _store(tmp_path)
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("session-1")
        try:
            result = tool.run({"kind": "nonexistent"})
            assert result.status == ToolStatus.ERROR
            assert result.error_info is not None
            assert result.error_info.get("code") == "INVALID_PARAM"
        finally:
            current_agent_session_id.reset(token)

    def test_empty_session_returns_empty(self, tmp_path):
        store = _store(tmp_path)
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("empty-session")
        try:
            result = tool.run({})
            assert result.status == ToolStatus.SUCCESS
            assert result.data["count"] == 0
        finally:
            current_agent_session_id.reset(token)

    def test_limit(self, tmp_path):
        store = _store(tmp_path)
        _create_events(store, "session-1")
        tool = ListTaskEventsTool(store)

        token = current_agent_session_id.set("session-1")
        try:
            result = tool.run({"limit": 1})
            assert result.status == ToolStatus.SUCCESS
            assert result.data["count"] == 1
        finally:
            current_agent_session_id.reset(token)
