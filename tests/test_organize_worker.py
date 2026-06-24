"""Tests for the OrganizeWorkerAgent (app.agent.organize_worker).

Exercises:
- Agent builder creates a registry with the correct tool set
- Agent builder applies the correct Filter and Gate
- _extract_result parses observations correctly for success, failure, error
- Dynamic Gate state is updated by the skill_load wrapper
- Edge cases: no observations, no last_result, no moves, skill not loaded
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.organize_worker import (
    OrganizeWorkerAgent,
    OrganizeWorkerResult,
    _OrganizeSkillTool,
    _SkillGateState,
)
from hello_agents.tools import Filter, Gate, GateResult, ToolCall, ToolRegistry, ToolStatus
from hello_agents.tools.response import ToolResponse


# ---------------------------------------------------------------------------
# Result extraction tests
# ---------------------------------------------------------------------------


class FakeObservation:
    """Minimal stand-in for a tool observation in ToolCallingLoopResult."""

    def __init__(
        self,
        tool_name: str,
        status: ToolStatus = ToolStatus.SUCCESS,
        text: str = "",
        arguments: dict[str, Any] | None = None,
        gate_result: str | None = None,
        gate_reason: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.response = ToolResponse(
            status=status,
            text=text,
            data={},
        )
        self.arguments = arguments or {}
        self.gate_result = gate_result
        self.gate_reason = gate_reason
        self.tool_call_id = "call-1"


class FakeLoopResult:
    """Minimal stand-in for ToolCallingLoopResult."""

    def __init__(self, observations: list[FakeObservation]) -> None:
        self.tool_observations = observations
        self.status: Any = "success"
        self.steps = len(observations)
        self.final_answer = ""
        self.paused_loop = None


class FakeAgent:
    """Minimal agent with a last_result."""

    def __init__(self, observations: list[FakeObservation]) -> None:
        self.last_result = FakeLoopResult(observations)


# ---------------------------------------------------------------------------


class TestExtractResult:
    """_extract_result produces correct OrganizeWorkerResult from observations."""

    def test_no_last_result(self) -> None:
        agent = FakeAgent([])
        agent.last_result = None
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "")
        assert result.status == "error"
        assert "Agent produced no result" in result.summary

    def test_no_observations(self) -> None:
        agent = FakeAgent([])
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "")
        assert result.status == "error"
        assert "No tool calls were made" in result.summary

    def test_skill_not_loaded(self) -> None:
        obs = [
            FakeObservation("mcp_filesystem_list_directory", arguments={"path": "/a"}),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "scanned directory")
        assert result.status == "failed"
        assert "never loaded" in result.issues[0]

    def test_skill_loaded_but_no_moves(self) -> None:
        obs = [
            FakeObservation(
                "skill_load",
                arguments={"name": "renaming-rules"},
            ),
            FakeObservation("mcp_filesystem_list_directory", arguments={"path": "/a"}),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "scanned, nothing to do")
        assert result.status == "failed"
        assert "No files were moved" in result.issues[0]

    def test_full_success(self) -> None:
        obs = [
            FakeObservation(
                "skill_load",
                arguments={"name": "renaming-rules"},
            ),
            FakeObservation("mcp_filesystem_list_directory", arguments={"path": "/a"}),
            FakeObservation(
                "mcp_filesystem_create_directory",
                arguments={"path": "/影视/电影/The.Movie.2024"},
            ),
            FakeObservation(
                "mcp_filesystem_move_file",
                arguments={
                    "source": "/a/movie.mkv",
                    "destination": "/影视/电影/The.Movie.2024/The.Movie.2024.mkv",
                },
            ),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "整理完成，移动了1个文件")
        assert result.status == "success"
        assert result.moved_count == 1
        assert "The.Movie.2024" in result.destination
        assert result.tool_calls == 4

    def test_partial_moves_with_some_errors(self) -> None:
        obs = [
            FakeObservation(
                "skill_load",
                arguments={"name": "renaming-rules"},
            ),
            FakeObservation(
                "mcp_filesystem_move_file",
                arguments={"source": "/a/f1", "destination": "/b/f1"},
            ),
            FakeObservation(
                "mcp_filesystem_move_file",
                status=ToolStatus.ERROR,
                text="Destination already exists",
                arguments={"source": "/a/f2", "destination": "/b/f2"},
            ),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "partial success")
        assert result.status == "success"
        assert result.moved_count == 1
        assert len(result.issues) == 1
        assert "Destination already exists" in result.issues[0]

    def test_gate_denial_appears_in_issues(self) -> None:
        obs = [
            FakeObservation(
                "skill_load",
                arguments={"name": "renaming-rules"},
            ),
            FakeObservation(
                "mcp_filesystem_move_file",
                arguments={"source": "/a/f", "destination": "/b/f"},
            ),
            FakeObservation(
                "mcp_filesystem_create_directory",
                arguments={"path": "/x/y"},
                gate_result="DENY",
                gate_reason="Skill not loaded",
            ),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "done")
        assert result.status == "success"
        assert any("DENIED" in i for i in result.issues)

    def test_answer_truncated_to_500_chars(self) -> None:
        long_answer = "x" * 1000
        obs = [
            FakeObservation(
                "skill_load",
                arguments={"name": "renaming-rules"},
            ),
            FakeObservation(
                "mcp_filesystem_move_file",
                arguments={"source": "/a/f", "destination": "/b/f"},
            ),
        ]
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, long_answer)
        assert len(result.summary) <= 500

    def test_tool_calls_count(self) -> None:
        obs = [FakeObservation("mcp_filesystem_list_directory", arguments={"path": "/a"}) for _ in range(5)]
        # Make skill_load appear so status is "failed" but not "error"
        obs.insert(0, FakeObservation("skill_load", arguments={"name": "renaming-rules"}))
        agent = FakeAgent(obs)
        worker = OrganizeWorkerAgent()
        result = worker._extract_result(agent, "")
        assert result.tool_calls == 6


# ---------------------------------------------------------------------------
# Agent builder tests
# ---------------------------------------------------------------------------


class TestAgentBuilder:
    """OrganizeWorkerAgent._build_agent creates a properly configured agent."""

    def test_build_agent_registers_correct_tools(self) -> None:
        worker = OrganizeWorkerAgent()
        agent = worker._build_agent()
        assert agent.tool_registry is not None

        tool_names = agent.tool_registry.list_tools()
        # Must contain the core tools.
        assert "skill_load" in tool_names
        assert "tmdb_search" in tool_names
        assert "tmdb_details" in tool_names
        assert "tavily_search" in tool_names
        assert "qb_get_torrent" in tool_names
        assert "qb_control_torrent" in tool_names

        # Must have at least the read-only MCP tools when MCP pool is active.
        # (MCP pool may be None in test, so these may be absent)
        if "mcp_filesystem_list_directory" in tool_names:
            assert "mcp_filesystem_get_file_info" in tool_names
            assert "mcp_filesystem_create_directory" in tool_names
            assert "mcp_filesystem_move_file" in tool_names

        # Must NOT include unrelated tools.
        assert "mteam_search" not in tool_names
        assert "qb_add_torrent" not in tool_names

    def test_filter_allows_only_organize_tools(self) -> None:
        worker = OrganizeWorkerAgent()
        agent = worker._build_agent()
        assert agent.tool_filter is not None

        allowed = [
            "skill_load",
            "tmdb_search",
            "tmdb_details",
            "tavily_search",
            "qb_get_torrent",
            "qb_control_torrent",
            "mcp_filesystem_list_directory",
            "mcp_filesystem_create_directory",
        ]
        denied = [
            "mteam_search",
            "qb_add_torrent",
            "current_time",
        ]

        for name in allowed:
            assert agent.tool_filter._predicate(name), f"{name} should be allowed"

        for name in denied:
            assert not agent.tool_filter._predicate(name), f"{name} should be denied"

    def test_gate_denies_mutation_before_skill_loaded(self) -> None:
        worker = OrganizeWorkerAgent()
        agent = worker._build_agent()
        assert agent.tool_gate is not None

        call_create = ToolCall(
            tool_name="mcp_filesystem_create_directory",
            params={"path": "/a/b"},
        )
        call_move = ToolCall(
            tool_name="mcp_filesystem_move_file",
            params={"source": "/a/f", "destination": "/b/f"},
        )
        call_list = ToolCall(
            tool_name="mcp_filesystem_list_directory",
            params={"path": "/a"},
        )

        result_create = agent.tool_gate.check(call_create)
        result_move = agent.tool_gate.check(call_move)
        result_list = agent.tool_gate.check(call_list)

        assert result_create == GateResult.DENY
        assert result_move == GateResult.DENY
        assert result_list == GateResult.ALLOW


# ---------------------------------------------------------------------------
# Dynamic Gate state
# ---------------------------------------------------------------------------


class TestSkillGateState:
    """_OrganizeSkillTool updates _SkillGateState on successful load."""

    def test_skill_load_updates_gate_state(self) -> None:
        gate_state = _SkillGateState()
        assert gate_state.skill_loaded is False

        # Create a real SkillTool-like mock.
        from hello_agents.skills.loader import SkillLoader
        from pathlib import Path

        skills_dir = Path(__file__).resolve().parents[1] / "skills"
        loader = SkillLoader(skills_dir=skills_dir)

        from hello_agents.tools.builtin.skill_tool import SkillTool
        wrapped = SkillTool(loader)
        wrapper = _OrganizeSkillTool(wrapped, gate_state)

        result = wrapper.run({"name": "renaming-rules"})
        assert result.status == ToolStatus.SUCCESS
        assert gate_state.skill_loaded is True

    def test_skill_load_unknown_skill_does_not_update_state(self) -> None:
        gate_state = _SkillGateState()
        from hello_agents.skills.loader import SkillLoader
        from pathlib import Path

        skills_dir = Path(__file__).resolve().parents[1] / "skills"
        loader = SkillLoader(skills_dir=skills_dir)

        from hello_agents.tools.builtin.skill_tool import SkillTool
        wrapped = SkillTool(loader)
        wrapper = _OrganizeSkillTool(wrapped, gate_state)

        result = wrapper.run({"name": "nonexistent-skill"})
        assert result.status == ToolStatus.ERROR
        assert gate_state.skill_loaded is False

    def test_gate_clears_after_skill_loaded(self) -> None:
        gate_state = _SkillGateState()
        gate = Gate(deny=[
            lambda call, st=gate_state: (
                call.tool_name in ("mcp_filesystem_create_directory",)
                and not st.skill_loaded
            ),
        ])

        call = ToolCall(tool_name="mcp_filesystem_create_directory", params={"path": "/a"})

        # Before load: denied.
        assert gate.check(call) == GateResult.DENY

        gate_state.skill_loaded = True

        # After load: allowed.
        assert gate.check(call) == GateResult.ALLOW


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Agent run failure paths."""

    def test_run_raises_no_mcp_pool_does_not_crash(self) -> None:
        """Agent building should not crash when MCP pool is None."""
        worker = OrganizeWorkerAgent()
        agent = worker._build_agent()
        assert agent is not None

    def test_system_prompt_contains_key_instructions(self) -> None:
        worker = OrganizeWorkerAgent()
        agent = worker._build_agent()
        prompt = agent.system_prompt or ""
        assert "renaming-rules" in prompt
        assert "skill_load" in prompt
        # Token-saving guidance — the prompt warns about directory_tree
        assert "directory_tree" in prompt
        assert "list_directory" in prompt
        assert "get_file_info" in prompt
        # Detailed workflow (create_directory, move_file, tmdb_search, etc.)
        # lives in the renaming-rules SKILL.md — loaded by skill_load on first step.
