"""Step executor for behavioral evaluation trials.

Each trial loads an EvalEnvironment, then iterates through the case steps:
user → runner.run() → capture tool calls / status
approve → runner.approve()
deny → runner.deny()
advance_time → advance the logical clock
assert → score immediately against a point-in-time snapshot

The harness distinguishes three failure domains:
  Agent failure  → FAIL  (wrong tool, wrong args, wrong facts, missing approval)
  Harness failure → INVALID (runner crash, checkpoint corruption)
  Provider failure → INVALID (LLM 429/5xx, network interruption)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from evals.environment import EvalEnvironment
from evals.models import (
    AdvanceTimeStep,
    ApproveStep,
    AssertStep,
    CallJournalEntry,
    DenyStep,
    EvalStep,
    FailedAssertion,
    FailureCategory,
    TrialResult,
    TrialStatus,
    UserStep,
)
from evals.scorers import score_assert_snapshot

logger = logging.getLogger(__name__)


class AgentBehaviorError(Exception):
    """The Agent did not behave as the harness expected — a FAIL, not INVALID."""


# ── Step execution ────────────────────────────────────────────────────

def _execute_user_step(
    env: EvalEnvironment,
    step: UserStep,
) -> dict[str, Any]:
    """Run one user turn and return the observable state."""
    result = env.runner.run(env.session_id, step.text)
    return {
        "status": result.status,
        "answer": result.answer,
        "tool_calls": getattr(result, "tool_calls", []) or [],
        "pending_approvals": result.pending_approvals,
        "context_usage": result.context_usage,
        "session_usage": result.session_usage,
    }


def _execute_approve_step(
    env: EvalEnvironment,
    step: ApproveStep,
    turn_state: dict[str, Any],
) -> dict[str, Any]:
    """Approve the current pending approval and return the resumed state.

    Raises :class:`AgentBehaviorError` when there is no pending approval
    to approve — the Agent failed to produce the expected gated tool call.
    """
    pending = turn_state.get("pending_approvals", [])
    if not pending:
        raise AgentBehaviorError(
            "No pending approval to approve — Agent did not produce "
            "the expected gated tool call."
        )
    approval_id = pending[0]["approval_id"]
    result = env.runner.approve(
        env.session_id,
        approval_id,
        decision=step.decision,
    )
    return {
        "status": result.status,
        "answer": result.message,
        "tool_calls": getattr(result, "tool_calls", []) or [],
        "pending_approvals": result.pending_approvals or [],
        "receipt": result.receipt,
        "error": result.error,
        "context_usage": result.context_usage,
        "session_usage": result.session_usage,
    }


def _execute_deny_step(
    env: EvalEnvironment,
    step: DenyStep,
    turn_state: dict[str, Any],
) -> dict[str, Any]:
    """Deny the current pending approval and return the resumed state.

    Raises :class:`AgentBehaviorError` when there is no pending approval
    to deny.
    """
    pending = turn_state.get("pending_approvals", [])
    if not pending:
        raise AgentBehaviorError(
            "No pending approval to deny — Agent did not produce "
            "the expected gated tool call."
        )
    approval_id = pending[0]["approval_id"]
    result = env.runner.deny(env.session_id, approval_id)
    return {
        "status": result.status,
        "answer": result.message,
        "tool_calls": getattr(result, "tool_calls", []) or [],
        "pending_approvals": result.pending_approvals or [],
        "context_usage": result.context_usage,
        "session_usage": result.session_usage,
    }


def _execute_advance_time_step(
    env: EvalEnvironment,
    step: AdvanceTimeStep,
) -> dict[str, Any]:
    """Advance the logical clock for the trial."""
    from datetime import timedelta
    env.clock_offset += timedelta(hours=step.hours)
    logger.info(
        "Advanced clock by %.1f hours (total offset: %s)",
        step.hours,
        env.clock_offset,
    )
    return {}


# ── Trial execution ───────────────────────────────────────────────────

def _merge_tool_calls(
    accumulated: list[dict[str, Any]],
    observed: list[dict[str, Any]],
) -> None:
    """Merge observations by provider tool-call id without double counting resume."""
    index_by_id = {
        str(call.get("tool_call_id")): index
        for index, call in enumerate(accumulated)
        if call.get("tool_call_id")
    }
    for call in observed:
        call_id = str(call.get("tool_call_id") or "")
        if call_id and call_id in index_by_id:
            accumulated[index_by_id[call_id]] = call
        else:
            if call_id:
                index_by_id[call_id] = len(accumulated)
            accumulated.append(call)

def run_trial(
    env: EvalEnvironment,
    steps: list[EvalStep],
) -> TrialResult:
    """Execute a full trial, scoring each assert step immediately.

    Each assert step captures a point-in-time snapshot of the cumulative
    tool calls, call journal, and runner status — so that per-step
    expectations (e.g. ``status: awaiting_approval`` before an approval)
    are evaluated against the state *at that point*, not the trial's
    final state.

    Agent behavior errors (missing approval, wrong tool selection, etc.)
    produce ``FAIL``.  Only true harness/provider failures produce
    ``INVALID``.
    """
    t_start = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    all_tool_calls: list[dict[str, Any]] = []
    all_failures: list[FailedAssertion] = []
    current_answer = ""
    current_status = "success"
    turn_state: dict[str, Any] = {"pending_approvals": []}
    step_index = 0
    harness_agent_calls = 0
    approval_latency_ms = 0.0
    last_token_usage: dict[str, int] = {}
    last_session_usage: dict[str, Any] = {}

    try:
        for step_index, step in enumerate(steps):
            logger.debug(
                "Trial %s step %d: kind=%s",
                env.session_id, step_index, step.kind,
            )

            if isinstance(step, UserStep):
                turn = _execute_user_step(env, step)
                _merge_tool_calls(all_tool_calls, turn["tool_calls"])
                current_answer = turn["answer"]
                current_status = turn["status"]
                turn_state = turn
                harness_agent_calls += 1
                _capture_usage(turn, last_token_usage, last_session_usage)

            elif isinstance(step, ApproveStep):
                t0 = time.monotonic()
                turn = _execute_approve_step(env, step, turn_state)
                if turn.get("tool_calls"):
                    _merge_tool_calls(all_tool_calls, turn["tool_calls"])
                current_answer = turn["answer"]
                current_status = turn["status"]
                turn_state = turn
                harness_agent_calls += 1
                approval_latency_ms += (time.monotonic() - t0) * 1000.0
                _capture_usage(turn, last_token_usage, last_session_usage)

            elif isinstance(step, DenyStep):
                t0 = time.monotonic()
                turn = _execute_deny_step(env, step, turn_state)
                if turn.get("tool_calls"):
                    _merge_tool_calls(all_tool_calls, turn["tool_calls"])
                current_answer = turn["answer"]
                current_status = turn["status"]
                turn_state = turn
                harness_agent_calls += 1
                approval_latency_ms += (time.monotonic() - t0) * 1000.0
                _capture_usage(turn, last_token_usage, last_session_usage)

            elif isinstance(step, AdvanceTimeStep):
                _execute_advance_time_step(env, step)

            elif isinstance(step, AssertStep):
                # ── Score immediately against the current snapshot ─────
                snapshot_calls = list(all_tool_calls)
                snapshot_journal: list[CallJournalEntry] = list(
                    env.call_journal.entries
                )
                failures = score_assert_snapshot(
                    assert_step=step,
                    tool_calls=snapshot_calls,
                    call_journal=snapshot_journal,
                    answer=current_answer,
                    status=current_status,
                )
                if failures:
                    all_failures.extend(failures)
                    # A later approve/deny step must never execute a pending
                    # action that has already failed the case contract.
                    break

            else:
                raise RuntimeError(
                    f"Unknown step kind: {getattr(step, 'kind', '?')}"
                )

    except AgentBehaviorError as exc:
        logger.warning(
            "Trial %s: Agent behavior error at step %d — marking FAIL: %s",
            env.session_id, step_index, exc,
        )
        all_failures.append(
            FailedAssertion(
                category=FailureCategory.APPROVAL_BEHAVIOR,
                detail=str(exc),
            )
        )
    except Exception as exc:
        logger.exception(
            "Trial %s failed with harness error at step %d",
            env.session_id, step_index,
        )
        error_msg = f"Harness error at step {step_index}: {exc}"
        return _invalid_trial_result(
            env=env,
            started_at=started_at,
            error=error_msg,
            tool_calls=all_tool_calls,
            final_answer=current_answer,
        )

    # ── Determine trial status ───────────────────────────────────────
    total_latency_ms = (time.monotonic() - t_start) * 1000.0
    finished_at = datetime.now(timezone.utc).isoformat()
    call_journal_entries = list(env.call_journal.entries)

    if all_failures:
        trial_status = TrialStatus.FAIL
        primary_failure = all_failures[0].category
    else:
        trial_status = TrialStatus.PASS
        primary_failure = None

    model_calls = int(last_session_usage.get("model_calls") or harness_agent_calls)
    llm_latency_ms = float(last_session_usage.get("llm_latency_ms") or 0.0)
    tool_latency_ms = sum(
        float((call.get("stats") or {}).get("time_ms") or 0.0)
        for call in all_tool_calls
    )

    result = TrialResult(
        run_id=env.run_id,
        suite=env.suite,
        case_id=env.case_id,
        repetition=env.repetition,
        label=env.label,
        status=trial_status,
        primary_failure=primary_failure,
        failed_assertions=all_failures,
        session_id=env.session_id,
        tool_calls=all_tool_calls,
        call_journal=call_journal_entries,
        final_answer=current_answer,
        token_usage=last_token_usage,
        model_calls=model_calls,
        tool_call_count=len(all_tool_calls),
        redundant_tool_calls=0,
        latency_ms=total_latency_ms,
        llm_request_latency_ms=llm_latency_ms,
        tool_exec_latency_ms=tool_latency_ms,
        approval_latency_ms=approval_latency_ms,
    )
    result.started_at = started_at
    result.finished_at = finished_at
    return result


def _capture_usage(
    turn: dict[str, Any],
    token_usage: dict[str, int],
    session_usage: dict[str, Any],
) -> None:
    """Extract token usage from a turn result into the mutable accumulators."""
    ctx = turn.get("context_usage") or {}
    sess = turn.get("session_usage") or {}

    if sess:
        session_usage.clear()
        session_usage.update(sess)
        token_usage.clear()
        token_usage.update(
            {
                "total_tokens": int(sess.get("total_tokens") or 0),
                "prompt_tokens": int(sess.get("total_prompt_tokens") or 0),
                "completion_tokens": int(sess.get("total_completion_tokens") or 0),
                "cache_hit_tokens": int(sess.get("total_cache_hit_tokens") or 0),
                "cache_miss_tokens": int(sess.get("total_cache_miss_tokens") or 0),
            }
        )
        return

    token_usage.clear()
    token_usage.update(
        {
            "total_tokens": int(ctx.get("total_tokens") or 0),
            "prompt_tokens": int(ctx.get("prompt_tokens") or 0),
            "completion_tokens": int(ctx.get("completion_tokens") or 0),
            "cache_hit_tokens": int(ctx.get("cache_hit_tokens") or 0),
            "cache_miss_tokens": int(ctx.get("cache_miss_tokens") or 0),
        }
    )


def _invalid_trial_result(
    env: EvalEnvironment,
    started_at: str,
    error: str,
    tool_calls: list[dict[str, Any]],
    final_answer: str,
) -> TrialResult:
    """Build an INVALID trial result for true harness/provider failures."""
    return TrialResult(
        run_id=env.run_id,
        suite=env.suite,
        case_id=env.case_id,
        repetition=env.repetition,
        label=env.label,
        status=TrialStatus.INVALID,
        primary_failure=FailureCategory.INFRASTRUCTURE,
        failed_assertions=[
            FailedAssertion(
                category=FailureCategory.INFRASTRUCTURE,
                detail=error,
            )
        ],
        session_id=env.session_id,
        tool_calls=tool_calls,
        call_journal=list(env.call_journal.entries),
        final_answer=final_answer,
        error=error,
        tool_call_count=len(tool_calls),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
