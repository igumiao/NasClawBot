"""Test deterministic scoring functions."""

import pytest

from evals.models import (
    AssertStep,
    CallJournalEntry,
    FailedAssertion,
    FailureCategory,
    TrialResult,
    TrialStatus,
)
from evals.scorers import (
    _arguments_match,
    _classify_tool_call,
    _score_status,
    _score_required_calls,
    _score_forbidden_calls,
    _score_exact_call_count,
    _score_ordering,
    _score_recorded_effects,
    _score_final_facts,
    score_trial,
)


class TestArgumentsMatch:
    def test_exact_match(self):
        assert _arguments_match({"a": 1}, {"a": 1, "b": 2})

    def test_nested_match(self):
        assert _arguments_match({"x": {"y": 1}}, {"x": {"y": 1, "z": 2}})

    def test_missing_key(self):
        assert not _arguments_match({"a": 1}, {"b": 2})

    def test_value_mismatch(self):
        assert not _arguments_match({"a": 1}, {"a": 2})

    def test_empty_expected(self):
        assert _arguments_match({}, {"a": 1})


class TestClassifyToolCall:
    def test_read_only(self):
        assert _classify_tool_call("mteam_search") == "read_only"
        assert _classify_tool_call("qb_list_torrents") == "read_only"

    def test_download(self):
        assert _classify_tool_call("qb_add_torrent") == "download"

    def test_control(self):
        assert _classify_tool_call("qb_control_torrent") == "control"

    def test_filesystem(self):
        assert _classify_tool_call("mcp_filesystem_move_file") == "filesystem"

    def test_other(self):
        assert _classify_tool_call("unknown_tool") == "other"


class TestScoreStatus:
    def test_match(self):
        step = AssertStep(kind="assert", status="awaiting_approval")
        assert _score_status(step, "awaiting_approval") == []

    def test_mismatch(self):
        step = AssertStep(kind="assert", status="awaiting_approval")
        failures = _score_status(step, "success")
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.APPROVAL_BEHAVIOR

    def test_no_status_check(self):
        step = AssertStep(kind="assert")
        assert _score_status(step, "success") == []


class TestScoreRequiredCalls:
    def test_all_present(self):
        step = AssertStep(kind="assert", required_calls=[
            {"name": "mteam_search"},
        ])
        tool_calls = [{"tool": "mteam_search", "arguments": {"keyword": "Dune"}}]
        assert _score_required_calls(step, tool_calls) == []

    def test_missing_call(self):
        step = AssertStep(kind="assert", required_calls=[
            {"name": "qb_add_torrent"},
        ])
        failures = _score_required_calls(step, [{"tool": "mteam_search", "arguments": {}}])
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.TOOL_SELECTION

    def test_argument_mismatch(self):
        step = AssertStep(kind="assert", required_calls=[
            {"name": "qb_add_torrent", "arguments": {"torrent_id": "101"}},
        ])
        tool_calls = [{"tool": "qb_add_torrent", "arguments": {"torrent_id": "999"}}]
        failures = _score_required_calls(step, tool_calls)
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.ARGUMENTS

    def test_no_arguments_required(self):
        step = AssertStep(kind="assert", required_calls=[
            {"name": "mteam_search"},
        ])
        # arguments=None means presence-only
        tool_calls = [{"tool": "mteam_search", "arguments": {"keyword": "Dune"}}]
        assert _score_required_calls(step, tool_calls) == []


class TestScoreForbiddenCalls:
    def test_no_forbidden(self):
        step = AssertStep(kind="assert", forbidden_calls=["qb_add_torrent"])
        assert _score_forbidden_calls(step, [{"tool": "mteam_search"}]) == []

    def test_forbidden_found(self):
        step = AssertStep(kind="assert", forbidden_calls=["qb_add_torrent"])
        failures = _score_forbidden_calls(step, [{"tool": "qb_add_torrent"}])
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.TOOL_SELECTION


class TestScoreExactCallCount:
    def test_exact_match(self):
        step = AssertStep(kind="assert", exact_call_count={"mteam_search": 1})
        tool_calls = [{"tool": "mteam_search"}, {"tool": "tmdb_details"}]
        assert _score_exact_call_count(step, tool_calls) == []

    def test_too_many(self):
        step = AssertStep(kind="assert", exact_call_count={"mteam_search": 1})
        tool_calls = [{"tool": "mteam_search"}, {"tool": "mteam_search"}]
        failures = _score_exact_call_count(step, tool_calls)
        assert len(failures) == 1

    def test_too_few(self):
        step = AssertStep(kind="assert", exact_call_count={"mteam_search": 2})
        tool_calls = [{"tool": "mteam_search"}]
        failures = _score_exact_call_count(step, tool_calls)
        assert len(failures) == 1


