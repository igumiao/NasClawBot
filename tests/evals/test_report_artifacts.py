import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import __main__ as eval_cli
from evals.models import FailureCategory, TrialResult, TrialStatus
from evals.report import archive_failure_bundle


def test_archive_failure_bundle_preserves_debug_artifacts(tmp_path: Path) -> None:
    work_dir = tmp_path / "trial-work"
    checkpoint_dir = work_dir / "checkpoints"
    trace_dir = work_dir / "traces"
    checkpoint_dir.mkdir(parents=True)
    trace_dir.mkdir(parents=True)
    session_id = "eval-session"
    (checkpoint_dir / f"{session_id}.json").write_text('{"history": []}')
    (trace_dir / f"trace-{session_id}.jsonl").write_text('{"event":"x"}\n')

    cleanup_calls: list[tuple[str, str]] = []
    runner = SimpleNamespace(
        cleanup_session_trace=lambda sid, root: cleanup_calls.append((sid, root))
    )
    env = SimpleNamespace(
        work_dir=work_dir,
        session_id=session_id,
        trace_root=trace_dir,
        runner=runner,
    )
    result = TrialResult(
        run_id="run-1",
        suite="behavioral-v1",
        case_id="broken-case",
        repetition=0,
        label="main",
        status=TrialStatus.FAIL,
        primary_failure=FailureCategory.TOOL_SELECTION,
    )

    bundle = archive_failure_bundle(env, result, tmp_path / "result")

    assert cleanup_calls == [(session_id, str(trace_dir))]
    assert json.loads((bundle / "checkpoint.json").read_text()) == {"history": []}
    assert (bundle / "trace.jsonl").read_text() == '{"event":"x"}\n'
    assert json.loads((bundle / "call-journal.json").read_text()) == []
    assert json.loads((bundle / "failure.json").read_text())["status"] == "FAIL"


def test_save_baseline_rejects_unresolved_invalid_trials(
    tmp_path: Path, monkeypatch
) -> None:
    result_dir = tmp_path / "run"
    result_dir.mkdir()
    (result_dir / "manifest.json").write_text(
        json.dumps({"worktree_dirty": False, "aggregate": {"invalid": 1}})
    )
    monkeypatch.setattr(eval_cli, "BASELINES_DIR", tmp_path / "baselines")

    with pytest.raises(SystemExit):
        eval_cli.cmd_save_baseline(
            SimpleNamespace(result=str(result_dir), name="should-not-save")
        )
