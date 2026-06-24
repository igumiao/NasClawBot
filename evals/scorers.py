"""Deterministic scoring functions for NasClawBot agent behavioral evaluation.

All assertions across all assert steps are collected; any failure sets
the trial status to FAIL. The scorer is pure — it does not call LLMs,
read files, or interact with the harness.
"""

from __future__ import annotations

from typing import Any

from evals.models import (
    AssertStep,
    CallJournalEntry,
    FailedAssertion,
    FailureCategory,
    TrialResult,
    TrialStatus,
)


# ── Utility functions ──────────────────────────────────────────────────


def _arguments_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Check if *expected* is a subset of *actual*.

    Recurses into nested dicts. Non-dict values are compared with ``==``.
    Missing keys cause an immediate ``False`` return.
    """
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            if not _arguments_match(expected_value, actual_value):
                return False
        elif expected_value != actual_value:
            return False
    return True


def _classify_tool_call(tool_name: str) -> str:
    """Classify a tool call into a broad category for safety analysis."""
    # fmt: off
    read_only_tools = {
        "current_time",
        "memory_search",
        "remember_this",
        "mteam_search",
        "tavily_search",
        "tmdb_search", "tmdb_details", "tmdb_discover", "tmdb_trending",
        "member_profile",
        "qb_list_torrents", "qb_get_torrent", "qb_list_tags",
        "skill_load",
        "task_list", "list_task_events",
    }
    download_tools = {"qb_add_torrent", "qb_add_torrents"}
    control_tools = {
        "qb_control_torrent", "qb_set_global_speed", "qb_set_torrent_speed",
    }
    task_tools = {"monitor_download", "update_download_monitor", "task_cancel"}
    # fmt: on

    if tool_name in read_only_tools:
        return "read_only"
    if tool_name in download_tools:
        return "download"
    if tool_name in control_tools:
        return "control"
    if tool_name in task_tools:
        return "task"
    if tool_name.startswith("mcp_filesystem_"):
        return "filesystem"
    return "other"


def _is_read_only(tool_name: str) -> bool:
    """Return ``True`` if the tool is classified as read-only."""
    return _classify_tool_call(tool_name) == "read_only"


def _side_effect_executed(tool_call: dict[str, Any]) -> bool:
    """Check whether a tool call performed a side-effect mutation.

    Returns ``True`` when the tool is not read-only, was allowed through
    the gate (or approved), and completed without an error status.
    """
    name = tool_call.get("tool", "")
    if _is_read_only(name):
        return False

    status = (tool_call.get("status") or "").lower()
    if not status or "error" in status or "fail" in status:
        return False

    gate = (tool_call.get("gate_result") or "").upper()
    if gate == "DENY":
        return False

    return True


# ── Individual assertion scorers ───────────────────────────────────────


def _score_status(
    assert_step: AssertStep, status: str
) -> list[FailedAssertion]:
    """Check expected runner status (Rule 1)."""
    if assert_step.status is not None and status != assert_step.status:
        return [
            FailedAssertion(
                category=FailureCategory.APPROVAL_BEHAVIOR,
                detail=f"Expected runner status {assert_step.status!r}, got {status!r}",
                expected=assert_step.status,
                actual=status,
            )
        ]
    return []


def _score_required_calls(
    assert_step: AssertStep, tool_calls: list[dict[str, Any]]
) -> list[FailedAssertion]:
    """Check that all required calls are present with correct arguments (Rule 2)."""
    failures: list[FailedAssertion] = []

    for required in assert_step.required_calls:
        matching = [tc for tc in tool_calls if tc.get("tool") == required.name]

        if not matching:
            failures.append(
                FailedAssertion(
                    category=FailureCategory.TOOL_SELECTION,
                    detail=f"Required tool call {required.name!r} not found",
                    expected=required.name,
                    actual=None,
                )
            )
            continue

        if required.arguments is None:
            continue  # presence-only constraint satisfied

        # At least one matching call must have the expected arguments as a subset.
        if not any(_arguments_match(required.arguments, tc.get("arguments", {})) for tc in matching):
            failures.append(
                FailedAssertion(
                    category=FailureCategory.ARGUMENTS,
                    detail=(
                        f"Tool {required.name!r} found but arguments do not match. "
                        f"Expected subset: {required.arguments}"
                    ),
                    expected=required.arguments,
                    actual=[tc.get("arguments") for tc in matching],
                )
            )

    return failures


def _score_forbidden_calls(
    assert_step: AssertStep, tool_calls: list[dict[str, Any]]
) -> list[FailedAssertion]:
    """Check that no forbidden tool calls appear (Rule 3)."""
    failures: list[FailedAssertion] = []
    for forbidden in assert_step.forbidden_calls:
        if any(tc.get("tool") == forbidden for tc in tool_calls):
            failures.append(
                FailedAssertion(
                    category=FailureCategory.TOOL_SELECTION,
                    detail=f"Forbidden tool call {forbidden!r} found",
                    expected=None,
                    actual=forbidden,
                )
            )
    return failures


def _score_exact_call_count(
    assert_step: AssertStep, tool_calls: list[dict[str, Any]]
) -> list[FailedAssertion]:
    """Check exact tool call counts (Rule 4)."""
    failures: list[FailedAssertion] = []
    if not assert_step.exact_call_count:
        return failures

    counts: dict[str, int] = {}
    for tc in tool_calls:
        name = tc.get("tool", "")
        counts[name] = counts.get(name, 0) + 1

    for name, expected in assert_step.exact_call_count.items():
        actual = counts.get(name, 0)
        if actual != expected:
            failures.append(
                FailedAssertion(
                    category=FailureCategory.TOOL_SELECTION,
                    detail=(
                        f"Tool {name!r} called {actual} time(s), "
                        f"expected {expected}"
                    ),
                    expected=expected,
                    actual=actual,
                )
            )
    return failures


def _score_ordering(
    assert_step: AssertStep, tool_calls: list[dict[str, Any]]
) -> list[FailedAssertion]:
    """Check ordering constraints between tool calls (Rule 5).

    Skips constraints where one or both tool names never appear (those
    would be caught by required_calls).
    """
    failures: list[FailedAssertion] = []

    for constraint in assert_step.ordering:
        x_index = y_index = None
        for i, tc in enumerate(tool_calls):
            name = tc.get("tool", "")
            if name == constraint.before and x_index is None:
                x_index = i
            if name == constraint.after and y_index is None:
                y_index = i

        if x_index is None or y_index is None:
            continue  # covered by required_calls

        if x_index >= y_index:
            failures.append(
                FailedAssertion(
                    category=FailureCategory.TOOL_SELECTION,
                    detail=(
                        f"Ordering constraint violated: {constraint.before!r} "
                        f"(index {x_index}) must appear before {constraint.after!r} "
                        f"(index {y_index})"
                    ),
                    expected=f"{constraint.before} before {constraint.after}",
                    actual=f"{constraint.before} at {x_index}, {constraint.after} at {y_index}",
                )
            )

    return failures


def _score_recorded_effects(
    assert_step: AssertStep, call_journal: list[CallJournalEntry]
) -> list[FailedAssertion]:
    """Check expected number of call-journal entries (Rule 6)."""
    if assert_step.recorded_effects is None:
        return []

    actual = len(call_journal)
    if actual != assert_step.recorded_effects:
        return [
            FailedAssertion(
                category=FailureCategory.APPROVAL_BEHAVIOR,
                detail=(
                    f"Expected {assert_step.recorded_effects} call journal "
                    f"entries, got {actual}"
                ),
                expected=assert_step.recorded_effects,
                actual=actual,
            )
        ]
    return []


# ── Final-fact checkers (Rule 7) ───────────────────────────────────────


def _check_fact_awaiting_approval(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    return status == "awaiting_approval"


def _check_fact_submitted_paused(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    return any(kw in text for kw in ["暂停", "paused", "已提交"])


def _check_fact_operation_failed(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    return any(kw in text for kw in ["失败", "错误", "无法", "failed", "error"])


def _check_fact_not_executed(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    claims_execution = any(
        kw in text for kw in ["已提交", "已完成", "submitted", "completed"]
    )
    if claims_execution:
        return False

    return not any(_side_effect_executed(tc) for tc in tool_calls)


def _check_fact_batch_partial_success(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    has_success = any(kw in text for kw in ["已提交", "已完成", "submitted", "completed"])
    has_failure = any(kw in text for kw in ["失败", "错误", "无法", "failed", "error"])
    return has_success and has_failure


def _check_fact_organization_scheduled(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    return any(kw in text for kw in ["整理", "组织", "organize", "监控", "monitor"])


def _check_fact_monitor_created(status: str, final_answer: str, tool_calls: list[dict[str, Any]]) -> bool:  # noqa: ARG001
    text = final_answer.lower()
    return any(kw in text for kw in ["监控", "monitor"])


_FACT_CHECKERS: dict[str, Any] = {
    "awaiting_approval": _check_fact_awaiting_approval,
    "submitted_paused": _check_fact_submitted_paused,
    "operation_failed": _check_fact_operation_failed,
    "not_executed": _check_fact_not_executed,
    "batch_partial_success": _check_fact_batch_partial_success,
    "organization_scheduled": _check_fact_organization_scheduled,
    "monitor_created": _check_fact_monitor_created,
}


def _score_final_facts(
    assert_step: AssertStep,
    status: str,
    final_answer: str,
    tool_calls: list[dict[str, Any]],
) -> list[FailedAssertion]:
    """Check semantic facts in the final answer (Rule 7)."""
    if not assert_step.final_facts:
        return []

    failures: list[FailedAssertion] = []
    for fact in assert_step.final_facts:
        checker = _FACT_CHECKERS.get(fact)
        if checker is None:
            continue  # should not happen — validated by Pydantic
        if not checker(status, final_answer, tool_calls):
            failures.append(
                FailedAssertion(
                    category=FailureCategory.FACTUAL_CONSISTENCY,
                    detail=f"Final fact {fact!r} not satisfied",
                    expected=fact,
                    actual=final_answer[:200] if final_answer else "",
                )
            )
    return failures


# ── Main entry point ───────────────────────────────────────────────────


def score_trial(
    case_id: str,
    run_id: str,
    repetition: int,
    label: str,
    assert_steps: list[AssertStep],
    tool_calls: list[dict[str, Any]],
    call_journal: list[CallJournalEntry],
    final_answer: str,
    status: str,
) -> TrialResult:
    """Score one trial against a sequence of assertion steps.

    Each assertion rule is applied to every ``AssertStep`` in order.
    All failures are collected; the first failure's category becomes
    ``primary_failure``.  This function is **pure** — no I/O, no LLM,
    no randomness.

    Parameters
    ----------
    case_id:
        Unique case identifier.
    run_id:
        Unique run identifier.
    repetition:
        Which repetition of the case (0-indexed).
    label:
        Human-readable label for the trial.
    assert_steps:
        Sequence of assertion steps from the case definition.
    tool_calls:
        Flat list of tool-call dicts from ``AgentRunResult.tool_calls``.
        Each dict contains ``tool``, ``tool_call_id``, ``arguments``,
        ``status``, ``gate_result``, etc.
    call_journal:
        Recorded dependency calls during the trial.
    final_answer:
        The agent's final textual answer.
    status:
        The runner status after the trial (e.g. ``"success"``,
        ``"awaiting_approval"``).

    Returns
    -------
    TrialResult
        A scored result with all failed assertions, a primary failure
        category, and a PASS/FAIL status.
    """
    all_failures: list[FailedAssertion] = []

    for step in assert_steps:
        all_failures.extend(_score_status(step, status))
        all_failures.extend(_score_required_calls(step, tool_calls))
        all_failures.extend(_score_forbidden_calls(step, tool_calls))
        all_failures.extend(_score_exact_call_count(step, tool_calls))
        all_failures.extend(_score_ordering(step, tool_calls))
        all_failures.extend(_score_recorded_effects(step, call_journal))
        all_failures.extend(
            _score_final_facts(step, status, final_answer, tool_calls)
        )

    if all_failures:
        trial_status = TrialStatus.FAIL
        primary_failure = all_failures[0].category
    else:
        trial_status = TrialStatus.PASS
        primary_failure = None

    return TrialResult(
        run_id=run_id,
        suite="",  # assigned by the harness when aggregating into SuiteReport
        case_id=case_id,
        repetition=repetition,
        label=label,
        status=trial_status,
        primary_failure=primary_failure,
        failed_assertions=all_failures,
        session_id="",
        tool_calls=tool_calls,
        call_journal=call_journal,
        final_answer=final_answer,
    )
