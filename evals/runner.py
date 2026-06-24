"""Step executor for behavioral evaluation trials.

Each trial loads an EvalEnvironment, then iterates through the case steps:
user → runner.run() → capture tool calls / status
approve → runner.approve()
deny → runner.deny()
advance_time → advance the logical clock
assert → collect assertions (scored at end by scorers.py)

The harness distinguishes three failure domains:
  Agent failure  → FAIL  (wrong tool, wrong args, wrong facts)
  Harness failure → INVALID (runner crash, checkpoint corruption)
  Provider failure → INVALID (LLM 429/5xx, network interruption)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from evals.environment import EvalEnvironment
from evals.models import (
    AdvanceTimeStep,
    ApproveStep,
    AssertStep,
    DenyStep,
    EvalStep,
    FailedAssertion,
    FailureCategory,
    TrialResult,
    TrialStatus,
    UserStep,
)
from evals.scorers import score_trial

logger = logging.getLogger(__name__)


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
        "tool_calls": result.tool_calls,
        "pending_approvals": result.pending_approvals,
        "context_usage": result.context_usage,
        "session_usage": result.session_usage,
    }


def _execute_approve_step(
    env: EvalEnvironment,
    step: ApproveStep,
    turn_state: dict[str, Any],
) -> dict[str, Any]:
    """Approve the current pending approval and return the resumed state."""
    pending = turn_state.get("pending_approvals", [])
    if not pending:
        raise RuntimeError("No pending approval to approve.")
    approval_id = pending[0]["approval_id"]
    result = env.runner.approve(
        env.session_id,
        approval_id,
        decision=step.decision,
    )
    return {
        "status": result.status,
        "answer": result.message,
        "tool_calls": [],
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
    """Deny the current pending approval and return the resumed state."""
    pending = turn_state.get("pending_approvals", [])
    if not pending:
        raise RuntimeError("No pending approval to deny.")
    approval_id = pending[0]["approval_id"]
    result = env.runner.deny(env.session_id, approval_id)
    return {
        "status": result.status,
        "answer": result.message,
        "tool_calls": [],
        "pending_approvals": result.pending_approvals or [],
        "context_usage": result.context_usage,
        "session_usage": result.session_usage,
    }


def _execute_advance_time_step(
    env: EvalEnvironment,
    step: AdvanceTimeStep,
) -> dict[str, Any]:
    """Advance the logical clock for the trial."""
    # The runner's fixed_now is set at construction time.
    # advance_time updates the environment's internal clock so that
    # subsequent tool calls (especially time-sensitive ones) reflect
    # the advanced time.  In V1 this is a simple delta on a stored
    # datetime; the runner would need to be re-created with a new
    # fixed_now for full fidelity.  For now we store the delta and
    # let the scorer use it.
    from datetime import timedelta
    env.clock_offset += timedelta(hours=step.hours)
    logger.info("Advanced clock by %.1f hours (total offset: %s)", step.hours, env.clock_offset)
    return {}


# ── Trial execution ───────────────────────────────────────────────────

def run_trial(
    env: EvalEnvironment,
    steps: list[EvalStep],
) -> TrialResult:
    """Execute a full trial and return the scored result.

    Maintains a running *turn_state* dict that carries pending_approvals
    (and other step-produced state) across approve/deny/user steps.
    On harness/provider failure the trial is marked INVALID.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    all_tool_calls: list[dict[str, Any]] = []
    assert_steps: list[AssertStep] = []
    final_answer = ""
    final_status = "success"
    turn_state: dict[str, Any] = {"pending_approvals": []}
    error: str | None = None

    try:
        for i, step in enumerate(steps):
            logger.debug(
                "Trial %s step %d: kind=%s",
                env.session_id, i, step.kind,
            )

            if isinstance(step, UserStep):
                turn = _execute_user_step(env, step)
                all_tool_calls.extend(turn["tool_calls"])
                final_answer = turn["answer"]
                final_status = turn["status"]
                turn_state = turn

            elif isinstance(step, ApproveStep):
                turn = _execute_approve_step(env, step, turn_state)
                if turn.get("tool_calls"):
                    all_tool_calls.extend(turn["tool_calls"])
                final_answer = turn["answer"]
                final_status = turn["status"]
                turn_state = turn

            elif isinstance(step, DenyStep):
                turn = _execute_deny_step(env, step, turn_state)
                final_answer = turn["answer"]
                final_status = turn["status"]
                turn_state = turn

            elif isinstance(step, AdvanceTimeStep):
                _execute_advance_time_step(env, step)
                # Does not modify turn_state.

            elif isinstance(step, AssertStep):
                assert_steps.append(step)
                # Does not modify turn_state.

            else:
                raise RuntimeError(f"Unknown step kind: {getattr(step, 'kind', '?')}")

    except Exception as exc:
        logger.exception("Trial %s failed with harness error", env.session_id)
        error = f"Harness error at step {i}: {exc}"
        return _invalid_trial_result(
            env=env,
            started_at=started_at,
            error=error,
            tool_calls=all_tool_calls,
            final_answer=final_answer,
        )

    # ── Score the trial ──────────────────────────────────────────────
    finished_at = datetime.now(timezone.utc).isoformat()
    call_journal_entries = list(env.call_journal.entries)

    result = score_trial(
        case_id=env.case_id,
        run_id=env.run_id,
        repetition=env.repetition,
        label=env.label,
        assert_steps=assert_steps,
        tool_calls=all_tool_calls,
        call_journal=call_journal_entries,
        final_answer=final_answer,
        status=final_status,
    )
    result.session_id = env.session_id
    result.call_journal = call_journal_entries
    result.started_at = started_at
    result.finished_at = finished_at
    return result


def _invalid_trial_result(
    env: EvalEnvironment,
    started_at: str,
    error: str,
    tool_calls: list[dict[str, Any]],
    final_answer: str,
) -> TrialResult:
    """Build an INVALID trial result for harness/provider failures."""
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
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
