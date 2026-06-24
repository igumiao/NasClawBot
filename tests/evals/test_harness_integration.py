from pathlib import Path
from types import SimpleNamespace
import json

import yaml

from evals import __main__ as eval_cli
from evals.loader import load_case
from evals.models import TrialResult, TrialStatus
from evals.recording import CallJournal
from evals.runner import run_trial


def test_simple_download_case_passes_through_step_executor() -> None:
    case = load_case(
        Path("evals/cases/behavioral-v1/04-simple-download-notify.yaml"),
        Path("evals/fixtures"),
    )
    journal = CallJournal()

    class FakeRunner:
        def run(self, session_id: str, message: str):
            return SimpleNamespace(
                status="awaiting_approval",
                answer="等待确认。",
                tool_calls=[
                    {
                        "tool": "mteam_search",
                        "arguments": {"keyword": "Dune 2021 2160p"},
                        "status": "success",
                        "gate_result": "allow",
                    },
                    {
                        "tool": "qb_add_torrent",
                        "arguments": {
                            "torrent_id": "101",
                            "completion_action": "notify",
                        },
                        "status": "pending_approval",
                        "gate_result": "ask_user",
                    },
                ],
                pending_approvals=[{"approval_id": "approval-1"}],
                context_usage={},
                session_usage={},
            )

        def approve(self, session_id: str, approval_id: str, decision: str):
            journal.record(
                "download",
                "submit_downloads",
                {"torrent_id": "101"},
                kind="effect",
            )
            return SimpleNamespace(
                status="approved",
                message="已提交并保持暂停。",
                pending_approvals=[],
                receipt={},
                error=None,
                context_usage={},
                session_usage={},
            )

    env = SimpleNamespace(
        runner=FakeRunner(),
        session_id="eval-test",
        call_journal=journal,
        case_id=case.id,
        run_id="run-test",
        repetition=0,
        label="test",
        suite="behavioral-v1",
    )

    result = run_trial(env, case.steps)

    assert result.status == TrialStatus.PASS


def test_failed_assertion_stops_before_approving_wrong_pending_tool() -> None:
    case = load_case(
        Path("evals/cases/behavioral-v1/04-simple-download-notify.yaml"),
        Path("evals/fixtures"),
    )

    class FakeRunner:
        approve_called = False

        def run(self, session_id: str, message: str):
            return SimpleNamespace(
                status="awaiting_approval",
                answer="等待确认。",
                tool_calls=[
                    {
                        "tool": "task_cancel",
                        "tool_call_id": "wrong-call",
                        "arguments": {"task_id": "task-1"},
                        "status": "pending_approval",
                        "gate_result": "ask_user",
                    }
                ],
                pending_approvals=[{"approval_id": "wrong-approval"}],
                context_usage={},
                session_usage={},
            )

        def approve(self, session_id: str, approval_id: str, decision: str):
            self.approve_called = True
            raise AssertionError("wrong pending action must not be approved")

    runner = FakeRunner()
    env = SimpleNamespace(
        runner=runner,
        session_id="eval-wrong-pending",
        call_journal=CallJournal(),
        case_id=case.id,
        run_id="run-test",
        repetition=0,
        label="test",
        suite="behavioral-v1",
    )

    result = run_trial(env, case.steps)

    assert result.status == TrialStatus.FAIL
    assert runner.approve_called is False


