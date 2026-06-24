"""Report writers for the NasClawBot agent behavioral evaluation system.

Produces four output artifacts inside a report directory:

    report/
    ├── summary.md       # Human-readable aggregate metrics
    ├── summary.json     # Machine-readable aggregate metrics (no trials)
    ├── trials.jsonl     # One JSON object per trial
    └── manifest.json    # Run metadata and all hashes

Usage:
    from evals.report import write_summary_markdown, write_summary_json, …

    report = compute_metrics(results)
    out = Path("evals/output/my-run")
    write_summary_markdown(report, out / "summary.md")
    write_summary_json(report, out / "summary.json")
    write_trials_jsonl(results, out / "trials.jsonl")
    write_manifest(report, out / "manifest.json")
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.models import SuiteReport, TrialResult

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value < 1000:
        return f"{value:.0f} ms"
    return f"{value / 1000:.2f} s"


def _status_icon(status: str) -> str:
    if status == "PASS":
        return "PASS"
    if status == "FAIL":
        return "FAIL"
    return "INV"


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------


def write_summary_markdown(report: SuiteReport, output_path: Path) -> None:
    """Write summary.md with human-readable aggregate metrics."""
    lines: list[str] = []

    # ── Title block ──────────────────────────────────────────────────────
    lines.append(f"# Eval Summary: {report.label}")
    lines.append("")
    lines.append(f"- **Suite:** `{report.suite}`")
    lines.append(f"- **Run ID:** `{report.run_id}`")
    lines.append(f"- **Model:** {report.model or '(not set)'}")
    lines.append(f"- **Temperature:** {report.temperature}")
    lines.append(f"- **Max steps:** {report.max_steps}")
    lines.append(f"- **Repetitions:** {report.repetitions}")
    lines.append(f"- **Git commit:** `{report.git_commit or '(not set)'}`")
    lines.append(f"- **Git branch:** `{report.git_branch or '(not set)'}`")
    if report.worktree_dirty:
        lines.append("- **Worktree:** dirty")
    lines.append("")

    # ── Overall Results ──────────────────────────────────────────────────
    lines.append("## Overall Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total trials | {report.total} |")
    lines.append(f"| PASS | {report.passed} |")
    lines.append(f"| FAIL | {report.failed} |")
    lines.append(f"| INVALID | {report.invalid} |")
    if report.success_rate is not None:
        lines.append(f"| Success rate | {report.success_rate:.1%} |")
    else:
        lines.append("| Success rate | N/A |")
    if report.case_consistency is not None:
        lines.append(f"| Case consistency | {report.case_consistency:.1%} |")
    else:
        lines.append("| Case consistency | N/A |")
    lines.append(f"| Safety violations | {report.safety_violations} |")
    lines.append("")

    # ── Per-Case Breakdown ───────────────────────────────────────────────
    # Build repetition column headers dynamically
    rep_count = max(
        (len(v) for v in report.case_results.values()),
        default=0,
    )
    if report.case_results and rep_count > 0:
        lines.append("## Per-Case Breakdown")
        lines.append("")
        headers = ["Case ID"] + [f"Rep {i + 1}" for i in range(rep_count)]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for case_id in sorted(report.case_results):
            statuses = report.case_results[case_id]
            # Pad row to rep_count columns if a case has fewer reps
            padded = [_status_icon(s) for s in statuses]
            while len(padded) < rep_count:
                padded.append("-")
            row = " | ".join([case_id] + padded)
            lines.append(f"| {row} |")
        lines.append("")

    # ── Failure Category Distribution ────────────────────────────────────
    if report.failure_by_category:
        lines.append("## Failure Category Distribution")
        lines.append("")
        lines.append("| Category | Trials |")
        lines.append("|----------|--------|")
        for cat, count in sorted(
            report.failure_by_category.items(), key=lambda x: -x[1]
        ):
            lines.append(f"| {cat} | {count} |")
        lines.append("")

    # ── Safety ───────────────────────────────────────────────────────────
    if report.safety_violations > 0:
        lines.append("## Safety")
        lines.append("")
        lines.append(
            f"**{report.safety_violations} safety violation(s)** detected — "
            f"`tool_selection` assertions matching download, control, or "
            f"filesystem tools that should not have been called."
        )
        lines.append("")

    # ── Token & Cost Efficiency ──────────────────────────────────────────
    lines.append("## Token & Cost Efficiency")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total tokens | {report.total_tokens:,} |")
    if report.tokens_per_success is not None:
        lines.append(f"| Tokens per success | {report.tokens_per_success:,.0f} |")
    else:
        lines.append("| Tokens per success | N/A |")
    lines.append(f"| Total model calls | {report.total_model_calls:,} |")
    lines.append(f"| Total tool calls | {report.total_tool_calls:,} |")
    if report.passed > 0:
        mc_ps = report.total_model_calls / report.passed
        lines.append(f"| Model calls per success | {mc_ps:.1f} |")
        tc_ps = report.total_tool_calls / report.passed
        lines.append(f"| Tool calls per success | {tc_ps:.1f} |")
    lines.append(f"| Cache hit tokens | {report.cache_hit_tokens:,} |")
    lines.append(f"| Cache miss tokens | {report.cache_miss_tokens:,} |")
    total_cache = report.cache_hit_tokens + report.cache_miss_tokens
    if total_cache > 0:
        hit_rate = report.cache_hit_tokens / total_cache
        lines.append(f"| Cache hit rate | {hit_rate:.1%} |")
    lines.append("")

    # ── Latency ──────────────────────────────────────────────────────────
    lines.append("## Latency")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| p50 (median) | {_fmt_ms(report.latency_p50_ms)} |")
    lines.append(f"| p95 | {_fmt_ms(report.latency_p95_ms)} |")
    lines.append(f"| Sample count (n) | {report.latency_n} |")
    lines.append("")

    # ── Failure Cases ────────────────────────────────────────────────────
    failed_case_ids = sorted(
        case_id
        for case_id, statuses in report.case_results.items()
        if any(s == "FAIL" for s in statuses)
    )
    if failed_case_ids:
        lines.append("## Failure Cases")
        lines.append("")
        for case_id in failed_case_ids:
            lines.append(f"- `{case_id}`")
        lines.append("")
        lines.append(
            "> Failure bundles are not yet tracked. "
            "See `trials.jsonl` for per-trial assertion details."
        )
        lines.append("")

    # ── Write ────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# summary.json
# ---------------------------------------------------------------------------


def write_summary_json(report: SuiteReport, output_path: Path) -> None:
    """Write summary.json with machine-readable aggregate metrics.

    Excludes the full ``trials`` list to keep the file small; use
    ``trials.jsonl`` for per-trial data.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report.model_dump_json(indent=2, exclude={"trials"}, exclude_none=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# trials.jsonl
# ---------------------------------------------------------------------------


def write_trials_jsonl(results: list[TrialResult], output_path: Path) -> None:
    """Write trials.jsonl with one JSON object per trial."""
    if not results:
        # Write empty file rather than fail
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for t in results:
            f.write(t.model_dump_json(exclude_none=True))
            f.write("\n")


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


def write_manifest(report: SuiteReport, output_path: Path) -> None:
    """Write manifest.json with run metadata and all hashes."""
    manifest = {
        "run_id": report.run_id,
        "suite": report.suite,
        "suite_version": report.suite_version,
        "label": report.label,
        "model": report.model,
        "temperature": report.temperature,
        "max_steps": report.max_steps,
        "repetitions": report.repetitions,
        "git_branch": report.git_branch,
        "git_commit": report.git_commit,
        "worktree_dirty": report.worktree_dirty,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "hashes": {
            "suite": report.suite_hash,
            "fixture": report.fixture_hash,
            "prompt_template": report.prompt_template_hash,
            "rendered_prompt": report.rendered_prompt_hash,
            "tool_schema": report.tool_schema_hash,
        },
        "fixed": {
            "date": report.fixed_date,
            "timezone": report.fixed_timezone,
            "download_path": report.fixed_download_path,
        },
        "profile_fixture": report.profile_fixture,
        "aggregate": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "invalid": report.invalid,
            "success_rate": report.success_rate,
            "case_consistency": report.case_consistency,
            "safety_violations": report.safety_violations,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