class TestScoreOrdering:
    def test_correct_order(self):
        step = AssertStep(kind="assert", ordering=[
            {"before": "mteam_search", "after": "qb_add_torrent"},
        ])
        tool_calls = [
            {"tool": "mteam_search"},
            {"tool": "qb_add_torrent", "arguments": {}},
        ]
        assert _score_ordering(step, tool_calls) == []

    def test_wrong_order(self):
        step = AssertStep(kind="assert", ordering=[
            {"before": "mteam_search", "after": "qb_add_torrent"},
        ])
        tool_calls = [
            {"tool": "qb_add_torrent", "arguments": {}},
            {"tool": "mteam_search"},
        ]
        failures = _score_ordering(step, tool_calls)
        assert len(failures) == 1

    def test_missing_tool_skipped(self):
        step = AssertStep(kind="assert", ordering=[
            {"before": "nonexistent", "after": "mteam_search"},
        ])
        assert _score_ordering(step, [{"tool": "mteam_search"}]) == []


class TestScoreRecordedEffects:
    def test_exact_count(self):
        step = AssertStep(kind="assert", recorded_effects=0)
        assert _score_recorded_effects(step, []) == []

    def test_unexpected_effects(self):
        step = AssertStep(kind="assert", recorded_effects=0)
        journal = [CallJournalEntry(sequence=1, kind="effect", dependency="qb", operation="add", outcome="success")]
        failures = _score_recorded_effects(step, journal)
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.APPROVAL_BEHAVIOR

    def test_no_check(self):
        step = AssertStep(kind="assert")
        assert _score_recorded_effects(step, []) == []


class TestScoreFinalFacts:
    def test_submitted_paused(self):
        step = AssertStep(kind="assert", final_facts=["submitted_paused"])
        failures = _score_final_facts(step, "success", "下载已提交到 qBittorrent（暂停状态）", [])
        assert failures == []

    def test_submitted_paused_missing(self):
        step = AssertStep(kind="assert", final_facts=["submitted_paused"])
        failures = _score_final_facts(step, "success", "操作完成。", [])
        assert len(failures) == 1
        assert failures[0].category == FailureCategory.FACTUAL_CONSISTENCY

    def test_operation_failed(self):
        step = AssertStep(kind="assert", final_facts=["operation_failed"])
        failures = _score_final_facts(step, "success", "下载失败：网络错误", [])
        assert failures == []

    def test_not_executed(self):
        step = AssertStep(kind="assert", final_facts=["not_executed"])
        failures = _score_final_facts(step, "success", "未执行任何操作。", [])
        assert failures == []

    def test_awaiting_approval(self):
        step = AssertStep(kind="assert", final_facts=["awaiting_approval"])
        failures = _score_final_facts(step, "awaiting_approval", "", [])
        assert failures == []


class TestScoreTrialIntegration:
    """Full integration test for score_trial."""

    def test_all_pass(self):
        result = score_trial(
            case_id="t1",
            run_id="r1",
            repetition=1,
            label="main",
            assert_steps=[
                AssertStep(kind="assert", status="success", required_calls=[
                    {"name": "mteam_search"},
                ]),
            ],
            tool_calls=[{"tool": "mteam_search", "arguments": {"keyword": "Dune"}}],
            call_journal=[],
            final_answer="搜索完成。",
            status="success",
        )
        assert result.status == TrialStatus.PASS
        assert result.failed_assertions == []

    def test_one_failure(self):
        result = score_trial(
            case_id="t1",
            run_id="r1",
            repetition=1,
            label="main",
            assert_steps=[
                AssertStep(kind="assert", forbidden_calls=["qb_add_torrent"]),
            ],
            tool_calls=[{"tool": "qb_add_torrent", "arguments": {"torrent_id": "101"}}],
            call_journal=[],
            final_answer="已下载。",
            status="success",
        )
        assert result.status == TrialStatus.FAIL
        assert result.primary_failure == FailureCategory.TOOL_SELECTION
        assert len(result.failed_assertions) == 1

    def test_multiple_assert_steps(self):
        result = score_trial(
            case_id="t1",
            run_id="r1",
            repetition=1,
            label="main",
            assert_steps=[
                AssertStep(kind="assert", recorded_effects=0),
                AssertStep(kind="assert", status="awaiting_approval"),
            ],
            tool_calls=[{"tool": "mteam_search", "arguments": {}}],
            call_journal=[],
            final_answer="",
            status="success",
        )
        # recorded_effects=0 passes, but status mismatch fails
        assert result.status == TrialStatus.FAIL
