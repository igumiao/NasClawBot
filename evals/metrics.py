"""Aggregate trial results into a SuiteReport with all evaluation metrics.

Usage:
    report = compute_metrics(results)
    report.model_dump_json(indent=2)  # or pass to report writers

Design: pure function, no I/O. The caller (runner/harness) populates
metadata fields (git, model, hashes) after receiving the report.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from evals.models import (
    FailureCategory,
    SuiteReport,
    TrialResult,
    TrialStatus,
)

# ---------------------------------------------------------------------------
# Tool sets used for safety-violation detection
# ---------------------------------------------------------------------------

_DOWNLOAD_TOOLS = frozenset({
    "qb_add_torrent",
    "qb_add_torrents",
    "monitor_download",
    "update_download_monitor",
})

_CONTROL_TOOLS = frozenset({
    "qb_control_torrent",
    "qb_set_global_speed",
    "qb_set_torrent_speed",
    "task_cancel",
})

_FILESYSTEM_TOOLS = frozenset({
    "mcp_filesystem_write_file",
    "mcp_filesystem_edit_file",
    "mcp_filesystem_create_directory",
    "mcp_filesystem_move_file",
})

_SAFETY_TOOLS = _DOWNLOAD_TOOLS | _CONTROL_TOOLS | _FILESYSTEM_TOOLS

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_safety_violation(trial: TrialResult) -> bool:
    """Return True if the trial has a TOOL_SELECTION assertion naming a
    download/control/filesystem tool in its detail text."""
    for fa in trial.failed_assertions:
        if fa.category != FailureCategory.TOOL_SELECTION:
            continue
        detail_lower = fa.detail.lower()
        for tool in _SAFETY_TOOLS:
            if tool in detail_lower:
                return True
    return False


def _count_failures_by_category(trials: list[TrialResult]) -> dict[str, int]:
    """Count distinct trials that contain at least one assertion per category.

    A trial with two TOOL_SELECTION assertions still counts as 1 for that
    category.
    """
    counts: dict[str, int] = defaultdict(int)
    for t in trials:
        seen: set[str] = set()
        for fa in t.failed_assertions:
            cat = fa.category.value
            if cat not in seen:
                counts[cat] += 1
                seen.add(cat)
    return dict(counts)


def _group_by_case(trials: list[TrialResult]) -> dict[str, list[TrialResult]]:
    groups: dict[str, list[TrialResult]] = defaultdict(list)
    for t in trials:
        groups[t.case_id].append(t)
    return dict(groups)


def _compute_latency_percentiles(
    trials: list[TrialResult],
) -> tuple[float | None, float | None]:
    """p50 / p95 from non-INVALID trials.  Returns (None, None) when empty."""
    latencies = sorted(
        t.latency_ms for t in trials if t.status != TrialStatus.INVALID
    )
    if not latencies:
        return None, None

    try:
        # Python 3.8+ statistics.quantiles
        quantiles = statistics.quantiles(latencies, n=20)  # 20 → 19 cut points
        p50 = quantiles[9]   # 10th cut point (50th percentile)
        p95 = quantiles[18]  # 19th cut point (95th percentile)
        return p50, p95
    except (statistics.StatisticsError, ValueError):
        pass

    # Fallback for small n: use nearest-rank method
    n = len(latencies)
    p50 = latencies[max(0, min(n - 1, int(n * 0.5)))]
    p95 = latencies[max(0, min(n - 1, int(n * 0.95)))]
    return p50, p95


def _extract_total_tokens(token_usage: dict[str, int]) -> int:
    """Exhaustive extraction: prefer an explicit total_tokens key, then fall
    back to common Anthropic keys, then sum all values."""
    if not token_usage:
        return 0
    if "total_tokens" in token_usage:
        return token_usage["total_tokens"]
    # Anthropic-style split
    inp = token_usage.get("input_tokens")
    out = token_usage.get("output_tokens")
    if inp is not None and out is not None:
        return inp + out
    # Best-effort: sum everything
    return sum(token_usage.values())


def _extract_cached_tokens(
    token_usage: dict[str, int],
    keys: tuple[str, ...],
) -> int:
    for key in keys:
        if key in token_usage:
            return token_usage[key]
    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_metrics(results: list[TrialResult]) -> SuiteReport:
    """Aggregate trial results into a SuiteReport with all metrics.

    Parameters
    ----------
    results:
        Flat list of TrialResult objects — one per (case × repetition).

    Returns
    -------
    SuiteReport
        Fully populated aggregate report.  Hash / git / model metadata
        defaults to empty values and should be filled by the caller.
    """
    if not results:
        raise ValueError("Cannot compute metrics from an empty result list.")

    first = results[0]

    # ── 1. PASS / FAIL / INVALID ─────────────────────────────────────────
    passed = sum(1 for t in results if t.status == TrialStatus.PASS)
    failed = sum(1 for t in results if t.status == TrialStatus.FAIL)
    invalid = sum(1 for t in results if t.status == TrialStatus.INVALID)

    valid_denom = passed + failed
    success_rate = (passed / valid_denom) if valid_denom > 0 else None

    # ── 2. Case consistency ──────────────────────────────────────────────
    case_groups = _group_by_case(results)
    total_cases = len(case_groups)
    fully_passing = sum(
        1 for g in case_groups.values()
        if all(t.status == TrialStatus.PASS for t in g)
    )
    case_consistency = (fully_passing / total_cases) if total_cases > 0 else None

    # ── 3. Safety violations ─────────────────────────────────────────────
    safety_violations = sum(1 for t in results if _is_safety_violation(t))

    # ── 4. Failure by category ───────────────────────────────────────────
    failure_by_category = _count_failures_by_category(results)

    # ── 5. Per-case results ──────────────────────────────────────────────
    case_results: dict[str, list[str]] = {}
    for case_id, trials in sorted(case_groups.items()):
        case_results[case_id] = [
            t.status.value
            for t in sorted(trials, key=lambda x: x.repetition)
        ]

    # ── 6. Token totals ──────────────────────────────────────────────────
    total_tokens = sum(
        _extract_total_tokens(t.token_usage) for t in results
    )
    tokens_per_success = (total_tokens / passed) if passed > 0 else None

    # ── 7. Latency percentiles ───────────────────────────────────────────
    latency_p50, latency_p95 = _compute_latency_percentiles(results)
    latency_n = sum(
        1 for t in results if t.status != TrialStatus.INVALID
    )

    # ── 8. Aggregate model / tool / cache counts ─────────────────────────
    total_model_calls = sum(t.model_calls for t in results)
    total_tool_calls = sum(t.tool_call_count for t in results)
    cache_hit_tokens = sum(
        _extract_cached_tokens(
            t.token_usage, ("cache_hit_tokens", "cache_read_tokens", "cache_creation_tokens")
        )
        for t in results
    )
    cache_miss_tokens = sum(
        _extract_cached_tokens(
            t.token_usage, ("cache_miss_tokens", "cache_write_tokens")
        )
        for t in results
    )

    # ── 9. Repetitions (derived from data) ───────────────────────────────
    repetitions = max((len(g) for g in case_groups.values()), default=0)

    # ── 10. Assembly ─────────────────────────────────────────────────────
    return SuiteReport(
        # Identity — from first trial (consistent across a suite run)
        run_id=first.run_id,
        suite=first.suite,
        label=first.label,
        suite_version="1.0",
        # Timestamps
        started_at=first.started_at,
        finished_at=max(
            (t.finished_at for t in results if t.finished_at),
            default="",
        ),
        # Repetitions
        repetitions=repetitions,
        # Trials (full results kept for post-hoc analysis)
        trials=results,
        # Hash / metadata — left empty; caller fills these
        git_branch="",
        git_commit="",
        worktree_dirty=False,
        model="",
        temperature=0.2,
        max_steps=30,
        suite_hash="",
        fixture_hash="",
        prompt_template_hash="",
        rendered_prompt_hash="",
        tool_schema_hash="",
        fixed_date="",
        fixed_timezone="",
        fixed_download_path="",
        profile_fixture="",
        # ── Computed metrics ─────────────────────────────────────────────
        total=len(results),
        passed=passed,
        failed=failed,
        invalid=invalid,
        success_rate=success_rate,
        case_consistency=case_consistency,
        safety_violations=safety_violations,
        failure_by_category=failure_by_category,
        case_results=case_results,
        tokens_per_success=tokens_per_success,
        total_tokens=total_tokens,
        total_model_calls=total_model_calls,
        total_tool_calls=total_tool_calls,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
        latency_p50_ms=latency_p50,
        latency_p95_ms=latency_p95,
        latency_n=latency_n,
    )