def test_usage_comes_from_cumulative_runner_session_usage() -> None:
    class FakeRunner:
        def run(self, session_id: str, message: str):
            return SimpleNamespace(
                status="success",
                answer="完成。",
                tool_calls=[
                    {
                        "tool": "current_time",
                        "tool_call_id": "call-time",
                        "arguments": {},
                        "status": "success",
                        "gate_result": "allow",
                        "stats": {"time_ms": 7},
                    }
                ],
                pending_approvals=[],
                context_usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cache_hit_tokens": 40,
                    "cache_miss_tokens": 60,
                },
                session_usage={
                    "model_calls": 3,
                    "total_tokens": 350,
                    "total_prompt_tokens": 300,
                    "total_completion_tokens": 50,
                    "total_cache_hit_tokens": 100,
                    "total_cache_miss_tokens": 200,
                    "llm_latency_ms": 123,
                },
            )

    env = SimpleNamespace(
        runner=FakeRunner(),
        session_id="eval-usage",
        call_journal=CallJournal(),
        case_id="usage-case",
        run_id="run-test",
        repetition=0,
        label="test",
        suite="behavioral-v1",
    )
    steps = [
        SimpleNamespace(kind="user", text="测试"),
    ]
    # Use the real Pydantic step so isinstance dispatch follows production.
    from evals.models import UserStep

    result = run_trial(env, [UserStep(text="测试")])

    assert result.token_usage == {
        "total_tokens": 350,
        "prompt_tokens": 300,
        "completion_tokens": 50,
        "cache_hit_tokens": 100,
        "cache_miss_tokens": 200,
    }
    assert result.model_calls == 3
    assert result.llm_request_latency_ms == 123
    assert result.tool_exec_latency_ms == 7


def test_cli_run_writes_artifacts_and_returns_cleanly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    results_root = tmp_path / "results"
    suite_dir = cases_dir / "smoke"
    suite_dir.mkdir(parents=True)
    fixtures_dir.mkdir(parents=True)
    (fixtures_dir / "base-world.yaml").write_text("name: base-world\n")
    (suite_dir / "01-smoke.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "smoke-case",
                "title": "Smoke",
                "category": "read_only",
                "steps": [{"kind": "user", "text": "test"}],
            },
            sort_keys=False,
        )
    )

    class FakeEnvironment:
        session_id = "smoke-session"
        fixed_now = SimpleNamespace(date=lambda: "2026-06-15")
        configuration_snapshot = {
            "model": "eval-model",
            "temperature": 0.2,
            "max_steps": 30,
            "prompt_template": "stable prompt template",
            "rendered_prompt": "stable prompt template\ncurrent date: 2026-06-15",
            "tool_schemas": [{"type": "function", "function": {"name": "tool_a"}}],
            "timezone": "Asia/Shanghai",
            "download_path": "/eval/downloads",
            "profile_fixture": "empty-v1",
            "fixed_date": "2026-06-15",
        }

        def cleanup(self) -> None:
            pass

    def fake_result(env, steps):
        return TrialResult(
            run_id="placeholder",
            suite="smoke",
            case_id="smoke-case",
            repetition=0,
            label="smoke",
            status=TrialStatus.PASS,
            started_at="2026-06-24T00:00:00+00:00",
            finished_at="2026-06-24T00:00:01+00:00",
        )

    monkeypatch.setattr(eval_cli, "CASES_DIR", cases_dir)
    monkeypatch.setattr(eval_cli, "FIXTURES_DIR", fixtures_dir)
    monkeypatch.setattr(eval_cli, "RESULTS_ROOT", results_root)
    monkeypatch.setattr(eval_cli, "create_trial_environment", lambda **kwargs: FakeEnvironment())
    monkeypatch.setattr(eval_cli, "run_trial", fake_result)
    monkeypatch.setattr(eval_cli, "_get_git_branch", lambda: "main")
    monkeypatch.setattr(eval_cli, "_get_git_commit", lambda: "abc123")
    monkeypatch.setattr(eval_cli, "_is_worktree_dirty", lambda: False)

    eval_cli.cmd_run(
        SimpleNamespace(suite="smoke", case=None, repetitions=1, label="smoke")
    )

    run_dirs = list(results_root.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "trials.jsonl").is_file()
    assert (run_dir / "manifest.json").is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["model"] == "eval-model"
    assert manifest["hashes"]["prompt_template"]
    assert manifest["hashes"]["rendered_prompt"]
    assert manifest["hashes"]["tool_schema"]
    assert manifest["profile_fixture"] == "empty-v1"
    assert "Results:" in capsys.readouterr().out
