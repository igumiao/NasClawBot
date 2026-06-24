"""CLI entry point for the NasClawBot agent behavioral evaluation system.

Subcommands::

    .venv/bin/python -m evals run --suite behavioral-v1 [--case CASE]
        [--repetitions N] [--label LABEL]

    .venv/bin/python -m evals compare --baseline PATH --candidate PATH

    .venv/python -m evals save-baseline --result PATH --name NAME
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.compare import CompareResult, compare as compare_reports
from evals.environment import create_trial_environment
from evals.loader import load_suite
from evals.models import SuiteReport, TrialResult, TrialStatus
from evals.runner import run_trial

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────

CASES_DIR = Path("evals/cases")
FIXTURES_DIR = Path("evals/fixtures")
RESULTS_ROOT = Path("eval-results")
BASELINES_DIR = Path("evals/baselines")

# ── Git helpers ──────────────────────────────────────────────────────────


def _get_git_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _is_worktree_dirty() -> bool:
    try:
        result = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return bool(result)
    except Exception:
        return True


# ── Hash helpers ─────────────────────────────────────────────────────────


def _compute_dir_hash(directory: Path, glob_pattern: str = "*.yaml") -> str:
    """Compute a deterministic hash over all matching files in *directory*."""
    if not directory.is_dir():
        return ""
    hasher = hashlib.sha256()
    for path in sorted(directory.glob(glob_pattern)):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


def _compute_suite_hash(suite_name: str) -> str:
    return _compute_dir_hash(CASES_DIR / suite_name, "*.yaml")


def _compute_fixture_hash() -> str:
    return _compute_dir_hash(FIXTURES_DIR, "*.yaml")


# ── Aggregate metrics ────────────────────────────────────────────────────


def _percentile(sorted_values: list[float], p: int) -> float:
    """Return the *p*-th percentile of a sorted list (nearest-rank method)."""
    if not sorted_values:
        return 0.0
    k = max(1, round(len(sorted_values) * p / 100))
    return sorted_values[k - 1]


def _compute_aggregate_metrics(
    trials: list[TrialResult],
    run_id: str,
    suite: str,
    label: str,
    *,
    repetitions: int = 1,
    suite_hash: str = "",
    fixture_hash: str = "",
    fixed_date: str = "",
    fixed_timezone: str = "",
    fixed_download_path: str = "",
) -> SuiteReport:
    """Aggregate a list of TrialResults into a SuiteReport with summary metrics.

    Parameters
    ----------
    trials:
        All trial results for the suite.
    run_id:
        Unique run identifier.
    suite:
        Suite name.
    label:
        Run label (e.g. "main").
    repetitions:
        Number of repetitions per case (default 1).
    suite_hash:
        Deterministic hash over suite case files.
    fixture_hash:
        Deterministic hash over fixture files.
    fixed_date:
        ISO date string used for the run.
    fixed_timezone:
        IANA timezone string used for the run.
    fixed_download_path:
        Download path used for the run.

    Returns
    -------
    SuiteReport
        Fully populated aggregate report.
    """
    # Assign suite name to each trial (the scorer sets it to empty).
    for t in trials:
        t.suite = suite

    total = len(trials)
    passed = sum(1 for t in trials if t.status == TrialStatus.PASS)
    failed = sum(1 for t in trials if t.status == TrialStatus.FAIL)
    invalid = sum(1 for t in trials if t.status == TrialStatus.INVALID)

    valid = total - invalid
    success_rate: float | None = passed / valid if valid > 0 else None

    # Case consistency: a case is consistent only when ALL its repetitions PASS.
    case_results: dict[str, list[str]] = {}
    for t in trials:
        case_results.setdefault(t.case_id, []).append(t.status.value)

    consistent = sum(
        1 for statuses in case_results.values() if all(s == "PASS" for s in statuses)
    )
    case_consistency: float | None = (
        consistent / len(case_results) if case_results else None
    )

    # Failure by category.
    failure_by_category: dict[str, int] = {}
    for t in trials:
        if t.primary_failure:
            cat = t.primary_failure.value
            failure_by_category[cat] = failure_by_category.get(cat, 0) + 1

    # Token / call counters.
    total_tokens = sum(t.token_usage.get("total_tokens", 0) for t in trials)
    total_model_calls = sum(t.model_calls for t in trials)
    total_tool_calls = sum(t.tool_call_count for t in trials)

    cache_hit = sum(
        t.token_usage.get("cache_read_input_tokens", 0) for t in trials
    )
    cache_miss = sum(
        t.token_usage.get("cache_creation_input_tokens", 0) for t in trials
    )

    tokens_per_success: float | None = (
        total_tokens / passed if passed > 0 else None
    )

    # Latency percentiles.
    latencies = sorted(t.latency_ms for t in trials if t.latency_ms > 0)
    latency_n = len(latencies)
    latency_p50: float | None = _percentile(latencies, 50) if latencies else None
    latency_p95: float | None = _percentile(latencies, 95) if latencies else None

    return SuiteReport(
        run_id=run_id,
        suite=suite,
        label=label,
        git_branch=_get_git_branch(),
        git_commit=_get_git_commit(),
        worktree_dirty=_is_worktree_dirty(),
        repetitions=repetitions,
        trials=trials,
        total=total,
        passed=passed,
        failed=failed,
        invalid=invalid,
        success_rate=success_rate,
        case_consistency=case_consistency,
        failure_by_category=failure_by_category,
        case_results=case_results,
        tokens_per_success=tokens_per_success,
        total_tokens=total_tokens,
        total_model_calls=total_model_calls,
        total_tool_calls=total_tool_calls,
        cache_hit_tokens=cache_hit,
        cache_miss_tokens=cache_miss,
        latency_p50_ms=latency_p50,
        latency_p95_ms=latency_p95,
        latency_n=latency_n,
        suite_hash=suite_hash,
        fixture_hash=fixture_hash,
        fixed_date=fixed_date,
        fixed_timezone=fixed_timezone,
        fixed_download_path=fixed_download_path,
    )


# ── Summary markdown formatter ───────────────────────────────────────────


def _format_summary_md(report: SuiteReport) -> str:
    """Render a SuiteReport as a human-readable Markdown summary."""
    lines: list[str] = []
    lines.append(f"# Evaluation Results: {report.suite} ({report.label})")
    lines.append("")

    # ── Run metadata ─────────────────────────────────────────────────────
    lines.append("## Run Metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Run ID | {report.run_id} |")
    lines.append(f"| Suite | {report.suite} |")
    lines.append(f"| Label | {report.label} |")
    lines.append(f"| Repetitions | {report.repetitions} |")
    if report.git_branch:
        commit = report.git_commit[:8] if report.git_commit else ""
        lines.append(
            f"| Git | {report.git_branch} @ {commit}".rstrip(" @") + " |"
        )
    if report.worktree_dirty:
        lines.append("| Worktree | **DIRTY** |")
    if report.fixed_date:
        lines.append(f"| Fixed Date | {report.fixed_date} |")
    if report.fixed_timezone:
        lines.append(f"| Timezone | {report.fixed_timezone} |")
    lines.append("")

    # ── Aggregate metrics ────────────────────────────────────────────────
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Trials | {report.total} |")
    lines.append(f"| Passed | {report.passed} |")
    lines.append(f"| Failed | {report.failed} |")
    lines.append(f"| Invalid | {report.invalid} |")

    if report.success_rate is not None:
        lines.append(f"| Success Rate | {report.success_rate:.1%} |")
    else:
        lines.append("| Success Rate | — |")

    if report.case_consistency is not None:
        lines.append(
            f"| Case Consistency | {report.case_consistency:.1%} |"
        )
    else:
        lines.append("| Case Consistency | — |")

    if report.tokens_per_success is not None:
        lines.append(f"| Tokens per Success | {report.tokens_per_success:,.0f} |")
    else:
        lines.append("| Tokens per Success | — |")

    lines.append(f"| Total Tokens | {report.total_tokens:,} |")
    lines.append(f"| Total Model Calls | {report.total_model_calls} |")
    lines.append(f"| Total Tool Calls | {report.total_tool_calls} |")

    if report.cache_hit_tokens or report.cache_miss_tokens:
        total_cache = report.cache_hit_tokens + report.cache_miss_tokens
        if total_cache > 0:
            hit_rate = report.cache_hit_tokens / total_cache
            lines.append(f"| Cache Hit Rate | {hit_rate:.1%} |")
        lines.append(f"| Cache Hit Tokens | {report.cache_hit_tokens:,} |")
        lines.append(f"| Cache Miss Tokens | {report.cache_miss_tokens:,} |")

    if report.latency_p50_ms is not None:
        lines.append(f"| Latency P50 | {report.latency_p50_ms:,.0f} ms |")
    if report.latency_p95_ms is not None:
        lines.append(f"| Latency P95 | {report.latency_p95_ms:,.0f} ms |")
    if report.latency_n > 0:
        lines.append(f"| Latency Samples | {report.latency_n} |")
    lines.append("")

    # ── Failure breakdown ────────────────────────────────────────────────
    if report.failure_by_category:
        lines.append("## Failure Breakdown")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat in sorted(report.failure_by_category):
            lines.append(f"| {cat} | {report.failure_by_category[cat]} |")
        lines.append("")

    # ── Case results ─────────────────────────────────────────────────────
    lines.append("## Case Results")
    lines.append("")
    lines.append("| Case ID | Statuses | Result |")
    lines.append("|---------|----------|--------|")
    if report.case_results:
        for case_id in sorted(report.case_results):
            statuses = report.case_results[case_id]
            status_str = ", ".join(statuses)
            if all(s == "PASS" for s in statuses):
                result = "OK"
            elif any(s == "PASS" for s in statuses):
                result = "REGRESSION"
            else:
                result = "FAIL"
            lines.append(f"| {case_id} | {status_str} | {result} |")
    lines.append("")

    # ── Hash summary ─────────────────────────────────────────────────────
    lines.append("## Hashes")
    lines.append("")
    lines.append("| Hash | Value |")
    lines.append("|------|-------|")
    for name in [
        "suite_hash",
        "fixture_hash",
        "prompt_template_hash",
        "rendered_prompt_hash",
        "tool_schema_hash",
    ]:
        val = getattr(report, name, "") or ""
        if val:
            lines.append(f"| {name} | `{val}` |")
    lines.append("")

    return "\n".join(lines)


# ── Comparison table formatter ───────────────────────────────────────────


def _format_comparison_table(result: CompareResult) -> str:
    """Render a CompareResult as a human-readable table.

    Prints to a string; callers are responsible for writing to stdout.
    """
    lines: list[str] = []
    lines.append(
        f"Comparison: {result.baseline_label} vs {result.candidate_label}"
    )
    lines.append("")

    if result.compatible:
        lines.append("Compatibility: OK")
    else:
        lines.append("Compatibility: INCOMPATIBLE")
        for reason in result.incompatibility_reasons:
            lines.append(f"  - {reason}")
    lines.append("")

    # ── Metric deltas ────────────────────────────────────────────────────
    # CompareResult only carries deltas, not absolute values.
    # For V1 we show the delta column. The Baseline/Candidate columns are
    # populated with "—" and could be enriched in V2 by passing SuiteReports
    # alongside CompareResult.
    header = f"{'Metric':<28} {'Baseline':<16} {'Candidate':<16} {'Delta':<16}"
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)

    def _fmt_pct(val: float | None) -> str:
        if val is None:
            return "—"
        return f"{val:+.1%}" if abs(val) < 1 else f"{val:+.2%}"

    metric_rows: list[tuple[str, str, str, str]] = []

    if result.success_rate_delta is not None:
        metric_rows.append((
            "success_rate",
            "—",
            "—",
            _fmt_pct(result.success_rate_delta),
        ))
    if result.case_consistency_delta is not None:
        metric_rows.append((
            "case_consistency",
            "—",
            "—",
            _fmt_pct(result.case_consistency_delta),
        ))
    if result.tokens_per_success_delta is not None:
        metric_rows.append((
            "tokens_per_success",
            "—",
            "—",
            f"{result.tokens_per_success_delta:+,.0f}",
        ))

    metric_rows.append((
        "model_calls",
        "—",
        "—",
        f"{result.model_calls_delta:+d}",
    ))
    metric_rows.append((
        "tool_calls",
        "—",
        "—",
        f"{result.tool_calls_delta:+d}",
    ))

    if result.cache_hit_rate_delta is not None:
        metric_rows.append((
            "cache_hit_rate",
            "—",
            "—",
            _fmt_pct(result.cache_hit_rate_delta),
        ))
    if result.latency_p50_delta_ms is not None:
        metric_rows.append((
            "latency_p50_ms",
            "—",
            "—",
            f"{result.latency_p50_delta_ms:+.0f}",
        ))
    if result.latency_p95_delta_ms is not None:
        metric_rows.append((
            "latency_p95_ms",
            "—",
            "—",
            f"{result.latency_p95_delta_ms:+.0f}",
        ))

    for name, base_s, cand_s, delta_s in metric_rows:
        lines.append(f"{name:<28} {base_s:<16} {cand_s:<16} {delta_s:<16}")

    lines.append("")

    # ── New / fixed failures ─────────────────────────────────────────────
    if result.new_failures:
        lines.append(f"New failures ({len(result.new_failures)}):")
        for cid in result.new_failures:
            lines.append(f"  - {cid}")
        lines.append("")

    if result.fixed_failures:
        lines.append(f"Fixed failures ({len(result.fixed_failures)}):")
        for cid in result.fixed_failures:
            lines.append(f"  - {cid}")
        lines.append("")

    # ── Hash changes ─────────────────────────────────────────────────────
    if result.hash_changes:
        lines.append("Hash changes:")
        for hname, (base_val, cand_val) in result.hash_changes.items():
            base_short = base_val[:12] if base_val else "(empty)"
            cand_short = cand_val[:12] if cand_val else "(empty)"
            lines.append(f"  {hname}: {base_short} -> {cand_short}")
        lines.append("")

    return "\n".join(lines)


# ── Subcommand: run ──────────────────────────────────────────────────────


def cmd_run(args: argparse.Namespace) -> None:
    """Execute the ``run`` subcommand."""
    suite_name = args.suite
    label = args.label or "main"
    repetitions = args.repetitions or 1

    run_id = f"eval-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    logger.info("Run ID: %s", run_id)

    # ── Load suite ───────────────────────────────────────────────────────
    cases = load_suite(suite_name, CASES_DIR, FIXTURES_DIR)

    if args.case:
        filtered = [c for c in cases if c.id == args.case]
        if not filtered:
            logger.error("Case '%s' not found in suite '%s'", args.case, suite_name)
            sys.exit(1)
        cases = filtered

    logger.info("Loaded %d case(s) from suite '%s'", len(cases), suite_name)

    # ── Create work directory ────────────────────────────────────────────
    base_work_dir = RESULTS_ROOT / run_id
    base_work_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Work directory: %s", base_work_dir)

    # ── Run trials ───────────────────────────────────────────────────────
    trials: list[TrialResult] = []
    started_at = datetime.now().isoformat()

    for case in cases:
        for rep in range(repetitions):
            logger.info(
                "Running case '%s' repetition %d/%d",
                case.id,
                rep + 1,
                repetitions,
            )

            # Create isolated environment.
            env = create_trial_environment(
                run_id=run_id,
                suite=suite_name,
                case=case,
                repetition=rep,
                label=label,
                base_work_dir=base_work_dir,
            )

            # Run the trial.
            result = run_trial(env, case.steps)
            result.run_id = run_id

            # Retry INVALID once.
            if result.status == TrialStatus.INVALID:
                logger.warning(
                    "Trial %s INVALID (attempt 1), retrying with fresh environment...",
                    env.session_id,
                )
                env.cleanup()
                env = create_trial_environment(
                    run_id=run_id,
                    suite=suite_name,
                    case=case,
                    repetition=rep,
                    label=label,
                    base_work_dir=base_work_dir,
                )
                result = run_trial(env, case.steps)
                result.run_id = run_id
                result.attempt = 2
                if result.status == TrialStatus.INVALID:
                    logger.error(
                        "Trial %s INVALID again after retry — marking final.",
                        env.session_id,
                    )

            trials.append(result)
            env.cleanup()

    finished_at = datetime.now().isoformat()

    # ── Compute hashes ──────────────────────────────────────────────────
    suite_hash = _compute_suite_hash(suite_name)
    fixture_hash = _compute_fixture_hash()

    # ── Aggregate → SuiteReport ──────────────────────────────────────────
    report = _compute_aggregate_metrics(
        trials=trials,
        run_id=run_id,
        suite=suite_name,
        label=label,
        repetitions=repetitions,
        suite_hash=suite_hash,
        fixture_hash=fixture_hash,
    )
    report.started_at = started_at
    report.finished_at = finished_at

    # ── Write artifacts ──────────────────────────────────────────────────
    # summary.json
    summary_path = base_work_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(report.model_dump_json(indent=2, exclude_none=True))
    logger.info("Wrote %s", summary_path)

    # summary.md
    summary_md = _format_summary_md(report)
    md_path = base_work_dir / "summary.md"
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(summary_md)
    logger.info("Wrote %s", md_path)

    # manifest.json
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "suite": suite_name,
        "label": label,
        "repetitions": repetitions,
        "started_at": started_at,
        "finished_at": finished_at,
        "git_branch": _get_git_branch(),
        "git_commit": _get_git_commit(),
        "worktree_dirty": _is_worktree_dirty(),
        "total_trials": len(trials),
        "passed": report.passed,
        "failed": report.failed,
        "invalid": report.invalid,
    }
    manifest_path = base_work_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote %s", manifest_path)

    # Individual trial results
    trials_dir = base_work_dir / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    for t in trials:
        trial_path = trials_dir / f"{t.case_id}-r{t.repetition:02d}.json"
        with open(trial_path, "w", encoding="utf-8") as fh:
            fh.write(t.model_dump_json(indent=2, exclude_none=True))

    logger.info("Wrote %d trial result files", len(trials))

    # ── Print summary to stdout ──────────────────────────────────────────
    print("\n=== Evaluation Complete ===")
    print(f"  Suite:      {suite_name}")
    print(f"  Label:      {label}")
    print(f"  Run ID:     {run_id}")
    print(f"  Cases:      {len(cases)} × {repetitions} rep(s) = {len(trials)} trials")
    print(f"  Passed:     {report.passed}")
    print(f"  Failed:     {report.failed}")
    print(f"  Invalid:    {report.invalid}")
    if report.success_rate is not None:
        print(f"  Rate:       {report.success_rate:.1%}")
    print(f"  Results:    {summary_path}")
    print()


# ── Subcommand: compare ──────────────────────────────────────────────────


def cmd_compare(args: argparse.Namespace) -> None:
    """Execute the ``compare`` subcommand."""
    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)

    if not baseline_path.is_file():
        logger.error("Baseline summary not found: %s", baseline_path)
        sys.exit(1)
    if not candidate_path.is_file():
        logger.error("Candidate summary not found: %s", candidate_path)
        sys.exit(1)

    baseline = SuiteReport.model_validate_json(baseline_path.read_bytes())
    candidate = SuiteReport.model_validate_json(candidate_path.read_bytes())

    result = compare_reports(baseline, candidate)
    table = _format_comparison_table(result)
    print(table)


# ── Subcommand: save-baseline ────────────────────────────────────────────


def cmd_save_baseline(args: argparse.Namespace) -> None:
    """Execute the ``save-baseline`` subcommand."""
    result_path = Path(args.result)
    name = args.name

    if not result_path.is_dir():
        logger.error("Result directory not found: %s", result_path)
        sys.exit(1)

    manifest_path = result_path / "manifest.json"
    if not manifest_path.is_file():
        logger.error(
            "No manifest.json found in %s — is this a valid eval result?",
            result_path,
        )
        sys.exit(1)

    manifest: dict[str, Any] = json.loads(manifest_path.read_bytes())
    if manifest.get("worktree_dirty", True):
        logger.error(
            "Refusing to save baseline from a dirty worktree. "
            "Commit or stash changes first, then re-run."
        )
        sys.exit(1)

    # Create the baseline directory.
    baseline_dir = BASELINES_DIR / name
    baseline_dir.mkdir(parents=True, exist_ok=True)

    # Copy manifest.json
    dest_manifest = baseline_dir / "manifest.json"
    _copy_file(manifest_path, dest_manifest)

    # Copy summary.json
    src_summary = result_path / "summary.json"
    if src_summary.is_file():
        dest_summary = baseline_dir / "summary.json"
        _copy_file(src_summary, dest_summary)
    else:
        logger.warning("No summary.json found in %s", result_path)

    # Copy summary.md
    src_md = result_path / "summary.md"
    if src_md.is_file():
        dest_md = baseline_dir / "summary.md"
        _copy_file(src_md, dest_md)
    else:
        logger.warning("No summary.md found in %s", result_path)

    logger.info("Baseline '%s' saved to %s", name, baseline_dir)
    print(f"Baseline '{name}' saved to {baseline_dir}")


def _copy_file(src: Path, dst: Path) -> None:
    """Copy a single file from *src* to *dst*, preserving mode."""
    import shutil

    shutil.copy2(src, dst)


# ── CLI entry point ──────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(
        description="NasClawBot Agent Behavioral Evaluator",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="Run a full evaluation suite")
    run_p.add_argument(
        "--suite",
        required=True,
        help="Suite name (subdirectory under evals/cases/)",
    )
    run_p.add_argument(
        "--case",
        default=None,
        help="Run only this case ID (optional)",
    )
    run_p.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Number of repetitions per case (default: 1)",
    )
    run_p.add_argument(
        "--label",
        default="main",
        help="Label for this run (default: 'main')",
    )

    # ── compare ──────────────────────────────────────────────────────────
    cmp_p = subparsers.add_parser(
        "compare", help="Compare two suite run summary files"
    )
    cmp_p.add_argument(
        "--baseline",
        required=True,
        help="Path to baseline summary.json",
    )
    cmp_p.add_argument(
        "--candidate",
        required=True,
        help="Path to candidate summary.json",
    )

    # ── save-baseline ────────────────────────────────────────────────────
    sv_p = subparsers.add_parser(
        "save-baseline",
        help="Save a completed run as a named baseline",
    )
    sv_p.add_argument(
        "--result",
        required=True,
        help="Path to the eval result directory (containing manifest.json)",
    )
    sv_p.add_argument(
        "--name",
        required=True,
        help="Name for the baseline (subdirectory under evals/baselines/)",
    )

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "save-baseline":
        cmd_save_baseline(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
