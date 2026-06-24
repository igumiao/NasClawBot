"""Compare two SuiteReport summaries from different branches/worktrees."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.models import SuiteReport, TrialStatus


# ── CompareResult ────────────────────────────────────────────────────────


@dataclass
class CompareResult:
    """Result of comparing two suite runs."""

    baseline_label: str
    candidate_label: str
    compatible: bool
    incompatibility_reasons: list[str] = field(default_factory=list)
    success_rate_delta: float | None = None
    case_consistency_delta: float | None = None
    new_failures: list[str] = field(default_factory=list)
    fixed_failures: list[str] = field(default_factory=list)
    tokens_per_success_delta: float | None = None
    model_calls_delta: int = 0
    tool_calls_delta: int = 0
    cache_hit_rate_delta: float | None = None
    latency_p50_delta_ms: float | None = None
    latency_p95_delta_ms: float | None = None
    hash_changes: dict[str, tuple[str, str]] = field(default_factory=dict)


# ── Compatibility check ─────────────────────────────────────────────────


def compatibility_check(
    baseline: SuiteReport, candidate: SuiteReport
) -> list[str]:
    """Return list of incompatibility reasons, empty if compatible.

    Requires identical: suite, suite_version, suite_hash, fixture_hash,
    model, temperature, max_steps, repetitions, fixed_date, fixed_timezone,
    fixed_download_path, profile_fixture.
    Allows different: prompt_template_hash, rendered_prompt_hash,
    tool_schema_hash, git_branch, git_commit.
    """
    reasons: list[str] = []

    checks: list[tuple[str, object, object]] = [
        ("suite", baseline.suite, candidate.suite),
        ("suite_version", baseline.suite_version, candidate.suite_version),
        ("suite_hash", baseline.suite_hash, candidate.suite_hash),
        ("fixture_hash", baseline.fixture_hash, candidate.fixture_hash),
        ("model", baseline.model, candidate.model),
        ("temperature", baseline.temperature, candidate.temperature),
        ("max_steps", baseline.max_steps, candidate.max_steps),
        ("repetitions", baseline.repetitions, candidate.repetitions),
        ("fixed_date", baseline.fixed_date, candidate.fixed_date),
        ("fixed_timezone", baseline.fixed_timezone, candidate.fixed_timezone),
        (
            "fixed_download_path",
            baseline.fixed_download_path,
            candidate.fixed_download_path,
        ),
        ("profile_fixture", baseline.profile_fixture, candidate.profile_fixture),
    ]

    for name, base_val, cand_val in checks:
        if base_val != cand_val:
            reasons.append(
                f"{name}: baseline={base_val!r}, candidate={cand_val!r}"
            )

    return reasons


# ── Helper: extract case status map from case_results ───────────────────


def _case_results_to_status_map(
    case_results: dict[str, list[str]],
) -> dict[str, list[TrialStatus]]:
    """Convert SuiteReport.case_results string lists to TrialStatus lists."""
    result: dict[str, list[TrialStatus]] = {}
    for case_id, status_strings in case_results.items():
        result[case_id] = [TrialStatus(s) for s in status_strings]
    return result


# ── Compare ──────────────────────────────────────────────────────────────


def compare(baseline: SuiteReport, candidate: SuiteReport) -> CompareResult:
    """Compare two suite runs and return structured deltas.

    Parameters
    ----------
    baseline:
        The earlier (or reference) suite run.
    candidate:
        The later (or changed) suite run to compare against the baseline.

    Returns
    -------
    CompareResult
        Structured deltas for all metrics, plus lists of new/fixed failures
        and any hash changes.
    """
    reasons = compatibility_check(baseline, candidate)
    compatible = len(reasons) == 0

    # ── Success rate delta ───────────────────────────────────────────────
    success_rate_delta: float | None = None
    if baseline.success_rate is not None and candidate.success_rate is not None:
        success_rate_delta = candidate.success_rate - baseline.success_rate

    # ── Case consistency delta ───────────────────────────────────────────
    case_consistency_delta: float | None = None
    if (
        baseline.case_consistency is not None
        and candidate.case_consistency is not None
    ):
        case_consistency_delta = (
            candidate.case_consistency - baseline.case_consistency
        )

    # ── New failures / fixed failures ────────────────────────────────────
    baseline_case_statuses = _case_results_to_status_map(baseline.case_results)
    candidate_case_statuses = _case_results_to_status_map(candidate.case_results)

    all_case_ids = (
        set(baseline_case_statuses.keys()) | set(candidate_case_statuses.keys())
    )

    new_failures: list[str] = []
    fixed_failures: list[str] = []

    for case_id in sorted(all_case_ids):
        base_statuses = baseline_case_statuses.get(case_id, [])
        cand_statuses = candidate_case_statuses.get(case_id, [])

        base_all_pass = (
            len(base_statuses) > 0
            and all(s == TrialStatus.PASS for s in base_statuses)
        )
        cand_all_pass = (
            len(cand_statuses) > 0
            and all(s == TrialStatus.PASS for s in cand_statuses)
        )

        if base_all_pass and not cand_all_pass:
            new_failures.append(case_id)
        elif not base_all_pass and cand_all_pass:
            fixed_failures.append(case_id)

    # ── Tokens per success delta ─────────────────────────────────────────
    tokens_per_success_delta: float | None = None
    if (
        baseline.tokens_per_success is not None
        and candidate.tokens_per_success is not None
    ):
        tokens_per_success_delta = (
            candidate.tokens_per_success - baseline.tokens_per_success
        )

    # ── Model calls delta ────────────────────────────────────────────────
    model_calls_delta = candidate.total_model_calls - baseline.total_model_calls

    # ── Tool calls delta ─────────────────────────────────────────────────
    tool_calls_delta = candidate.total_tool_calls - baseline.total_tool_calls

    # ── Cache hit rate delta ─────────────────────────────────────────────
    cache_hit_rate_delta: float | None = None
    total_cache_baseline = baseline.cache_hit_tokens + baseline.cache_miss_tokens
    total_cache_candidate = (
        candidate.cache_hit_tokens + candidate.cache_miss_tokens
    )
    if total_cache_baseline > 0 and total_cache_candidate > 0:
        base_rate = baseline.cache_hit_tokens / total_cache_baseline
        cand_rate = candidate.cache_hit_tokens / total_cache_candidate
        cache_hit_rate_delta = cand_rate - base_rate

    # ── Latency deltas ──────────────────────────────────────────────────
    latency_p50_delta_ms: float | None = None
    latency_p95_delta_ms: float | None = None
    if baseline.latency_p50_ms is not None and candidate.latency_p50_ms is not None:
        latency_p50_delta_ms = candidate.latency_p50_ms - baseline.latency_p50_ms
    if baseline.latency_p95_ms is not None and candidate.latency_p95_ms is not None:
        latency_p95_delta_ms = candidate.latency_p95_ms - baseline.latency_p95_ms

    # ── Hash changes ─────────────────────────────────────────────────────
    hash_changes: dict[str, tuple[str, str]] = {}
    hash_fields = [
        "suite_hash",
        "fixture_hash",
        "prompt_template_hash",
        "rendered_prompt_hash",
        "tool_schema_hash",
    ]
    for field_name in hash_fields:
        base_val: Any = getattr(baseline, field_name, "")
        cand_val: Any = getattr(candidate, field_name, "")
        if base_val != cand_val:
            hash_changes[field_name] = (
                str(base_val) if base_val else "",
                str(cand_val) if cand_val else "",
            )

    return CompareResult(
        baseline_label=baseline.label,
        candidate_label=candidate.label,
        compatible=compatible,
        incompatibility_reasons=reasons,
        success_rate_delta=success_rate_delta,
        case_consistency_delta=case_consistency_delta,
        new_failures=new_failures,
        fixed_failures=fixed_failures,
        tokens_per_success_delta=tokens_per_success_delta,
        model_calls_delta=model_calls_delta,
        tool_calls_delta=tool_calls_delta,
        cache_hit_rate_delta=cache_hit_rate_delta,
        latency_p50_delta_ms=latency_p50_delta_ms,
        latency_p95_delta_ms=latency_p95_delta_ms,
        hash_changes=hash_changes,
    )
