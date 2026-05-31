"""Dedicated tests for the HelloAgents-backed runner.

These verify behavioral parity with the LangGraph runner, approval guards,
and persistence. They do not require real M-Team/qB credentials — adapters
are faked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.adapters.mteam import MTeamAdapter
from app.adapters.qbittorrent import QBittorrentAdapter
from app.agent_runtime.keyword import KeywordExtractor
from app.agent_runtime.runner import (
    HelloAgentWorkflowRunner,
    _build_confirmation_step,
    _execute_download_step,
    _make_envelope,
)
from app.agent_runtime.state import WorkflowStatus
from app.agent_runtime.tools import MTeamSearchTool, QBAddTorrentTool
from app.api.chat_routes import WorkflowRunner
from app.config import Settings
from app.domain.models import ConfirmationPayload, ResourceCandidate
from hello_agents.runtime.workflow import SequentialWorkflow
from hello_agents.tools.permissions import ToolPermission
from hello_agents.tools.response import ToolResponse, ToolStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMTeamAdapter(MTeamAdapter):
    """Returns canned search results without hitting the network."""

    def __init__(self) -> None:
        pass

    def search_torrents_by_keyword(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        return [
            {"id": 123, "title": "Test Movie 2024", "seeders": 10, "size": "10 GiB", "size_bytes": 10737418240},
            {"id": 456, "title": "Test TV Show S01", "seeders": 5, "size": "20 GiB", "size_bytes": 21474836480},
        ]

    def get_torrent_details(self, torrent_id: str) -> dict[str, Any] | None:
        return {"title": f"Detail for {torrent_id}", "id": torrent_id}

    def get_torrent_download_url(self, torrent_id: str) -> str | None:
        return f"https://mteam.local/download/{torrent_id}"

    def is_download_url_torrent(self, url: str) -> bool:
        return bool(url)


class FakeQBAdapter(QBittorrentAdapter):
    """Records add calls without touching a real qB instance."""

    def __init__(self) -> None:
        self._last_add: dict[str, Any] | None = None

    def add_torrent_url(self, *, url: str, category: str, rename: str, tags: list[str], paused: bool) -> dict[str, Any]:
        self._last_add = {"url": url, "category": category, "rename": rename, "tags": tags, "paused": paused}
        return {"ok": True, "status": "submitted_paused", "qb_hash": "fake-hash"}

    def generate_mteam_torrent_name(self, mteam_id: str, detail: dict[str, Any], qb_category: str) -> str:
        return f"{mteam_id}.torrent"

    def login(self) -> None:
        pass


class FakeKeywordExtractor:
    """Returns a fixed keyword without LLM call."""

    def invoke(self, message: str) -> dict[str, str]:
        return {"keyword": message}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_mteam() -> FakeMTeamAdapter:
    return FakeMTeamAdapter()


@pytest.fixture
def fake_qb() -> FakeQBAdapter:
    return FakeQBAdapter()


@pytest.fixture
def runner(fake_mteam, fake_qb, tmp_path, monkeypatch) -> HelloAgentWorkflowRunner:
    db_path = tmp_path / "test.db"
    fake_settings = Settings(
        mteam_base_url="https://mteam.local",
        mteam_api_key="key",
        qb_base_url="https://qb.local",
        qb_username="user",
        qb_password="pass",
        database_path=str(db_path),
    )
    monkeypatch.setattr("app.agent_runtime.runner.get_settings", lambda: fake_settings)
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)
    r = HelloAgentWorkflowRunner(mteam_adapter=fake_mteam, qb_adapter=fake_qb)
    r._keyword_extractor = FakeKeywordExtractor()  # type: ignore[assignment]
    return r


# ---------------------------------------------------------------------------
# Unit: tool permissions
# ---------------------------------------------------------------------------


class TestToolPermissions:
    def test_default_permission_is_side_effect(self):
        from hello_agents.tools.base import Tool

        class AnyTool(Tool):
            def get_parameters(self):
                return []

            def run(self, parameters):
                return ToolResponse.success(text="ok")

        tool = AnyTool(name="test", description="test")
        assert tool.permission == ToolPermission.SIDE_EFFECT

    def test_readonly_tool_declared_explicitly(self, fake_mteam):
        tool = MTeamSearchTool(fake_mteam)
        assert tool.permission == ToolPermission.READONLY

    def test_side_effect_tool_declared_explicitly(self, fake_mteam, fake_qb):
        tool = QBAddTorrentTool(fake_mteam, fake_qb)
        assert tool.permission == ToolPermission.SIDE_EFFECT


# ---------------------------------------------------------------------------
# Unit: search tool
# ---------------------------------------------------------------------------


class TestMTeamSearchTool:
    def test_returns_candidates_in_data(self, fake_mteam):
        tool = MTeamSearchTool(fake_mteam)
        response = tool.run({"keyword": "test"})
        assert response.status == ToolStatus.SUCCESS
        assert len(response.data["candidates"]) == 2

    def test_parses_candidate_fields(self, fake_mteam):
        tool = MTeamSearchTool(fake_mteam)
        response = tool.run({"keyword": "test"})
        c = ResourceCandidate(**response.data["candidates"][0])
        assert c.id == "123"
        assert c.source == "mteam"

    def test_missing_keyword_returns_error(self, fake_mteam):
        tool = MTeamSearchTool(fake_mteam)
        response = tool.run({"keyword": ""})
        assert response.status == ToolStatus.ERROR


# ---------------------------------------------------------------------------
# Unit: SequentialWorkflow
# ---------------------------------------------------------------------------


class TestSequentialWorkflow:
    def test_runs_steps_in_order(self):
        calls: list[str] = []

        def step_a(env):
            calls.append("a")
            return env

        def step_b(env):
            calls.append("b")
            return env

        wf = SequentialWorkflow([step_a, step_b])
        wf.run({"status": "in_progress"})
        assert calls == ["a", "b"]

    def test_halts_at_awaiting_approval(self):
        def step_a(env):
            env["status"] = WorkflowStatus.AWAITING_APPROVAL.value
            return env

        def step_b(env):
            env["called"] = True
            return env

        wf = SequentialWorkflow([step_a, step_b])
        result = wf.run({"status": "in_progress"})
        assert result["status"] == WorkflowStatus.AWAITING_APPROVAL.value
        assert "called" not in result

    def test_halts_at_error(self):
        def step_a(env):
            env["status"] = WorkflowStatus.ERROR.value
            return env

        def step_b(env):
            env["called"] = True
            return env

        wf = SequentialWorkflow([step_a, step_b])
        result = wf.run({"status": "in_progress"})
        assert result["status"] == WorkflowStatus.ERROR.value
        assert "called" not in result

    def test_requires_at_least_one_step(self):
        with pytest.raises(ValueError):
            SequentialWorkflow([])


# ---------------------------------------------------------------------------
# Unit: workflow steps
# ---------------------------------------------------------------------------


class TestBuildConfirmationStep:
    def test_produces_awaiting_approval(self, fake_mteam):
        candidates_dicts = [
            {"id": "1", "title": "Movie A", "media_type": "movie", "resolution": "1080p", "seeders": 10, "size": "5 GiB", "source": "mteam"},
            {"id": "2", "title": "Movie B", "media_type": "movie", "resolution": "2160p", "seeders": 5, "size": "10 GiB", "source": "mteam"},
        ]
        envelope = _make_envelope("s1", "test")
        envelope["domain"]["search_results"] = candidates_dicts
        envelope = _build_confirmation_step()(envelope)

        assert envelope["status"] == WorkflowStatus.AWAITING_APPROVAL.value
        assert envelope["pending_approval"] is not None
        assert envelope["pending_approval"]["tool_name"] == "qb_add_torrent"
        assert envelope["pending_approval"]["resolved"] is False
        cf = envelope["domain"]["confirmation_payload"]
        assert isinstance(cf, dict)
        assert cf["recommended_result_id"] == "1"

    def test_empty_results_returns_awaiting_approval_with_empty_payload(self):
        envelope = _make_envelope("s1", "test")
        envelope["domain"]["search_results"] = []
        envelope = _build_confirmation_step()(envelope)
        assert envelope["status"] == WorkflowStatus.AWAITING_APPROVAL.value
        cf = envelope["domain"]["confirmation_payload"]
        assert isinstance(cf, dict)
        assert cf["recommended_result_id"] is None
        assert cf["results"] == []
        assert envelope["pending_approval"] is not None
        assert envelope["pending_approval"]["confirmation_payload"]["results"] == []


class TestExecuteDownloadStep:
    def test_executes_download_and_completes(self, fake_mteam, fake_qb):
        tool = QBAddTorrentTool(fake_mteam, fake_qb)
        envelope = _make_envelope("s1", "test")
        confirmation = ConfirmationPayload(
            summary="ok",
            recommended_result_id="123",
            results=[],
            selected_result_id="123",
        )
        envelope["domain"]["confirmation_payload"] = confirmation
        envelope = _execute_download_step(tool)(envelope)

        assert envelope["status"] == WorkflowStatus.COMPLETED.value
        receipt = envelope["domain"]["receipt"]
        assert receipt is not None
        assert receipt["qb_hash"] == "fake-hash"
        assert envelope["pending_approval"]["resolved"] is True

    def test_no_selected_id_returns_error(self, fake_mteam, fake_qb):
        tool = QBAddTorrentTool(fake_mteam, fake_qb)
        envelope = _make_envelope("s1", "test")
        confirmation = ConfirmationPayload(summary="ok", recommended_result_id=None, results=[])
        envelope["domain"]["confirmation_payload"] = confirmation
        envelope = _execute_download_step(tool)(envelope)

        assert envelope["status"] == WorkflowStatus.ERROR.value


# ---------------------------------------------------------------------------
# Integration: runner API
# ---------------------------------------------------------------------------


class TestHelloAgentWorkflowRunnerChat:
    def test_run_chat_returns_awaiting_confirmation(self, runner):
        result = runner.run_chat("s1", "test movie")
        assert result["session_id"] == "s1"
        assert result["status"] == "awaiting_confirmation"
        assert result["confirmation_payload"] is not None
        assert result["error"] is None

    def test_run_chat_persists_session(self, runner, tmp_path):
        runner.run_chat("s1", "test movie")
        loaded = runner._session_store.load("s1")
        assert loaded is not None
        assert loaded["status"] == WorkflowStatus.AWAITING_APPROVAL.value


class TestHelloAgentWorkflowRunnerConfirm:
    def test_approve_completes_download(self, runner):
        chat_result = runner.run_chat("s2", "test movie")
        confirmation = chat_result["confirmation_payload"]
        result = runner.run_confirm(
            "s2", action="approve", confirmation_payload=confirmation
        )
        assert result["status"] == "completed"
        assert result["receipt"] is not None

    def test_cancel_returns_canceled(self, runner):
        runner.run_chat("s3", "test movie")
        result = runner.run_confirm("s3", action="cancel", confirmation_payload=None)
        assert result["status"] == "canceled"

    def test_missing_confirmation_returns_error(self, runner):
        result = runner.run_confirm("s5", action="approve", confirmation_payload=None)
        assert result["status"] == "error"

    def test_approval_persists_across_roundtrip(self, runner):
        runner.run_chat("s6", "test movie")
        # Reload session fresh
        loaded = runner._session_store.load("s6")
        assert loaded is not None
        assert loaded["pending_approval"] is not None
        assert loaded["pending_approval"]["resolved"] is False


class TestApprovalGuard:
    def test_approve_without_pending_session_is_rejected(self, runner):
        result = runner.run_confirm("no-session", action="approve", confirmation_payload={"summary": "x"})
        assert result["status"] == "error"
        assert "no pending approval" in str(result.get("error", "")).lower()

    def test_double_approve_is_rejected(self, runner):
        chat = runner.run_chat("s-double", "test movie")
        runner.run_confirm("s-double", action="approve", confirmation_payload=chat["confirmation_payload"])
        # Second approve must fail — already resolved.
        result = runner.run_confirm("s-double", action="approve", confirmation_payload=chat["confirmation_payload"])
        assert result["status"] == "error"
        assert "already been resolved" in str(result.get("error", "")).lower() or "not awaiting approval" in str(result.get("error", "")).lower()


# ---------------------------------------------------------------------------
# Runner import smoke test
# ---------------------------------------------------------------------------


class TestRunnerImport:
    def test_can_import_default_runner(self):
        from app.api.chat_routes import _build_default_runner

        _ = _build_default_runner  # import coverage — actual instantiation needs adapters



class TestRunnerProtocol:
    def test_helloagent_runner_satisfies_protocol(self, runner):
        """HelloAgentWorkflowRunner structurally matches WorkflowRunner."""
        assert hasattr(runner, "run_chat")
        assert hasattr(runner, "run_confirm")
        assert callable(runner.run_chat)
        assert callable(runner.run_confirm)


# ---------------------------------------------------------------------------
# KeywordExtractor: function-calling with tool_choice="required"
# ---------------------------------------------------------------------------


class TestKeywordExtractor:
    """Verify KeywordExtractor invokes the LLM with tool_choice='auto' for DeepSeek thinking-mode compatibility."""

    def test_invoke_returns_keyword_from_tool_call(self, monkeypatch):
        """KeywordExtractor parses keyword from a function-calling response."""
        captured_tool_choice: dict | str | None = None

        class _MockLLM:
            def __init__(self, model=None, api_key=None, base_url=None, **kwargs):
                pass

            def invoke_with_tools(self, messages, tools, tool_choice=None, **kwargs):
                nonlocal captured_tool_choice
                captured_tool_choice = tool_choice
                from hello_agents.core.llm_response import LLMToolResponse, ToolCall

                return LLMToolResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="extract_keyword",
                            arguments='{"keyword": "Dune 2021"}',
                        )
                    ],
                    model="test-model",
                )

        monkeypatch.setattr(
            "hello_agents.core.llm.HelloAgentsLLM", _MockLLM
        )

        from app.agent_runtime.keyword import KeywordExtractor

        extractor = KeywordExtractor()
        result = extractor.invoke("I want to watch Dune 2021")

        assert result == {"keyword": "Dune 2021"}
        assert captured_tool_choice == "auto"
